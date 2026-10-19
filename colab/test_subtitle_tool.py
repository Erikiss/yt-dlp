"""Offline regression checks for complete transcripts and restart safety."""

import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

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
        with tempfile.TemporaryDirectory() as temporary, patch('yt_dlp.YoutubeDL', FakeYDL):
            result = app.run('QRS8MkLhQmM', output_dir=temporary, progress=lambda _: None,
                             transcriber=lambda *args, **kwargs: self.fail('Unexpected Whisper'))
            self.assertEqual((result.directory / 'original.json3').read_text(), raw)
            self.assertIn('12:30:00,000', (result.directory / 'untertitel.srt').read_text())

    def test_absent_captions_in_captions_only_mode_is_clear(self):
        with tempfile.TemporaryDirectory() as temporary, patch('yt_dlp.YoutubeDL', FakeYDL):
            with self.assertRaisesRegex(app.SubtitleError, 'Keine vorhandenen'):
                app.run('QRS8MkLhQmM', mode='subtitles', output_dir=temporary, progress=lambda _: None)

    def test_blocked_cloud_is_not_misreported_as_no_captions(self):
        FakeYDL.failure = RuntimeError('HTTP Error 429: Too Many Requests')
        with tempfile.TemporaryDirectory() as temporary, patch('yt_dlp.YoutubeDL', FakeYDL):
            with self.assertRaisesRegex(app.SubtitleError, 'kein fehlender Untertitel'):
                app.run('QRS8MkLhQmM', output_dir=temporary, progress=lambda _: None,
                        transcriber=lambda *args, **kwargs: self.fail('Unexpected Whisper'))

    def test_live_stream_rejected(self):
        FakeYDL.info['is_live'] = True
        with tempfile.TemporaryDirectory() as temporary, patch('yt_dlp.YoutubeDL', FakeYDL):
            with self.assertRaisesRegex(app.SubtitleError, 'Livestreams'):
                app.run('QRS8MkLhQmM', output_dir=temporary, progress=lambda _: None)


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
