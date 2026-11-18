"""Regression tests with the real gevent hub and native workers. No cloud or DB."""
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gevent

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import state_machine as sm


class TurnTests(unittest.TestCase):
    def setUp(self):
        self.socket = Mock()
        self.cloud = Mock(Request=SimpleNamespace)
        self.cloud.query_with_text.side_effect = lambda r: SimpleNamespace(
            request=r, audio=None, text='Hola', username=None, continue_conversation=True,
            robot_mood='joy', audio_mime_type='audio/mpeg', exchange=['test'],
        )
        self.cloud.streaming_stt.side_effect = lambda chunks: 'hola' if b''.join(chunks) else ''
        self.cloud.speech_to_text.return_value = ''
        self.cloud.text_to_speech.return_value = b'MP3'
        sm.init(self.socket, self.cloud)
        self.recent = self.enter_patch('greeted_recently', return_value=False)
        self.save_name = self.enter_patch('update_shara_name', return_value=True)
        self.enter_patch('_proactive', new=sm.ProactiveService())
        sm.register_session('sid', 'cuenta', None)
        sm.on_session_login('sid', {'sessionId': 'page', 'protocolVersion': 2})
        self.c = sm._sessions['sid']
        self.addCleanup(sm.on_client_disconnect, 'sid')

    def enter_patch(self, name, **kwargs):
        p = patch.object(sm, name, **kwargs)
        self.addCleanup(p.stop)
        return p.start()

    def event(self, **data):
        return dict(sessionId='page', turnId=self.c.turn_id, **data)

    def wait_for(self, condition):
        with gevent.Timeout(4, AssertionError('Transition timed out')):
            while not condition():
                gevent.sleep(.002)

    def listen(self):
        self.recent.return_value = True
        sm.on_user_detected('sid', self.event())
        self.wait_for(lambda: self.c.state == 'listening')

    def confirm_face(self):
        sm.on_user_detected('sid', self.event(presenceCheck=self.c.presence_check))

    def greeting(self):
        sm.on_user_detected('sid', self.event())
        self.wait_for(lambda: self.c.presence_check)
        self.confirm_face()
        self.assertEqual(self.c.state, 'speaking')

    def ack(self, status='played'):
        sm.on_tts_complete('sid', self.event(messageId=self.c.current_tts_message_id, status=status))

    def test_listening_deadline_begins_when_microphone_is_ready(self):
        self.enter_patch('LISTENING_RESPONSE_TIMEOUT_SECONDS', new=.025)
        self.listen()
        gevent.sleep(.04)
        self.assertEqual(self.c.state, 'listening')
        sm.on_microphone_ready('sid', self.event())
        first = self.c.timer
        sm.on_microphone_ready('sid', self.event())
        self.assertIs(first, self.c.timer)
        self.wait_for(lambda: self.c.state == 'idle_presence')
        self.assertTrue(self.c.presence_check)
        self.assertIsNone(self.c.stream)

    def test_late_audio_and_old_watchdog_cannot_change_verified_new_turn(self):
        self.enter_patch('LISTENING_RESPONSE_TIMEOUT_SECONDS', new=.02)
        self.listen()
        old = self.event()
        sm.on_microphone_ready('sid', old)
        self.wait_for(lambda: self.c.presence_check)
        self.assertFalse(sm.on_audio_stream_start('sid', old))
        self.confirm_face()
        sm.on_microphone_ready('sid', self.event())
        self.assertTrue(sm.on_audio_stream_start('sid', self.event()))
        sm.on_audio_chunk(b'old', 'sid', old)
        self.assertFalse(sm.on_audio_stream_end('sid', old))
        gevent.sleep(.04)
        self.assertEqual(self.c.state, 'recording')
        self.assertEqual(self.c.stream.buffer, b'')

    def test_worker_turn_requires_fresh_presence_and_persists_only_once_after_playback(self):
        self.listen()
        sm.on_microphone_ready('sid', self.event())
        self.assertTrue(sm.on_audio_stream_start('sid', self.event()))
        sm.on_audio_chunk(b'pcm', 'sid', self.event())
        self.assertTrue(sm.on_audio_stream_end('sid', self.event()))
        self.wait_for(lambda: self.c.presence_check)
        self.assertEqual(self.c.state, 'processing_query')
        sm.on_user_detected('sid', self.event(presenceCheck='old-check'))
        self.assertEqual(self.c.state, 'processing_query')
        self.confirm_face()
        self.cloud.persist_exchange.assert_not_called()
        original = self.event(messageId=self.c.current_tts_message_id, status='played')
        sm.on_tts_complete('sid', original)
        sm.on_tts_complete('sid', original)
        self.wait_for(lambda: self.c.presence_check)
        self.confirm_face()
        self.assertEqual(self.c.state, 'listening')
        self.cloud.persist_exchange.assert_called_once()

    def test_presence_loss_invalidates_late_cloud_reply_and_does_not_block_hub(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        def slow(_):
            gate.wait(.5)
            return None
        self.cloud.query_with_text.side_effect = slow
        sm.on_user_detected('sid', self.event())
        self.wait_for(lambda: self.cloud.query_with_text.called)
        sm.on_user_lost('sid', self.event())
        self.assertFalse(gate.is_set())
        gate.set()
        gevent.sleep(.03)
        self.assertEqual(self.c.state, 'idle')
        self.assertIsNone(self.c.response)
        self.cloud.text_to_speech.assert_not_called()
        self.assertFalse(any(c.args[0] == 'robot_message' for c in self.socket.emit.call_args_list))

    def test_failed_or_missing_playback_releases_greeting_without_saving(self):
        self.enter_patch('TTS_WATCHDOG_MIN_SECONDS', new=.01)
        self.enter_patch('TTS_WATCHDOG_MAX_SECONDS', new=.01)
        self.enter_patch('TTS_WATCHDOG_ACK_GRACE_SECONDS', new=.01)
        self.greeting()
        self.wait_for(lambda: self.c.state == 'idle_presence')
        sm.on_user_lost('sid', self.event())
        self.greeting()
        self.ack('failed')
        self.assertEqual(self.c.state, 'idle_presence')
        self.assertFalse(sm._proactive.delivered_until)
        self.assertFalse(sm._proactive.pending)
        self.cloud.persist_exchange.assert_not_called()

    def test_worker_watchdog_and_empty_transcription_recheck(self):
        self.listen()
        self.cloud.streaming_stt.side_effect = lambda chunks: ''
        sm.on_microphone_ready('sid', self.event())
        sm.on_audio_stream_start('sid', self.event())
        sm.on_audio_chunk(b'all PCM', 'sid', self.event())
        sm.on_audio_stream_end('sid', self.event())
        self.wait_for(lambda: self.c.presence_check)
        self.cloud.speech_to_text.assert_called_once_with(b'all PCM')
        self.assertEqual(self.c.state, 'idle_presence')
        sm.on_user_lost('sid', self.event())
        self.assertEqual(self.c.state, 'idle')

    def test_recording_deadline_closes_orphaned_stream(self):
        self.enter_patch('RECORDING_TIMEOUT', new=.02)
        self.listen()
        sm.on_microphone_ready('sid', self.event())
        sm.on_audio_stream_start('sid', self.event())
        stream = self.c.stream
        self.wait_for(lambda: self.c.presence_check)
        self.assertTrue(stream.closed)
        self.assertIsNone(self.c.stream)

    def test_silent_capture_cap_rechecks_only_its_own_turn(self):
        self.listen()
        previous = self.event(reason='silence')
        self.assertTrue(sm.on_audio_stream_end('sid', previous))
        self.confirm_face()
        self.assertFalse(sm.on_audio_stream_end('sid', previous))
        self.assertEqual(self.c.state, 'listening')

    def test_delivered_history_failure_returns_to_rest_with_visible_error(self):
        self.cloud.persist_exchange.side_effect = RuntimeError('database unavailable')
        self.greeting()
        with self.assertLogs('StateMachine', level='ERROR'), patch.object(gevent.get_hub(), 'exception_stream', None):
            self.ack()
            self.wait_for(lambda: self.c.state == 'idle_presence')
        self.assertEqual(self.cloud.persist_exchange.call_count, 2)
        self.assertIsNone(self.c.presence_check)
        self.assertEqual(self.socket.emit.call_args.args[0], 'interaction_error')

    def test_literal_name_and_reconnection_cooldown(self):
        self.enter_patch('LISTENING_RESPONSE_TIMEOUT_SECONDS', new=.02)
        self.greeting()
        self.ack()
        self.wait_for(lambda: self.c.presence_check)
        self.confirm_face()
        sm.on_microphone_ready('sid', self.event())
        self.wait_for(lambda: self.c.presence_check)
        self.confirm_face()
        self.assertEqual(self.c.state, 'listening')
        sm.on_text_message('sid', self.event(text='No lo sé'))
        self.wait_for(lambda: self.c.presence_check)
        self.save_name.assert_called_once_with('cuenta', 'No lo sé')
        sm.on_client_disconnect('sid')
        sm.register_session('sid', 'cuenta', 'No lo sé')
        sm.on_session_login('sid', {'sessionId':'page', 'protocolVersion':2})
        self.c = sm._sessions['sid']
        sm.on_user_detected('sid', self.event())
        self.assertEqual(self.c.state, 'listening')

    def test_goodbye_waits_for_explicit_resume(self):
        self.greeting()
        self.ack()
        self.wait_for(lambda: self.c.presence_check)
        self.confirm_face()
        self.assertEqual(self.c.state, 'listening')
        sm.on_text_message('sid', self.event(text='Adiós'))
        self.wait_for(lambda: self.c.presence_check)
        self.c.response.continue_conversation = False
        self.confirm_face()
        self.ack()
        self.wait_for(lambda: self.c.state == 'idle_presence')
        self.assertIsNone(self.c.presence_check)
        sm.on_user_detected('sid', self.event())
        self.assertEqual(self.c.state, 'idle_presence')
        sm.on_resume('sid', self.event())
        self.confirm_face()
        self.assertEqual(self.c.state, 'listening')

    def test_old_page_or_connection_cannot_change_current_session(self):
        sm.on_user_detected('sid', dict(self.event(), sessionId='other'))
        self.assertEqual(self.c.state, 'idle')
        self.listen()
        sm.on_client_disconnect('sid')
        sm.on_user_detected('sid', self.event())
        self.assertNotIn('sid', sm._sessions)
