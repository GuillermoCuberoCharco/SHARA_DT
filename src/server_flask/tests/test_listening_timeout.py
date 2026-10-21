import sys
import types
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


class _FakeGreenlet:
    def __init__(self, callback, args):
        self.callback = callback
        self.args = args
        self.dead = False

    def kill(self):
        self.dead = True


class _FakeGevent(types.ModuleType):
    def __init__(self):
        super().__init__('gevent')
        self.scheduled = []

    def spawn_later(self, timeout, callback, *args):
        greenlet = _FakeGreenlet(callback, args)
        self.scheduled.append((timeout, greenlet))
        return greenlet

    @staticmethod
    def spawn(callback, *args):
        return callback(*args)


fake_gevent = _FakeGevent()
sys.modules['gevent'] = fake_gevent

fake_auth = types.ModuleType('auth')
fake_auth.get_shara_name = lambda _login_name: None
fake_auth.update_shara_name = lambda _login_name, _shara_name: True
sys.modules['auth'] = fake_auth


class _FakeProactiveService:
    def __init__(self, callback=None):
        self.callback = callback

    def cancel_timers(self):
        pass

    def update(self, *_args, **_kwargs):
        pass


fake_proactive = types.ModuleType('proactive_service')
fake_proactive.ProactiveService = _FakeProactiveService
sys.modules['proactive_service'] = fake_proactive

import state_machine


class _FakeSocket:
    def __init__(self):
        self.events = []

    def emit(self, event, payload, **kwargs):
        self.events.append((event, payload, kwargs))


class ListeningTimeoutTests(unittest.TestCase):
    def setUp(self):
        state_machine._session_contexts.clear()
        state_machine._proactive_services.clear()
        state_machine._audio_streams.clear()
        state_machine._speaking_watchdogs.clear()
        state_machine._listening_watchdogs.clear()
        state_machine._server = None
        state_machine._socketio = _FakeSocket()
        state_machine.LISTENING_RESPONSE_TIMEOUT_SECONDS = 12
        fake_gevent.scheduled.clear()
        self.sid = 'test-sid'

    def tearDown(self):
        state_machine._cancel_listening_watchdog(self.sid)
        state_machine._discard_audio_stream(self.sid)
        state_machine._session_contexts.clear()

    def _context(self, state='speaking'):
        context = state_machine._get_context(self.sid)
        context.state = state
        context.face_session_id = 'face-session'
        context.continue_conversation = True
        context.proactive_question = 'how_are_you'
        context.unknown_user_interactions = 2
        return context

    def test_entering_listening_starts_one_session_watchdog(self):
        context = self._context()

        state_machine.process_transition('speaking2listening', {}, self.sid)

        self.assertEqual(context.state, 'listening')
        self.assertIn(self.sid, state_machine._listening_watchdogs)
        self.assertEqual(len(fake_gevent.scheduled), 1)
        self.assertEqual(fake_gevent.scheduled[0][0], 12)
        self.assertEqual(state_machine._socketio.events[-1][1]['state'], 'listening')

    def test_no_response_timeout_returns_to_idle_presence_and_cleans_turn(self):
        context = self._context()
        state_machine.process_transition('speaking2listening', {}, self.sid)
        cycle_id = state_machine._listening_watchdogs[self.sid]['cycle_id']

        state_machine._handle_listening_watchdog_timeout(self.sid, cycle_id)

        self.assertEqual(context.state, 'idle_presence')
        self.assertFalse(context.continue_conversation)
        self.assertEqual(context.proactive_question, '')
        self.assertEqual(context.unknown_user_interactions, 0)
        self.assertNotIn(self.sid, state_machine._listening_watchdogs)
        self.assertEqual(state_machine._socketio.events[-1][1]['state'], 'idle_presence')

    def test_detected_voice_cancels_watchdog_and_enters_recording(self):
        context = self._context()
        state_machine.process_transition('speaking2listening', {}, self.sid)
        greenlet = state_machine._listening_watchdogs[self.sid]['greenlet']

        accepted = state_machine.on_audio_stream_start(self.sid)

        self.assertTrue(accepted)
        self.assertEqual(context.state, 'recording')
        self.assertTrue(greenlet.dead)
        self.assertNotIn(self.sid, state_machine._listening_watchdogs)
        self.assertIn(self.sid, state_machine._audio_streams)

    def test_late_audio_start_is_rejected_after_timeout(self):
        context = self._context()
        state_machine.process_transition('speaking2listening', {}, self.sid)
        cycle_id = state_machine._listening_watchdogs[self.sid]['cycle_id']
        state_machine._handle_listening_watchdog_timeout(self.sid, cycle_id)

        accepted = state_machine.on_audio_stream_start(self.sid)

        self.assertFalse(accepted)
        self.assertEqual(context.state, 'idle_presence')
        self.assertNotIn(self.sid, state_machine._audio_streams)

    def test_stale_watchdog_cannot_close_a_new_listening_cycle(self):
        context = self._context()
        state_machine.process_transition('speaking2listening', {}, self.sid)
        old_cycle_id = state_machine._listening_watchdogs[self.sid]['cycle_id']
        new_cycle_id = state_machine._start_listening_watchdog(self.sid)

        state_machine._handle_listening_watchdog_timeout(self.sid, old_cycle_id)

        self.assertEqual(context.state, 'listening')
        self.assertEqual(
            state_machine._listening_watchdogs[self.sid]['cycle_id'],
            new_cycle_id,
        )


if __name__ == '__main__':
    unittest.main()
