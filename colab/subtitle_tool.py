"""One-link subtitles for Erikiss/yt-dlp; also embedded in the Colab notebook.

No server, account cookies or API keys. Only standard-library imports until
yt-dlp / optional faster-whisper are actually needed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import io
import json
import math
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import wave
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse


TOOL_VERSION = 1
CHUNK_SECONDS = 600
CONTEXT_SECONDS = 3
WHISPER_PACKAGES = ('faster-whisper==1.2.1', 'av==18.1.0')


class SubtitleError(RuntimeError):
    """An actionable, user-facing failure."""

    def __init__(self, message, *, details=''):
        super().__init__(message)
        self.details = details


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class Result:
    title: str
    source: str
    language: str
    directory: Path
    files: list[Path]
    archive: Path


def youtube_url(value: str) -> str:
    """Accept one YouTube video, discard tracking and playlist parameters."""
    value = value.strip()
    if not value:
        raise SubtitleError('Bitte zuerst einen YouTube-Link einfügen.')
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
        video_id = value
    else:
        if value.startswith(('www.', 'm.', 'youtube.com/', 'youtu.be/')):
            value = 'https://' + value
        parsed = urlparse(value)
        host = (parsed.hostname or '').lower()
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
            raise SubtitleError('Bitte einen gültigen YouTube-Videolink einfügen.')
        if host == 'youtu.be':
            video_id = parsed.path.strip('/').split('/')[0]
        elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com',
                      'music.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'):
            pieces = parsed.path.strip('/').split('/')
            if parsed.path.rstrip('/') == '/watch':
                video_id = parse_qs(parsed.query).get('v', [''])[0]
            elif len(pieces) == 2 and pieces[0] in ('shorts', 'live', 'embed', 'v'):
                video_id = pieces[1]
            else:
                video_id = ''
        else:
            raise SubtitleError('Dieser Einstieg akzeptiert ausschließlich YouTube-Videolinks.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise SubtitleError('Kein einzelnes Video gefunden. Bitte den Video-Link statt einer Playlist verwenden.')
    return f'https://www.youtube.com/watch?v={video_id}'


def clean_text(value: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(value)).strip()


def parse_json3(data: str) -> list[Cue]:
    """Keep the full native timed-text stream; no duration or token limit."""
    events = json.loads(data).get('events', [])
    cues = []
    for index, event in enumerate(events):
        text = clean_text(''.join(segment.get('utf8', '') for segment in event.get('segs', [])))
        if not text or 'tStartMs' not in event:
            continue
        start = max(0, float(event['tStartMs']) / 1000)
        duration = event.get('dDurationMs')
        if duration is None:
            following = next((item['tStartMs'] for item in events[index + 1:]
                              if item.get('tStartMs', 0) > event['tStartMs']), None)
            end = float(following) / 1000 if following is not None else start + 3
        else:
            end = start + max(0.001, float(duration) / 1000)
        cues.append(Cue(start, end, text))
    return normalize_cues(cues)


def parse_timestamp(value: str) -> float:
    parts = value.replace(',', '.').split(':')
    if len(parts) == 2:
        parts.insert(0, '0')
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def parse_vtt(data: str) -> list[Cue]:
    cues = []
    timing = re.compile(r'(?P<start>(?:\d+:)?\d{2}:\d{2}[.,]\d+)\s+-->\s+'
                        r'(?P<end>(?:\d+:)?\d{2}:\d{2}[.,]\d+)')
    for block in re.split(r'\n\s*\n', data.replace('\r\n', '\n').lstrip('\ufeff')):
        lines = block.splitlines()
        if not lines or lines[0].startswith(('NOTE', 'STYLE', 'REGION')):
            continue
        for index, line in enumerate(lines):
            match = timing.match(line)
            if match:
                text = clean_text(re.sub(r'<[^>]+>', '', ' '.join(lines[index + 1:])))
                if text:
                    cues.append(Cue(parse_timestamp(match['start']), parse_timestamp(match['end']), text))
                break
    return normalize_cues(cues)


def normalize_cues(cues: list[Cue]) -> list[Cue]:
    """Remove rolling display repetitions only when their time spans overlap."""
    output = []
    previous = None
    for cue in sorted(cues, key=lambda item: (item.start, item.end)):
        if not all(math.isfinite(number) for number in (cue.start, cue.end)):
            continue
        text = clean_text(cue.text)
        if not text or cue.end <= cue.start:
            continue
        if previous is not None and cue.start < previous.end:
            old_words, new_words = previous.text.split(), text.split()
            for count in range(min(len(old_words), len(new_words)), 0, -1):
                if old_words[-count:] == new_words[:count]:
                    text = ' '.join(new_words[count:])
                    if not text and output:
                        output[-1].end = max(output[-1].end, cue.end)
                    break
        # Compare the next rolling frame with the full previous frame, not the delta.
        previous = Cue(cue.start, cue.end, clean_text(cue.text))
        if text:
            if output and output[-1].end > cue.start:
                output[-1].end = max(output[-1].start + 0.001, cue.start)
            output.append(Cue(max(0, cue.start), max(cue.start + 0.001, cue.end), text))
    return output


def timestamp(seconds: float, *, vtt: bool = False) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    separator = '.' if vtt else ','
    return f'{hours:02}:{minutes:02}:{whole_seconds:02}{separator}{milliseconds:03}'


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def write_exports(directory: Path, cues: list[Cue], metadata: dict, *, partial: bool = False) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    suffix = '.partial' if partial else ''
    srt = ''.join(f'{index}\n{timestamp(cue.start)} --> {timestamp(cue.end)}\n'
                  f'{textwrap.fill(cue.text, width=84, break_long_words=False, break_on_hyphens=False)}\n\n'
                  for index, cue in enumerate(cues, 1))
    vtt = 'WEBVTT\n\n' + ''.join(
        f'{timestamp(cue.start, vtt=True)} --> {timestamp(cue.end, vtt=True)}\n'
        f'{html.escape(cue.text, quote=False)}\n\n' for cue in cues)
    # Paragraphs make multi-hour transcripts readable without discarding words.
    paragraphs, current, start = [], [], 0.0
    for cue in cues:
        if current and cue.start - start >= 60:
            paragraphs.append(' '.join(current))
            current = []
        if not current:
            start = cue.start
        current.append(cue.text)
    if current:
        paragraphs.append(' '.join(current))
    documents = {
        f'untertitel{suffix}.srt': srt,
        f'untertitel{suffix}.vtt': vtt,
        f'transkript{suffix}.txt': '\n\n'.join(paragraphs) + '\n',
        f'transkript_zeitstempel{suffix}.txt': ''.join(
            f'[{timestamp(cue.start).split(",")[0]}] {cue.text}\n' for cue in cues),
        f'info{suffix}.json': json.dumps({**metadata, 'status': 'partial' if partial else 'complete',
                                        'cue_count': len(cues), 'tool_version': TOOL_VERSION},
                                       ensure_ascii=False, indent=2) + '\n',
    }
    paths = []
    for name, content in documents.items():
        path = directory / name
        atomic_text(path, content)
        paths.append(path)
    return paths


def make_result(directory: Path, cues: list[Cue], metadata: dict, raw: Path | None = None) -> Result:
    if not cues:
        raise SubtitleError('Keine Sprache erkannt. Es wurde kein leeres Transkript als Erfolg ausgegeben.')
    files = write_exports(directory, cues, metadata)
    if raw is not None:
        files.append(raw)
    archive = directory / 'untertitel.zip'
    temporary = archive.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in files:
            zipped.write(path, arcname=path.name)
    temporary.replace(archive)
    return Result(metadata['title'], metadata['source'], metadata.get('language', 'unknown'), directory, files, archive)


def caption_track(info: dict) -> tuple[str, str, list[dict]] | None:
    """Prefer human captions in the original language, then original auto captions."""
    manual = {key: value for key, value in (info.get('subtitles') or {}).items()
              if key != 'live_chat' and value}
    automatic = {key: value for key, value in (info.get('automatic_captions') or {}).items()
                 if key != 'live_chat' and value and any(
                     'tlang' not in parse_qs(urlparse(track.get('url', '')).query) for track in value)}
    originals = [key.removesuffix('-orig') for key in automatic if key.endswith('-orig')]
    language = info.get('language') or (originals[0] if originals else None)
    if language:
        for collection, source in ((manual, 'YouTube-Untertitel'), (automatic, 'YouTube-Autountertitel')):
            matches = [key for key in collection
                       if key.removesuffix('-orig').split('-')[0] == language.split('-')[0]]
            matches.sort(key=lambda key: (key != language, not key.endswith('-orig'), key))
            if matches:
                key = matches[0]
                return source, key.removesuffix('-orig'), collection[key]
    if automatic:
        key = sorted(automatic, key=lambda item: (not item.endswith('-orig'), item))[0]
        return 'YouTube-Autountertitel', key.removesuffix('-orig'), automatic[key]
    if manual:
        key = sorted(manual, key=lambda item: (item not in ('en', 'de'), item))[0]
        return 'YouTube-Untertitel (Originalsprache nicht ermittelbar)', key, manual[key]
    return None


def error_detail(error: Exception) -> str:
    """Keep the error type/reason, but never put signed URLs or tokens in reports."""
    text = getattr(error, 'details', '') or f'{type(error).__name__}: {error}'
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    text = re.sub(r'https?://[^\s<>"\']+',
                  lambda match: urlparse(match[0])._replace(query='', fragment='', netloc=urlparse(match[0]).hostname or '').geturl(), text)
    text = re.sub(r'(?i)\b(cookie|authorization|po_token|pot|token|api_key)\s*[:=]\s*[^\s,;]+', r'\1=[entfernt]', text)
    return text[:1600]


def youtube_error(error: Exception) -> SubtitleError:
    if isinstance(error, SubtitleError):
        return error
    detail = error_detail(error)
    lowered = detail.lower()
    if any(marker in lowered for marker in ('http error 429', '429 client error', 'rate-limit', 'too many requests')):
        message = 'YouTube meldet für diesen Abruf eine Anfragegrenze (429/Rate-Limit). Bitte später erneut versuchen.'
    elif any(marker in lowered for marker in ('requestblocked', 'ipblocked', 'not a bot', 'sign in', 'sign-in', 'captcha')):
        message = ('YouTube verlangt bei diesem Abruf eine Anmeldung oder Botbestätigung. '
                   'Das sagt nichts darüber aus, ob Untertitel vorhanden sind. Ein anderes Tool kann einen anderen Abrufweg verwenden.')
    elif any(marker in lowered for marker in ('http error 403', '403 client error', '403 forbidden')):
        message = 'YouTube lehnt diesen Abruf mit HTTP 403 ab. Die genaue Ursache steht unter „Technische Details“.'
    elif 'po token' in lowered or 'po_token' in lowered:
        message = 'Für diesen Abrufweg fehlt ein von YouTube verlangter PO-Token. Details stehen unten.'
    elif 'ssl' in lowered or 'certificate_verify_failed' in lowered:
        message = 'Die sichere Verbindung zu YouTube ist fehlgeschlagen (TLS/Zertifikat). Das ist kein Nachweis fehlender Untertitel.'
    elif any(marker in lowered for marker in ('transcriptsdisabled', 'notranscriptfound')):
        message = 'Über diesen Abrufweg wurden keine verfügbaren Untertitel gemeldet.'
    elif any(marker in lowered for marker in ('age-restrict', 'agerestricted', 'private', 'unavailable', 'not available', 'removed')):
        message = 'YouTube meldet das Video für diesen Abruf als eingeschränkt oder nicht verfügbar. Die genaue Meldung steht unten.'
    else:
        message = f'Abruf fehlgeschlagen: {detail[:500]}'
    return SubtitleError(message, details=detail)


def combined_error(attempts: list[tuple[str, Exception]]) -> SubtitleError:
    last_error = youtube_error(attempts[-1][1])
    return SubtitleError(str(last_error), details='\n\n'.join(
        f'{name}:\n{error_detail(error)}' for name, error in attempts))


def player_metadata(payload: dict) -> dict:
    """Read metadata from the transcript client's existing player response."""
    details = payload.get('videoDetails') or {}
    microformat = (payload.get('microformat') or {}).get('playerMicroformatRenderer') or {}
    broadcast = microformat.get('liveBroadcastDetails') or {}
    ended = False
    try:
        ended = datetime.fromisoformat(broadcast['endTimestamp'].replace('Z', '+00:00')).timestamp() <= time.time()
    except (KeyError, TypeError, ValueError):
        pass
    live = details.get('isLive', broadcast.get('isLiveNow', False))
    status = ('post_live' if details.get('isPostLiveDvr') else 'was_live' if ended
              else 'is_live' if live else 'is_upcoming' if details.get('isUpcoming')
              else 'was_live' if details.get('isLiveContent') else 'not_live')
    try:
        duration = float(details.get('lengthSeconds') or microformat.get('lengthSeconds') or 0) or None
    except (TypeError, ValueError):
        duration = None
    return {'title': details.get('title'), 'duration_seconds': duration,
            'language': details.get('defaultAudioLanguage'), 'live_status': status}


def fetch_direct_transcript(canonical: str, root: Path, *, stream_ended=False, progress=print) -> Result:
    """Try the maintained transcript client before extracting any media formats."""
    from requests import Session
    from youtube_transcript_api import YouTubeTranscriptApi

    video_id = parse_qs(urlparse(canonical).query)['v'][0]

    class TranscriptSession(Session):
        def __init__(self):
            super().__init__()
            self.video_info = {}

        def request(self, *args, **kwargs):
            kwargs.setdefault('timeout', (10, 30))
            response = super().request(*args, **kwargs)
            if response.status_code == 200 and urlparse(response.url).path == '/youtubei/v1/player':
                self.video_info = player_metadata(response.json())
            return response

    with TranscriptSession() as session:
        transcripts = list(YouTubeTranscriptApi(http_client=session).list(video_id))
        info = session.video_info
        if info.get('live_status') in ('is_live', 'is_upcoming') and not stream_ended:
            raise SubtitleError('YouTube meldet dieses Video noch als live. '
                                'Falls es bereits beendet ist, „Stream_bereits_beendet“ anhaken.')
        if not transcripts:
            raise SubtitleError('Der direkte Abruf hat keine Untertitelspur geliefert.')
        generated = [track for track in transcripts if track.is_generated]
        language = info.get('language') or (generated[0].language_code if len(generated) == 1 else None)
        same_language = [track for track in transcripts if track.language_code == language]
        if language and not same_language:
            same_language = [track for track in transcripts if track.language_code.split('-')[0] == language.split('-')[0]]
        selected = next((track for track in same_language if not track.is_generated), None)
        selected = selected or next(iter(same_language), None) or transcripts[0]
        source = 'YouTube-Autountertitel' if selected.is_generated else 'YouTube-Untertitel'
        if not same_language:
            source += ' (Originalsprache nicht ermittelbar)'
        progress(f'Lade {source}, Sprache: {selected.language_code}. Dafür wird keine GPU benötigt.')
        fetched = selected.fetch()
        raw_data = fetched.to_raw_data()
    cues = normalize_cues([Cue(float(item['start']), float(item['start']) + float(item['duration']), item['text'])
                           for item in raw_data])
    if not cues:
        raise SubtitleError('Der direkte Abruf hat eine leere Untertitelspur geliefert.')
    directory = root / 'youtube'
    raw_path = directory / 'original.transcript-api.json'
    atomic_text(raw_path, json.dumps(raw_data, ensure_ascii=False, indent=2))
    metadata = {**info, 'title': info.get('title') or video_id, 'url': canonical, 'video_id': video_id,
                'source': source, 'language': selected.language_code, 'backend': 'youtube-transcript-api',
                'stream_ended_confirmed': stream_ended, 'reported_live_status': info.get('live_status')}
    return make_result(directory, cues, metadata, raw_path)


def is_ended_recording(info: dict) -> bool:
    """An explicit ended status outranks an inconsistent legacy is_live flag."""
    return info.get('live_status') in ('post_live', 'was_live') or info.get('was_live') is True


def recording_audio_format(context: dict):
    """Only choose finite files while a recently ended stream is processing.

    A rolling live manifest can contain only the last part of a long recording.
    Never silently label that tail as the full transcript or keep recording live.
    """
    candidates = [item for item in context.get('formats', [])
                  if item.get('protocol') in ('http', 'https')
                  and isinstance(item.get('filesize'), (int, float)) and item['filesize'] > 0
                  and item.get('acodec') not in (None, 'none')
                  and not item.get('target_duration') and not item.get('is_from_start')
                  and 'incomplete' not in str(item.get('format_note', '')).lower()
                  and 'last 2 hours' not in str(item.get('format_note', '')).lower()]
    audio_only = [item for item in candidates if item.get('vcodec') == 'none']
    available = audio_only or candidates
    if not available:
        raise SubtitleError(
            'Der Stream ist beendet bzw. als beendet bestätigt. YouTube liefert hier aber noch keine '
            'vollständige Tonspur als fertige Datei. Die Aufzeichnung kann noch verarbeitet werden. '
            'Bitte später erneut starten; es wird nicht nur das letzte Stück des Streams transkribiert.')
    yield available[-1]


class QuietLogger:
    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        # yt-dlp exceptions are handled below; do not overwhelm a phone with logs.
        pass

    def error(self, message):
        pass


def youtube_downloader(options: dict):
    """Use the pinned extractor without irrelevant storyboard processing.

    Its storyboard implementation divides a missing duration by a float. The
    subtitle workflow does not consume thumbnail/storyboard formats at all.
    Keep the change local to this downloader instance, including after reruns.
    """
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.youtube import YoutubeIE
    from yt_dlp.utils import parse_iso8601

    class SubtitleYoutubeIE(YoutubeIE):
        @classmethod
        def ie_key(cls):
            return YoutubeIE.ie_key()

        def _extract_storyboard(self, player_responses, duration):
            return iter(())

        def _list_formats(self, video_id, microformats, video_details, player_responses, player_url, duration=None):
            # A finished broadcast can still carry isLive=True in another client
            # response. Its recorded end time is stronger evidence of an ending.
            ended = any(
                isinstance(item, dict)
                and (end := parse_iso8601((item.get('liveBroadcastDetails') or {}).get('endTimestamp'))) is not None
                and end <= time.time()
                for item in (microformats or []))
            if ended:
                video_details = copy.deepcopy(video_details or [{}])
                for item in video_details:
                    item.update(isLive=False, isUpcoming=False, isLiveContent=True)
                microformats = copy.deepcopy(microformats)
                for item in microformats:
                    if isinstance(item.get('liveBroadcastDetails'), dict):
                        item['liveBroadcastDetails']['isLiveNow'] = False
                # Preserve isPostLiveDvr: yt-dlp needs its distinction between a
                # processed recording and a recording still being processed.
            return super()._list_formats(video_id, microformats, video_details,
                                         player_responses, player_url, duration)

        def raise_no_formats(self, msg, expected=False, video_id=None):
            # Video playback can fail while a caption track is still returned.
            # Keep the player failure for a report if no captions can be fetched,
            # but let upstream finish its metadata/subtitle extraction first.
            markers = ('sign in', 'sign-in', 'log in', 'login', 'not a bot', 'captcha',
                       'age-restrict', 'private', 'unavailable', 'not available',
                       'removed', 'rate-limit', 'too many requests', '403', '429', 'po token')
            if expected and self.get_param('ignore_no_formats_error') and any(marker in str(msg).lower() for marker in markers):
                self._downloader.subtitle_playback_errors.append(str(msg))
            return super().raise_no_formats(msg, expected=expected, video_id=video_id)

    ydl = YoutubeDL(options)
    ydl.subtitle_playback_errors = []
    ydl.add_info_extractor(SubtitleYoutubeIE(ydl))
    return ydl


def ydl_options(*, metadata_only=False) -> dict:
    runtime = {}
    if not shutil.which('deno'):
        try:
            from deno import find_deno_bin
            runtime['path'] = str(find_deno_bin())
        except (ImportError, RuntimeError):
            pass
    return {
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'logger': QuietLogger(),
        'socket_timeout': 30,
        'retries': 3,
        'fragment_retries': 3,
        'extractor_retries': 2,
        'extractor_args': {'youtube': {'skip': ['translated_subs', *(['hls', 'dash'] if metadata_only else [])]}},
        'js_runtimes': {'deno': runtime},
    }


def fetch_caption(ydl, tracks: list[dict]) -> tuple[list[Cue], str, str]:
    supported = [track for track in tracks if track.get('ext') in ('json3', 'vtt')]
    supported.sort(key=lambda track: track.get('ext') != 'json3')
    if not supported:
        raise SubtitleError('Die Untertitelspur hat kein unterstütztes JSON3- oder VTT-Format.')
    from yt_dlp.networking import Request

    last_error = None
    # Try one URL of each format; avoid hammering duplicate client URLs.
    formats_seen = set()
    for track in supported:
        extension = track['ext']
        if extension in formats_seen:
            continue
        formats_seen.add(extension)
        try:
            raw = track.get('data')
            if raw is None:
                with ydl.urlopen(Request(track['url'], headers=track.get('http_headers', {}))) as response:
                    raw = response.read().decode('utf-8-sig')
            cues = parse_json3(raw) if extension == 'json3' else parse_vtt(raw)
            if cues:
                return cues, raw, extension
            last_error = SubtitleError('YouTube hat eine leere Untertitelspur zurückgegeben.')
        except Exception as error:
            last_error = error
            if any(code in str(error) for code in ('429', '403')):
                break
    raise youtube_error(last_error or SubtitleError('Untertitel konnten nicht gelesen werden.'))


def audio_duration(path: Path) -> float:
    if not shutil.which('ffprobe'):
        raise SubtitleError('FFmpeg fehlt. Bitte FFmpeg installieren; in Colab geschieht dies automatisch.')
    command = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        duration = float(result.stdout.strip())
        if result.returncode or not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return duration
    except ValueError:
        raise SubtitleError('Die Audio-/Videodatei konnte nicht gelesen werden oder hat keine gültige Dauer.')


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def check_audio_decoder() -> None:
    """Check the actual Whisper/PyAV boundary before loading a large model."""
    from faster_whisper.audio import decode_audio

    sample = io.BytesIO()
    with wave.open(sample, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b'\x00\x00' * 800)
    sample.seek(0)
    try:
        decoded = decode_audio(sample, sampling_rate=16000)
        if len(decoded) != 800:
            raise ValueError('Der Audio-Decodertest hat eine unerwartete Länge geliefert.')
    except Exception as error:
        if 'metadata_errors' in str(error):
            message = ('Die installierten Versionen von faster-whisper und PyAV sind nicht kompatibel. '
                       'Bitte faster-whisper==1.2.1 und av==18.1.0 installieren; '
                       'die aktuelle Colab-Version erledigt das automatisch. Die Tonspur bleibt erhalten.')
        else:
            message = 'Der Audio-Decodertest ist fehlgeschlagen. Die Tonspur bleibt erhalten.'
        raise SubtitleError(message, details=error_detail(error)) from error


def transcribe_audio(audio: Path, root: Path, metadata: dict, *, model_name='auto', progress=print) -> Result:
    try:
        import ctranslate2
        from faster_whisper import WhisperModel
    except ImportError:
        raise SubtitleError('Spracherkennung fehlt. Bitte faster-whisper installieren oder die Colab-Startzelle nutzen.')

    duration = audio_duration(audio)
    try:
        has_gpu = ctranslate2.get_cuda_device_count() > 0
    except RuntimeError:
        has_gpu = False
    device, precision = ('cuda', 'float16') if has_gpu else ('cpu', 'int8')
    if model_name == 'auto':
        model_name = 'turbo' if has_gpu else 'small'
    if not has_gpu:
        progress('Spracherkennung läuft auf CPU. Bei langen Videos beschleunigt eine Colab-GPU diesen Schritt.')

    signature = {
        'tool_version': TOOL_VERSION, 'audio_sha256': file_digest(audio),
        'model': model_name, 'chunk_seconds': CHUNK_SECONDS, 'context_seconds': CONTEXT_SECONDS,
        'beam_size': 5, 'vad_filter': True, 'word_timestamps': True,
    }
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:16]
    directory = root / f'whisper-{key}'
    checkpoint = directory / 'fortschritt.json'
    state = {'signature': signature, 'next_chunk': 0, 'language': None, 'cues': []}
    if checkpoint.exists():
        try:
            saved = json.loads(checkpoint.read_text(encoding='utf-8'))
            if saved['signature'] != signature:
                raise ValueError('Signatur stimmt nicht überein')
            if not isinstance(saved['next_chunk'], int) or saved['next_chunk'] < 0:
                raise ValueError('Ungültiger Fortschritt')
            state = saved
        except (ValueError, KeyError, TypeError) as error:
            raise SubtitleError(f'Die Sicherung ist beschädigt: {checkpoint}. Bitte den Ordner umbenennen und neu starten.') from error
    count = math.ceil(duration / CHUNK_SECONDS)
    cues = [Cue(**item) for item in state['cues']]
    metadata = {**metadata, 'source': f'Whisper ({model_name})', 'duration_seconds': duration,
                'model': model_name, 'language': state['language'] or 'unknown'}
    if state['next_chunk'] >= count:
        progress('Vollständige Sicherung gefunden – kein erneutes Transkribieren nötig.')
        return make_result(directory, cues, metadata)

    check_audio_decoder()
    progress('Audio-Decodertest erfolgreich.')
    progress(f'Spracherkennung: {model_name} auf {device}; {count} Abschnitte à höchstens 10 Minuten.')
    progress(f'Zwischenstände: {directory}')
    if state['next_chunk']:
        progress(f'Setze nach {state["next_chunk"]} bereits gesicherten Abschnitten fort.')
    try:
        model = WhisperModel(model_name, device=device, compute_type=precision)
    except Exception as error:
        raise SubtitleError('Whisper konnte nicht geladen werden. Internetzugriff und freien Speicher prüfen; '
                            'bei CUDA-Fehlern die Colab-Laufzeit neu starten oder CPU wählen. '
                            f'Detail: {str(error)[:300]}') from error

    with tempfile.TemporaryDirectory(prefix='subtitle-chunk-') as scratch:
        chunk_file = Path(scratch) / 'chunk.wav'
        for index in range(state['next_chunk'], count):
            start = index * CHUNK_SECONDS
            stop = min(duration, start + CHUNK_SECONDS)
            context_start = max(0, start - CONTEXT_SECONDS)
            context_stop = min(duration, stop + CONTEXT_SECONDS)
            progress(f'Abschnitt {index + 1}/{count}: {timestamp(start)} – {timestamp(stop)}')
            subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                            '-ss', str(context_start), '-i', str(audio), '-t', str(context_stop - context_start),
                            '-vn', '-ac', '1', '-ar', '16000', str(chunk_file)], check=True)
            segments, detected = model.transcribe(
                str(chunk_file), beam_size=5, language=state['language'], task='transcribe',
                vad_filter=True, condition_on_previous_text=False, word_timestamps=True,
            )
            chunk_cues = []
            for segment in segments:
                # Context on both sides protects words at chunk boundaries. Keep
                # each word only in the interval containing its midpoint.
                words = [word for word in (segment.words or [])
                         if start <= context_start + (word.start + word.end) / 2 < stop]
                if words:
                    text = clean_text(''.join(word.word for word in words))
                    if text:
                        chunk_cues.append(Cue(max(start, context_start + words[0].start),
                                              min(stop, context_start + words[-1].end), text))
                elif not segment.words and start <= context_start + (segment.start + segment.end) / 2 < stop:
                    text = clean_text(segment.text)
                    if text:
                        chunk_cues.append(Cue(max(start, context_start + segment.start),
                                              min(stop, context_start + segment.end), text))
            cues.extend(cue for cue in chunk_cues if cue.end > cue.start)
            if chunk_cues and state['language'] is None:
                state['language'] = detected.language
            state.update(next_chunk=index + 1, cues=[asdict(cue) for cue in cues])
            atomic_text(checkpoint, json.dumps(state, ensure_ascii=False))
            metadata['language'] = state['language'] or 'unknown'
            write_exports(directory, cues, {**metadata, 'completed_chunks': index + 1,
                                           'total_chunks': count}, partial=True)
            progress(f'Gesichert: {index + 1}/{count}.')
    return make_result(directory, cues, metadata)


def run(url: str = '', *, output_dir: str | Path = 'youtube_subtitles',
        local_file: str | Path | None = None, mode: str = 'auto', model_name: str = 'auto',
        stream_ended: bool = False, progress=print, transcriber=None) -> Result:
    if mode not in ('auto', 'subtitles', 'whisper'):
        raise SubtitleError('Unbekannter Modus.')
    if model_name not in ('auto', 'small', 'medium', 'turbo', 'large-v3'):
        raise SubtitleError('Unbekanntes Whisper-Modell.')
    output_dir = Path(output_dir).expanduser().resolve()
    if local_file is not None:
        audio = Path(local_file).expanduser().resolve()
        if not audio.is_file():
            raise SubtitleError('Die hochgeladene Datei fehlt.')
        if mode == 'subtitles':
            raise SubtitleError('Für eine eigene Datei bitte „Automatisch“ oder „KI neu erzeugen“ wählen.')
        metadata = {'title': audio.stem, 'input': 'local_file', 'source': 'Whisper'}
        root = output_dir / f'lokal-{file_digest(audio)[:16]}'
    else:
        canonical = youtube_url(url)
        video_id = parse_qs(urlparse(canonical).query)['v'][0]
        root = output_dir / video_id
        attempts = []
        if mode != 'whisper':
            progress('Prüfe Untertitel direkt …')
            try:
                return fetch_direct_transcript(canonical, root, stream_ended=stream_ended, progress=progress)
            except Exception as error:
                attempts.append(('Direkter Untertitelabruf', error))
                progress(f'Direkter Abruf ohne Ergebnis ({type(error).__name__}). Prüfe zusätzlich mit yt-dlp …')
        else:
            progress('Prüfe Video für Spracherkennung …')
        try:
            with youtube_downloader({**ydl_options(metadata_only=True), 'skip_download': True, 'ignore_no_formats_error': True}) as ydl:
                info = ydl.extract_info(canonical, download=False)
                if not info or info.get('_type') in ('playlist', 'multi_video'):
                    raise SubtitleError('Kein einzelnes Video gefunden.')
                ended = is_ended_recording(info)
                reports_live = info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming')
                if reports_live and not ended and not stream_ended:
                    raise SubtitleError(
                        'YouTube meldet dieses Video noch als live oder angekündigt. '
                        'Falls der Stream bereits beendet ist: „Stream_bereits_beendet“ anhaken und erneut starten. '
                        'Der /live/-Link ist auch für Aufzeichnungen gültig.')
                cautious_recording = info.get('live_status') == 'post_live' or bool(reports_live and (ended or stream_ended))
                metadata = {'title': info.get('title') or video_id, 'url': canonical,
                            'video_id': video_id, 'duration_seconds': info.get('duration'),
                            'reported_live_status': info.get('live_status'), 'stream_ended_confirmed': stream_ended}
                progress(metadata['title'])
                if cautious_recording:
                    progress('Beendete Aufzeichnung: prüfe Untertitel und bereits fertig bereitgestellte Audiodateien.')
                track = caption_track(info)
                if mode != 'whisper' and track:
                    source, language, formats = track
                    progress(f'Lade {source}, Sprache: {language}. Dafür wird keine GPU benötigt.')
                    try:
                        cues, raw, extension = fetch_caption(ydl, formats)
                    except Exception as error:
                        attempts.append(('yt-dlp: Untertiteldatei', error))
                        progress('Die Untertiteldatei konnte nicht geladen werden.')
                    else:
                        directory = root / 'youtube'
                        raw_path = directory / f'original.{extension}'
                        atomic_text(raw_path, raw)
                        return make_result(directory, cues, {**metadata, 'source': source, 'language': language,
                                                            'backend': 'yt-dlp'}, raw_path)
                playback_errors = getattr(ydl, 'subtitle_playback_errors', [])
                if playback_errors:
                    raise RuntimeError('\n'.join(playback_errors))
        except Exception as error:
            attempts.append(('yt-dlp: Videometadaten', error))
            raise combined_error(attempts) from error
        if mode == 'subtitles':
            if track:
                raise combined_error(attempts)
            if ended or stream_ended:
                message = ('Für diese Aufzeichnung hat keiner der Abrufwege Untertitel geliefert. '
                           'Sie können noch verarbeitet werden oder hier nicht abrufbar sein. '
                           '„Automatisch“ versucht zusätzlich die Tonspur.')
            else:
                message = 'Keiner der Abrufwege hat vorhandene Untertitel geliefert. Für Spracherkennung „Automatisch“ wählen.'
            raise SubtitleError(message, details=combined_error(attempts).details if attempts else '')
        progress('Lade nur die Tonspur für die Spracherkennung …')
        cache = output_dir / '_audio' / video_id
        cache.mkdir(parents=True, exist_ok=True)
        try:
            require_finite_audio = cautious_recording or stream_ended

            def avoid_live_recording(latest_info, *, incomplete=False):
                nonlocal require_finite_audio
                latest_live = latest_info.get('is_live') or latest_info.get('live_status') in ('is_live', 'is_upcoming')
                if latest_live and not is_ended_recording(latest_info) and not stream_ended:
                    raise SubtitleError('YouTube meldet beim Audioabruf erneut einen Live-Status. '
                                        'Bei einer beendeten Sendung „Stream_bereits_beendet“ aktivieren.')
                if latest_info.get('live_status') == 'post_live' or latest_live:
                    require_finite_audio = True

            def select_audio(context):
                if require_finite_audio:
                    yield from recording_audio_format(context)
                else:
                    yield from ydl.build_format_selector('bestaudio/best')(context)

            with youtube_downloader({**ydl_options(),
                                     'format': select_audio,
                                     'match_filter': avoid_live_recording,
                                     'skip_unavailable_fragments': False,
                                     'outtmpl': str(cache / 'audio.%(ext)s')}) as ydl:
                audio_info = ydl.extract_info(canonical, download=True)
                audio = Path(ydl.prepare_filename(audio_info))
                if not audio.is_file():
                    raise SubtitleError('Die Tonspur wurde nicht vollständig heruntergeladen.')
                expected_duration = audio_info.get('duration') or metadata.get('duration_seconds')
                if (ended or stream_ended or is_ended_recording(audio_info)) and isinstance(expected_duration, (int, float)) and expected_duration > 0:
                    actual_duration = audio_duration(audio)
                    if actual_duration < expected_duration - max(30, expected_duration * 0.02):
                        # Do not keep reusing a cached tail after YouTube finishes
                        # processing. Keep it separately for inspection instead.
                        audio.replace(audio.with_name(f'audio.incomplete{audio.suffix}'))
                        raise SubtitleError('Die geladene Tonspur ist deutlich kürzer als die Aufzeichnung. '
                                            'YouTube hat möglicherweise noch nicht alles bereitgestellt. '
                                            'Bitte später erneut starten; kein vollständiges Transkript erzeugt.')
        except Exception as error:
            attempts.append(('yt-dlp: Tonspur', error))
            raise combined_error(attempts) from error
    return (transcriber or transcribe_audio)(audio, root, metadata, model_name=model_name, progress=progress)


def main():
    parser = argparse.ArgumentParser(description='YouTube-Link → SRT, VTT und vollständiges TXT-Transkript')
    parser.add_argument('url', nargs='?', default='')
    parser.add_argument('--file', dest='local_file', help='Eigene Audio-/Videodatei statt YouTube')
    parser.add_argument('--output', default='youtube_subtitles')
    parser.add_argument('--mode', choices=('auto', 'subtitles', 'whisper'), default='auto')
    parser.add_argument('--model', choices=('auto', 'small', 'medium', 'turbo', 'large-v3'), default='auto')
    parser.add_argument('--stream-ended', action='store_true', help='Bestätigt: Der Livestream ist bereits beendet')
    args = parser.parse_args()
    try:
        result = run(args.url, local_file=args.local_file, output_dir=args.output,
                     mode=args.mode, model_name=args.model, stream_ended=args.stream_ended)
        print(f'Fertig: {result.archive}')
    except SubtitleError as error:
        parser.exit(1, f'{error}\n' + (f'\nTechnische Details:\n{error.details}\n' if error.details else ''))
    except KeyboardInterrupt:
        parser.exit(130, 'Gestoppt. Bereits gesicherte Abschnitte bleiben erhalten.\n')


if __name__ == '__main__':
    main()
