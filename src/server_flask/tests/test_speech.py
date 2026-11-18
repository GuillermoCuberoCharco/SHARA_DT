import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class StreamingSpeechTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # No credentials or remote connections are needed to exercise the SDK responses.
        with patch.dict(os.environ, {'GOOGLE_APPLICATION_CREDENTIALS': '', 'GOOGLE_CLIENT_EMAIL': ''}), \
                patch('google.cloud.speech.SpeechClient'), patch('google.cloud.texttospeech.TextToSpeechClient'):
            from services.cloud import google_api
        cls.api = google_api

    def recognize(self, segments, consume_all=True):
        def google(config, requests, timeout):
            if consume_all:
                list(requests)
            else:
                next(requests)
            results = [SimpleNamespace(is_final=final, alternatives=[SimpleNamespace(transcript=text)])
                       for text, final in segments]
            return [SimpleNamespace(results=results)]
        with patch.object(self.api.clientSTT, 'streaming_recognize', google):
            return self.api.streaming_speech_to_text(iter([b'a', b'b']))

    def test_all_final_segments_in_order(self):
        self.assertEqual(self.recognize([('provi', False), ('primera', True), ('segunda', True)]),
                         'primera segunda')

    def test_partial_tail_or_early_rpc_end_falls_back_to_full_recording(self):
        self.assertEqual(self.recognize([('primera', True), ('segu', False)]), '')
        self.assertEqual(self.recognize([('primera', True)], consume_all=False), '')
        self.assertEqual(self.recognize([]), '')
