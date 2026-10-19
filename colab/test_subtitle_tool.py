"""Offline regression checks for complete transcripts and restart safety."""

import copy
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import subtitle_tool as app


class TestInputAndCaptions(unittest.TestCase):
    def test_mobile_short_live_and_playlist_links(self):
        expected = 'https://www.youtube.com/watch?v=QRS8MkLhQmM'
        for url in ['https://youtu.be/QRS8MkLhQmM?si=tracking',
                    'https://m.youtube.com/watch?v=QRS8MkLhQmM&list=ignored',
                    'https://youtube.com/shorts/QRS8MkLhQmM',
                    'https://youtube.com/live/QRS8MkLhQmM', 'QRS8MkLhQmM']:
            self.assertEqual(app.youtube_url(url), expected)

    def test_wrong_hosts_playlists_and_shell_fragments_rejected(self):
        for url in ['', 'https://youtube.com.evil.example/watch?v=QRS8MkLhQmM',
                    'https://youtube.com/playlist?list=test', 'file:///etc/passwd',
                    'https://youtube.com@evil.example/watch?v=QRS8MkLhQmM', '$(echo nope)']:
            with self.subTest(url=url), self.assertRaises(app.SubtitleError):
                app.youtube_url(url)

    def test_original_auto_beats_manual_translation(self):
        original = [{'ext': 'json3', 'url': 'https://example.test/?lang=en'}]
        german = [{'ext': 'json3', 'url': 'https://example.test/?lang=de'}]
        info = {'language': 'en', 'subtitles': {'de': german}, 'automatic_captions': {'en-orig': original}}
        source, language, tracks = app.caption_track(info)
        self.assertEqual((source, language, tracks), ('YouTube-Autountertitel', 'en', original))
        info['subtitles']['en'] = original
        self.assertEqual(app.caption_track(info)[0], 'YouTube-Untertitel')

    def test_translated_autocaptions_and_chat_are_excluded(self):
        self.assertIsNone(app.caption_track({'automatic_captions': {
            'de': [{'url': 'https://example.test/?lang=en&tlang=de'}]},
            'subtitles': {'live_chat': [{'ext': 'json'}]}}))

    def test_rolling_repetitions_removed_but_spoken_repetitions_kept(self):
        cues = app.normalize_cues([app.Cue(0, 4, 'hello world'), app.Cue(2, 6, 'hello world again'),
                                  app.Cue(7, 8, 'again'), app.Cue(8, 9, 'again')])
        self.assertEqual([cue.text for cue in cues], ['hello world', 'again', 'again', 'again'])

    def test_json3_preserves_unicode_entities_and_long_video_end(self):
        raw = json.dumps({'events': [
            {'tStartMs': 0, 'dDurationMs': 3000, 'segs': [{'utf8': 'Grüße &amp; α'}]},
            {'tStartMs': 25 * 3600 * 1000, 'dDurationMs': 1200, 'segs': [{'utf8': 'letztes Wort'}]},
        ]})
        cues = app.parse_json3(raw)
        self.assertEqual([cue.text for cue in cues], ['Grüße & α', 'letztes Wort'])
        self.assertEqual(app.timestamp(cues[-1].start), '25:00:00,000')
        self.assertEqual(app.timestamp(59.9996), '00:01:00,000')

    def test_vtt_handles_tags_timing_settings_and_notes(self):
        raw = ('WEBVTT\r\n\r\nNOTE ignore\r\n\r\n1\r\n00:00:01.000 --> 00:00:03.500 align:start\r\n'
               '<c>Ein</c> <00:00:02.000>Test &amp; mehr\r\n\r\n')
        self.assertEqual(app.parse_vtt(raw), [app.Cue(1, 3.5, 'Ein Test & mehr')])

    def test_large_transcript_has_no_token_or_duration_cap(self):
        cues = [app.Cue(index * 2, index * 2 + 1, f'Text{index}') for index in range(20000)]
        with tempfile.TemporaryDirectory() as temporary:
            result = app.make_result(Path(temporary), cues, {'title': 'Long', 'source': 'Test', 'language': 'de'})
            text = (result.directory / 'transkript.txt').read_text()
            self.assertIn('Text19999', text)
            self.assertEqual(len(text.split()), 20000)
            with zipfile.ZipFile(result.archive) as zipped:
                self.assertEqual(len(zipped.namelist()), 5)
                self.assertEqual(zipped.testzip(), None)
            self.assertEqual(json.loads((result.directory / 'info.json').read_text())['status'], 'complete')

    def test_empty_output_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(app.SubtitleError):
            app.make_result(Path(temporary), [], {'title': 'Empty', 'source': 'Test'})


class FakeYDL:
    info = {}
    failure = None

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, *args, **kwargs):
        if self.failure:
            raise self.failure
        return self.info


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        FakeYDL.failure = None
        FakeYDL.info = {'id': 'QRS8MkLhQmM', 'title': 'Fixture', 'language': 'en', 'duration': 50000}

    def test_captions_workflow_does_not_load_whisper(self):
        raw = json.dumps({'events': [{'tStartMs': 45000000, 'dDurationMs': 2000, 'segs': [{'utf8': 'The end.'}]}]})
        FakeYDL.info['subtitles'] = {'en': [{'ext': 'json3', 'data': raw}]}
        with tempfile.TemporaryDirectory() as temporary, patch.object(app, 'youtube_downloader', FakeYDL):
            result = app.run('QRS8MkLhQmM', output_dir=temporary, progress=lambda _: None,
                             transcriber=lambda *args, **kwargs: self.fail('Unexpected Whisper'))
            self.assertEqual((result.directory / 'original.json3').read_text(), raw)
            self.assertIn('12:30:00,000', (result.directory / 'untertitel.srt').read_text())

    def test_absent_captions_in_captions_only_mode_is_clear(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(app, 'youtube_downloader', FakeYDL):
            with self.assertRaisesRegex(app.SubtitleError, 'Keine vorhandenen'):
                app.run('QRS8MkLhQmM', mode='subtitles', output_dir=temporary, progress=lambda _: None)

    def test_blocked_cloud_is_not_misreported_as_no_captions(self):
        FakeYDL.failure = RuntimeError('HTTP Error 429: Too Many Requests')
        with tempfile.TemporaryDirectory() as temporary, patch.object(app, 'youtube_downloader', FakeYDL):
            with self.assertRaisesRegex(app.SubtitleError, 'kein fehlender Untertitel'):
                app.run('QRS8MkLhQmM', output_dir=temporary, progress=lambda _: None,
                        transcriber=lambda *args, **kwargs: self.fail('Unexpected Whisper'))

    def test_live_stream_rejected(self):
        FakeYDL.info['is_live'] = True
        with tempfile.TemporaryDirectory() as temporary, patch.object(app, 'youtube_downloader', FakeYDL):
            with self.assertRaisesRegex(app.SubtitleError, 'Stream_bereits_beendet'):
                app.run('QRS8MkLhQmM', output_dir=temporary, progress=lambda _: None)

    def test_ended_status_or_confirmation_allows_captions_despite_live_flag(self):
        raw = json.dumps({'events': [{'tStartMs': 0, 'dDurationMs': 2000, 'segs': [{'utf8': 'Archive.'}]}]})
        FakeYDL.info.update(is_live=True, subtitles={'en': [{'ext': 'json3', 'data': raw}]})
        cases = [('was_live', False), ('post_live', False), ('is_live', True)]
        with tempfile.TemporaryDirectory() as temporary, patch.object(app, 'youtube_downloader', FakeYDL):
            for status, confirmed in cases:
                with self.subTest(status=status, confirmed=confirmed):
                    FakeYDL.info['live_status'] = status
                    result = app.run('https://www.youtube.com/live/QRS8MkLhQmM', output_dir=temporary,
                                     stream_ended=confirmed, progress=lambda _: None,
                                     transcriber=lambda *args, **kwargs: self.fail('Unexpected Whisper'))
                    self.assertEqual((result.directory / 'transkript.txt').read_text().strip(), 'Archive.')
                    meta = json.loads((result.directory / 'info.json').read_text())
                    self.assertEqual(meta['stream_ended_confirmed'], confirmed)

    def test_processing_archive_without_captions_has_specific_message(self):
        FakeYDL.info.update(live_status='post_live', is_live=False)
        with tempfile.TemporaryDirectory() as temporary, patch.object(app, 'youtube_downloader', FakeYDL):
            with self.assertRaisesRegex(app.SubtitleError, 'Aufzeichnung.*keine Untertitel'):
                app.run('QRS8MkLhQmM', mode='subtitles', output_dir=temporary, progress=lambda _: None)


class FakeAudioYDL(FakeYDL):
    download_info = None
    selected = None

    def build_format_selector(self, specification):
        from yt_dlp import YoutubeDL

        with YoutubeDL({'quiet': True}) as ydl:
            return ydl.build_format_selector(specification)

    def extract_info(self, url, download=False):
        info = copy.deepcopy(self.download_info if download and self.download_info else self.info)
        if download:
            self.options['match_filter'](info, incomplete=False)
            context = {'formats': info['formats'], 'has_merged_format': False, 'incomplete_formats': True}
            selected = list(self.options['format'](context))[-1]
            type(self).selected = selected
            info.update(selected)
            self.path = Path(self.options['outtmpl'].replace('%(ext)s', info['ext']))
            self.path.write_bytes(b'placeholder audio')
        return info

    def prepare_filename(self, info):
        return str(self.path)


class TestRecentArchiveAudio(unittest.TestCase):
    def setUp(self):
        self.audio_format = {'format_id': 'audio', 'protocol': 'https', 'filesize': 1000,
                             'acodec': 'opus', 'vcodec': 'none', 'ext': 'webm', 'url': 'https://example.test/audio'}
        self.rolling_format = {**self.audio_format, 'format_id': 'rolling', 'protocol': 'm3u8_native'}
        FakeAudioYDL.info = {'id': 'QRS8MkLhQmM', 'title': 'Archive', 'duration': 50000,
                             'live_status': 'post_live', 'formats': [self.audio_format, self.rolling_format]}
        FakeAudioYDL.download_info, FakeAudioYDL.selected = None, None

    def test_finite_audio_preferred_over_manifest_or_large_video(self):
        video = {**self.audio_format, 'format_id': 'video', 'vcodec': 'h264'}
        formats = [self.audio_format, self.rolling_format, video]
        self.assertEqual(list(app.recording_audio_format({'formats': formats})), [self.audio_format])
        self.assertEqual(list(app.recording_audio_format({'formats': [video]})), [video])

    def test_incomplete_audio_and_unknown_length_are_not_full_recordings(self):
        for overrides in ({'filesize': None}, {'filesize': 0}, {'target_duration': 5},
                          {'is_from_start': True}, {'format_note': '(Last 2 hours)'},
                          {'format_note': '(incomplete)'}, {'protocol': 'm3u8_native'}):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(app.SubtitleError, 'fertige Datei'):
                list(app.recording_audio_format({'formats': [{**self.audio_format, **overrides}]}))

    def test_confirmed_ended_and_post_live_downloads_reach_transcriber(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(app, 'youtube_downloader', FakeAudioYDL), \
                patch.object(app, 'audio_duration', return_value=50000):
            for status, confirmed in [('post_live', False), ('is_live', True), ('was_live', False)]:
                with self.subTest(status=status):
                    FakeAudioYDL.info.update(live_status=status, is_live=status == 'is_live')
                    transcriber = Mock(return_value='finished')
                    result = app.run('QRS8MkLhQmM', output_dir=temporary, stream_ended=confirmed,
                                     transcriber=transcriber, progress=lambda _: None)
                    self.assertEqual(result, 'finished')
                    transcriber.assert_called_once()
                    if status != 'was_live':
                        self.assertEqual(FakeAudioYDL.selected['format_id'], 'audio')

    def test_refreshed_metadata_prevents_live_capture_and_rolling_tail(self):
        FakeAudioYDL.info['live_status'] = 'was_live'
        with tempfile.TemporaryDirectory() as temporary, patch.object(app, 'youtube_downloader', FakeAudioYDL):
            for status, message in [('is_live', 'erneut einen Live-Status'), ('post_live', 'fertige Datei')]:
                with self.subTest(status=status):
                    FakeAudioYDL.download_info = {**FakeAudioYDL.info, 'live_status': status,
                                                  'formats': [self.rolling_format]}
                    with self.assertRaisesRegex(app.SubtitleError, message):
                        app.run('QRS8MkLhQmM', output_dir=temporary, progress=lambda _: None,
                                transcriber=lambda *args, **kwargs: self.fail('Unexpected Whisper'))

    def test_short_audio_is_not_reused_or_transcribed(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(app, 'youtube_downloader', FakeAudioYDL), \
                patch.object(app, 'audio_duration', return_value=7200):
            with self.assertRaisesRegex(app.SubtitleError, 'deutlich kürzer'):
                app.run('QRS8MkLhQmM', output_dir=temporary, progress=lambda _: None,
                        transcriber=lambda *args, **kwargs: self.fail('Unexpected Whisper'))
            cache = Path(temporary) / '_audio' / 'QRS8MkLhQmM'
            self.assertFalse((cache / 'audio.webm').exists())
            self.assertTrue((cache / 'audio.incomplete.webm').exists())


class TestRealYoutubeExtractor(unittest.TestCase):
    def test_past_end_timestamp_corrects_live_before_format_extraction(self):
        microformats = [{'liveBroadcastDetails': {'isLiveNow': True, 'endTimestamp': '2020-01-01T00:00:00Z'}}]
        details = [{'isLive': True, 'isUpcoming': True}]
        with app.youtube_downloader(app.ydl_options()) as ydl:
            extractor = ydl.get_info_extractor('Youtube')
            for post_live, expected in [(False, 'was_live'), (True, 'post_live')]:
                details[0]['isPostLiveDvr'] = post_live
                original = copy.deepcopy((microformats, details))
                with patch.object(extractor, '_extract_formats_and_subtitles', return_value=iter([{}])) as extract:
                    result = extractor._list_formats('QRS8MkLhQmM', microformats, details, [], None)
                self.assertEqual(result[1], expected)
                self.assertEqual(extract.call_args.args[3], expected)
                self.assertEqual((microformats, details), original, 'Do not mutate other extractor inputs')
            with patch.object(extractor, '_extract_formats_and_subtitles', return_value=iter([{}])):
                self.assertEqual(extractor._list_formats('QRS8MkLhQmM', microformats, [], [], None)[1], 'was_live')

    def test_future_or_missing_end_timestamp_preserves_live_status(self):
        with app.youtube_downloader(app.ydl_options()) as ydl:
            extractor = ydl.get_info_extractor('Youtube')
            for timestamp in (None, '2999-01-01T00:00:00Z'):
                microformats = [{'liveBroadcastDetails': {'isLiveNow': True, 'endTimestamp': timestamp}}]
                with patch.object(extractor, '_extract_formats_and_subtitles', return_value=iter([{}])):
                    self.assertEqual(extractor._list_formats('QRS8MkLhQmM', microformats, [], [], None)[1], 'is_live')

    def test_missing_duration_does_not_crash_and_patch_is_instance_local(self):
        from yt_dlp import YoutubeDL

        response = [{'storyboards': {'playerStoryboardSpecRenderer': {
            'spec': 'https://i.ytimg.com/sb/test/storyboard3_L$L/$N.jpg?x=1|48#27#100#10#10#0#default#signature',
        }}}]
        with app.youtube_downloader(app.ydl_options()) as ydl:
            extractor = ydl.get_info_extractor('Youtube')
            for duration in (None, 0, 60):
                self.assertEqual(list(extractor._extract_storyboard(response, duration)), [])
            self.assertEqual(ydl._ies['Youtube'], extractor)
        # The standard extractor outside this tool has not been monkeypatched.
        with YoutubeDL({'quiet': True}) as plain:
            self.assertEqual(len(list(plain.get_info_extractor('Youtube')._extract_storyboard(response, 60))), 1)

    def test_access_denial_not_suppressed_by_metadata_mode(self):
        from yt_dlp.utils import ExtractorError

        with app.youtube_downloader({**app.ydl_options(), 'ignore_no_formats_error': True}) as ydl:
            extractor = ydl.get_info_extractor('Youtube')
            for message in ('Sign in to confirm you are not a bot', 'Private video',
                            'The current session has been rate-limited by YouTube'):
                with self.subTest(message=message), self.assertRaises(ExtractorError):
                    extractor.raise_no_formats(message, expected=True)
            # No media formats alone must still permit available subtitle metadata.
            self.assertIsNone(extractor.raise_no_formats('No video formats found', expected=True))


class FakeWhisper:
    attempts = 0
    should_fail = True

    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, *args, **kwargs):
        FakeWhisper.attempts += 1
        if FakeWhisper.attempts == 2 and FakeWhisper.should_fail:
            raise RuntimeError('simulated interruption')
        if FakeWhisper.attempts == 1:
            words = [types.SimpleNamespace(start=599.1, end=599.8, word=' before')]
        else:
            # Second chunk starts at 600, with audio context from 597.
            words = [types.SimpleNamespace(start=2.1, end=2.8, word=' before'),
                     types.SimpleNamespace(start=3.1, end=3.8, word=' after')]
        segment = types.SimpleNamespace(words=words)
        return iter([segment]), types.SimpleNamespace(language='en')


class TestResume(unittest.TestCase):
    def test_interrupted_run_resumes_complete_chunks_with_global_timestamps(self):
        modules = {'ctranslate2': types.SimpleNamespace(get_cuda_device_count=lambda: 0),
                   'faster_whisper': types.SimpleNamespace(WhisperModel=FakeWhisper)}
        FakeWhisper.attempts, FakeWhisper.should_fail = 0, True
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules, modules), \
                patch.object(app, 'audio_duration', return_value=601), patch.object(app.subprocess, 'run'):
            root = Path(temporary)
            audio = root / 'audio.wav'
            audio.write_bytes(b'stable audio fixture')
            metadata = {'title': 'Resume', 'source': 'Whisper'}
            with self.assertRaisesRegex(RuntimeError, 'interruption'):
                app.transcribe_audio(audio, root, metadata, progress=lambda _: None)
            checkpoint = next(root.glob('whisper-*/fortschritt.json'))
            self.assertEqual(json.loads(checkpoint.read_text())['next_chunk'], 1)
            self.assertTrue(checkpoint.with_name('transkript.partial.txt').exists())
            self.assertFalse(checkpoint.with_name('info.json').exists())
            FakeWhisper.should_fail = False
            result = app.transcribe_audio(audio, root, metadata, progress=lambda _: None)
            self.assertEqual((result.directory / 'transkript.txt').read_text().split(), ['before', 'after'])
            self.assertIn('00:10:00,100', (result.directory / 'untertitel.srt').read_text())
            self.assertEqual(FakeWhisper.attempts, 3)
            app.transcribe_audio(audio, root, metadata, progress=lambda _: None)
            self.assertEqual(FakeWhisper.attempts, 3, 'Finished checkpoint should not transcribe again')
            # A changed input must not reuse the old checkpoint.
            audio.write_bytes(b'different audio fixture')
            app.transcribe_audio(audio, root, metadata, progress=lambda _: None)
            self.assertEqual(len(list(root.glob('whisper-*'))), 2)


if __name__ == '__main__':
    unittest.main()
