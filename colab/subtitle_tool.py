"""One-link subtitles for Erikiss/yt-dlp; also embedded in the Colab notebook.

No server, account cookies or API keys. Only standard-library imports until
yt-dlp / optional faster-whisper are actually needed.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import tempfile
import textwrap
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse


TOOL_VERSION = 1
CHUNK_SECONDS = 600
CONTEXT_SECONDS = 3


class SubtitleError(RuntimeError):
    """An actionable, user-facing failure."""


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


def youtube_error(error: Exception) -> SubtitleError:
    message = str(error)
    lowered = message.lower()
    if any(marker in lowered for marker in ('429', '403', 'bot', 'sign in', 'login', 'po token', 'age-restrict')):
        return SubtitleError(
            'YouTube lässt den Abruf aus dieser Umgebung nicht zu (Anmeldung, Zugriffsschutz oder Anfragegrenze). '
            'Das ist kein fehlender Untertitel. Später erneut versuchen oder eine eigene Audio-/Videodatei '
            'über „Datei hochladen“ transkribieren. Es werden keine Zugangssperren umgangen.')
    if any(marker in lowered for marker in ('private', 'unavailable', 'not available', 'removed')):
        return SubtitleError('Das Video ist privat, gelöscht oder hier nicht verfügbar. Bitte den Link prüfen.')
    return SubtitleError(f'Abruf fehlgeschlagen: {message[:600]}')


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


def ydl_options() -> dict:
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
        'extractor_args': {'youtube': {'skip': ['translated_subs']}},
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
        progress=print, transcriber=None) -> Result:
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
        from yt_dlp import YoutubeDL

        progress('Prüfe Video und verfügbare Untertitel …')
        try:
            with YoutubeDL({**ydl_options(), 'skip_download': True, 'ignore_no_formats_error': True}) as ydl:
                info = ydl.extract_info(canonical, download=False)
                if not info or info.get('_type') in ('playlist', 'multi_video'):
                    raise SubtitleError('Kein einzelnes Video gefunden.')
                if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming'):
                    raise SubtitleError('Laufende oder angekündigte Livestreams sind nicht unterstützt. '
                                        'Bitte nach dem Ende die Videoaufzeichnung verwenden.')
                video_id = parse_qs(urlparse(canonical).query)['v'][0]
                root = output_dir / video_id
                metadata = {'title': info.get('title') or video_id, 'url': canonical,
                            'video_id': video_id, 'duration_seconds': info.get('duration')}
                progress(metadata['title'])
                track = caption_track(info)
                if mode != 'whisper' and track:
                    source, language, formats = track
                    progress(f'Lade {source}, Sprache: {language}. Dafür wird keine GPU benötigt.')
                    cues, raw, extension = fetch_caption(ydl, formats)
                    directory = root / 'youtube'
                    raw_path = directory / f'original.{extension}'
                    atomic_text(raw_path, raw)
                    return make_result(directory, cues, {**metadata, 'source': source, 'language': language}, raw_path)
        except SubtitleError:
            raise
        except Exception as error:
            raise youtube_error(error) from error
        if mode == 'subtitles':
            raise SubtitleError('Keine vorhandenen Untertitel gefunden. Für Spracherkennung „Automatisch“ wählen.')
        progress('Lade nur die Tonspur für die Spracherkennung …')
        cache = output_dir / '_audio' / video_id
        cache.mkdir(parents=True, exist_ok=True)
        try:
            with YoutubeDL({**ydl_options(), 'format': 'bestaudio/best',
                            'outtmpl': str(cache / 'audio.%(ext)s')}) as ydl:
                audio_info = ydl.extract_info(canonical, download=True)
                audio = Path(ydl.prepare_filename(audio_info))
                if not audio.is_file():
                    raise SubtitleError('Die Tonspur wurde nicht vollständig heruntergeladen.')
        except SubtitleError:
            raise
        except Exception as error:
            raise youtube_error(error) from error
    return (transcriber or transcribe_audio)(audio, root, metadata, model_name=model_name, progress=progress)


def main():
    parser = argparse.ArgumentParser(description='YouTube-Link → SRT, VTT und vollständiges TXT-Transkript')
    parser.add_argument('url', nargs='?', default='')
    parser.add_argument('--file', dest='local_file', help='Eigene Audio-/Videodatei statt YouTube')
    parser.add_argument('--output', default='youtube_subtitles')
    parser.add_argument('--mode', choices=('auto', 'subtitles', 'whisper'), default='auto')
    parser.add_argument('--model', choices=('auto', 'small', 'medium', 'turbo', 'large-v3'), default='auto')
    args = parser.parse_args()
    try:
        result = run(args.url, local_file=args.local_file, output_dir=args.output,
                     mode=args.mode, model_name=args.model)
        print(f'Fertig: {result.archive}')
    except SubtitleError as error:
        parser.exit(1, f'{error}\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Gestoppt. Bereits gesicherte Abschnitte bleiben erhalten.\n')


if __name__ == '__main__':
    main()
