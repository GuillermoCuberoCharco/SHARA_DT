"""Authenticated Socket.IO entry points for the robot."""
import base64

import gevent
from flask import request
from flask_socketio import Namespace, emit

import state_machine
from auth import get_shara_name


class MessageNamespace(Namespace):
    def __init__(self, namespace, authenticated_login):
        super().__init__(namespace)
        self.authenticated_login = authenticated_login

    def on_connect(self, auth=None):
        login = self.authenticated_login()
        if not login:
            return False
        name = gevent.get_hub().threadpool.spawn(get_shara_name, login).get()
        state_machine.register_session(request.sid, login, name)

    def on_disconnect(self, reason=None):
        state_machine.on_client_disconnect(request.sid)

    def on_register_client(self, data):
        emit('registration_success', {'status': 'ok', 'role': 'web'})

    def on_set_login_identity(self, data):
        state_machine.on_session_login(request.sid, data)

    def on_microphone_ready(self, data):
        state_machine.on_microphone_ready(request.sid, data)

    def on_device_error(self, data):
        state_machine.on_device_error(request.sid, data)

    def on_resume_listening(self, data):
        state_machine.on_resume(request.sid, data)

    def on_audio_stream_start(self, data):
        return state_machine.on_audio_stream_start(request.sid, data)

    def on_audio_chunk(self, data):
        try:
            chunk = base64.b64decode(data['data'], validate=True)
        except (ValueError, TypeError, KeyError):
            return
        if chunk:
            state_machine.on_audio_chunk(chunk, request.sid, data)

    def on_audio_stream_end(self, data):
        return state_machine.on_audio_stream_end(request.sid, data)

    def on_client_message(self, data):
        if isinstance(data, dict):
            if data.get('type') == 'audio':
                state_machine.on_audio_message(request.sid, data)
            else:
                state_machine.on_text_message(request.sid, data)

    def on_user_detected(self, data):
        state_machine.on_user_detected(request.sid, data)

    def on_user_lost(self, data):
        state_machine.on_user_lost(request.sid, data)

    def on_tts_complete(self, data):
        state_machine.on_tts_complete(request.sid, data or {})

    def on_transcription_result(self, data):
        state_machine.on_text_message(request.sid, data if isinstance(data, dict) else {'text': str(data)})
