import base64
import types
import unittest
from unittest.mock import Mock

import state_machine


class _RecordingSocket:
    def __init__(self):
        self.events = []

    def emit(self, event, payload, **kwargs):
        self.events.append((event, payload, kwargs))


class _ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)


class _QueuedExecutor:
    def __init__(self):
        self.jobs = []

    def submit(self, function, *args):
        self.jobs.append((function, args))

    def run_all(self):
        for function, args in self.jobs:
            function(*args)
        self.jobs.clear()


class StateMachineTtsTests(unittest.TestCase):
    def setUp(self):
        self.original_socket = state_machine._socketio
        self.original_server = state_machine._server
        self.original_tts_executor = state_machine._tts_executor

        self.socket = _RecordingSocket()
        self.synthesize_response = Mock(return_value=b"mp3-audio")
        self.server = types.SimpleNamespace(
            synthesize_response=self.synthesize_response,
            TTS_MIME_TYPE="audio/mpeg",
        )
        state_machine.init(self.socket, self.server)

        with state_machine._lock:
            state_machine._processing_users.clear()
            state_machine._tts_preferences.clear()
            state_machine._tts_generations.clear()

    def tearDown(self):
        with state_machine._lock:
            state_machine._processing_users.clear()
            state_machine._tts_preferences.clear()
            state_machine._tts_generations.clear()

        state_machine._socketio = self.original_socket
        state_machine._server = self.original_server
        state_machine._tts_executor = self.original_tts_executor

    @staticmethod
    def _response():
        return types.SimpleNamespace(text="Respuesta de SHARA", robot_mood="happy")

    def _mark_processing(self):
        with state_machine._lock:
            state_machine._processing_users.add("alumna::matematicas")

    def test_tts_disabled_emits_text_without_calling_google(self):
        state_machine.register_session("sid-1", tts_enabled=False)
        state_machine._tts_executor = _ImmediateExecutor()
        self._mark_processing()

        state_machine._handle_response(
            self._response(),
            "sid-1",
            "alumna",
            "matematicas",
        )

        self.synthesize_response.assert_not_called()
        self.assertEqual([event[0] for event in self.socket.events], ["robot_message", "state_update"])
        self.assertEqual(self.socket.events[0][1]["text"], "Respuesta de SHARA")
        self.assertNotIn("audio", self.socket.events[0][1])
        self.assertEqual(self.socket.events[1][1], {"state": "idle"})

    def test_tts_enabled_emits_text_before_separate_mp3_audio(self):
        state_machine.register_session("sid-1", tts_enabled=True)
        state_machine._tts_executor = _ImmediateExecutor()
        self._mark_processing()

        state_machine._handle_response(
            self._response(),
            "sid-1",
            "alumna",
            "matematicas",
        )

        self.synthesize_response.assert_called_once_with("Respuesta de SHARA")
        self.assertEqual(
            [event[0] for event in self.socket.events],
            ["robot_message", "state_update", "robot_audio"],
        )
        text_payload = self.socket.events[0][1]
        audio_payload = self.socket.events[2][1]
        self.assertEqual(audio_payload["id"], text_payload["id"])
        self.assertEqual(audio_payload["mime_type"], "audio/mpeg")
        self.assertEqual(base64.b64decode(audio_payload["audio"]), b"mp3-audio")

    def test_disabling_tts_cancels_queued_synthesis(self):
        queued_executor = _QueuedExecutor()
        state_machine._tts_executor = queued_executor
        state_machine.register_session("sid-1", tts_enabled=True)
        self._mark_processing()

        state_machine._handle_response(
            self._response(),
            "sid-1",
            "alumna",
            "matematicas",
        )
        state_machine.set_tts_enabled("sid-1", False)
        queued_executor.run_all()

        self.synthesize_response.assert_not_called()
        self.assertEqual([event[0] for event in self.socket.events], ["robot_message", "state_update"])


if __name__ == "__main__":
    unittest.main()
