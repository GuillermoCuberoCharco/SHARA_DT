"""
sockets/message_handler.py

Socket.IO namespace /message.

Events received from frontend:
    register_client     - web client registration
    set_login_identity  - initial login/session identity
    client_message      - audio (base64 webm/opus blob, legacy) or text from user
    audio_stream_start  - PCM LINEAR16 stream begins
    audio_chunk         - PCM LINEAR16 chunk (base64 Int16 bytes)
    audio_stream_end    - PCM stream finished, trigger batch STT
    user_detected       - face detected by FaceDetection.jsx
    user_lost           - face lost
    tts_complete        - frontend finished playing TTS audio
    transcription_result- browser fallback transcript

Events emitted to frontend:
    registration_success
    robot_message       - {text, state, audio (base64), continue}
    state_update        - {state}
    transcription_result- {text} echo of what the user said
"""

import base64
import logging

from flask import request
from flask_socketio import Namespace, emit

import state_machine

logger = logging.getLogger('MessageHandler')

# Track connected web clients: sid -> {username, loginName, sessionId, registered}
_clients: dict = {}

# Per-session PCM audio buffers. Chunks are accumulated until stream_end.
_audio_buffers: dict = {}  # sid -> bytearray


class MessageNamespace(Namespace):

    def on_connect(self):
        logger.info(f'[/message] Client connected: {request.sid}')
        _clients[request.sid] = {
            'registered': False,
            'username': None,
            'loginName': None,
            'sessionId': None,
        }

    def on_disconnect(self):
        logger.info(f'[/message] Client disconnected: {request.sid}')
        client_data = _clients.pop(request.sid, None) or {}
        if client_data:
            state_machine.on_client_disconnect(client_data)
        _cleanup_audio_buffer(request.sid)

    def on_register_client(self, data):
        client_type = data if isinstance(data, str) else data.get('client', 'web')
        logger.info(f'[/message] Registering client {request.sid} as {client_type}')

        if request.sid in _clients:
            _clients[request.sid]['registered'] = True

        emit('registration_success', {'status': 'ok', 'role': client_type})

    def on_set_login_identity(self, data):
        logger.info(f'[/message] set_login_identity from {request.sid}: {data}')

        if request.sid in _clients and isinstance(data, dict):
            _clients[request.sid]['username'] = data.get('userName')
            _clients[request.sid]['loginName'] = data.get('loginName')
            _clients[request.sid]['sessionId'] = data.get('sessionId')

        state_machine.on_session_login(data or {})

    def on_audio_stream_start(self, data):
        sid = request.sid
        logger.info(f'[/message] audio_stream_start from {sid}')

        _cleanup_audio_buffer(sid)
        _audio_buffers[sid] = bytearray()
        state_machine.on_audio_stream_start(sid)

    def on_audio_chunk(self, data):
        sid = request.sid
        buf = _audio_buffers.get(sid)
        if buf is None:
            logger.warning(f'[/message] audio_chunk from {sid} with no active buffer - ignoring')
            return

        b64_data = data.get('data', '') if isinstance(data, dict) else ''
        if not b64_data:
            return

        try:
            raw_bytes = base64.b64decode(b64_data)
            buf.extend(raw_bytes)
        except Exception as e:
            logger.warning(f'[/message] Failed to decode audio_chunk: {e}')

    def on_audio_stream_end(self, data):
        sid = request.sid
        logger.info(f'[/message] audio_stream_end from {sid}')

        buf = _audio_buffers.pop(sid, None)
        if buf:
            audio_bytes = bytes(buf)
            logger.info(f'[/message] Collected {len(audio_bytes)} PCM bytes, submitting to state machine')
            state_machine.on_audio_stream_end(audio_bytes, sid)
        else:
            logger.warning(f'[/message] audio_stream_end with no buffer for {sid}')

    def on_client_message(self, data):
        if not isinstance(data, dict):
            logger.warning(f'[/message] Unexpected client_message format: {type(data)}')
            return

        msg_type = data.get('type', '')

        if msg_type == 'audio':
            audio_b64 = data.get('data', '')
            if audio_b64:
                logger.info(f'[/message] Legacy audio blob received from {request.sid}')
                state_machine.on_audio_message(audio_b64, request.sid)
            else:
                logger.warning('[/message] Audio message with empty data')

        elif msg_type in ('client_message', 'text'):
            text = data.get('text', '').strip()
            if text:
                logger.info(f'[/message] Text received from {request.sid}: "{text}"')
                emit('client_message', {'text': text, 'sender': 'client'}, broadcast=True)
                state_machine.on_text_message(text, request.sid)

        else:
            text = data.get('text', '').strip()
            if text:
                state_machine.on_text_message(text, request.sid)

    def on_user_detected(self, data):
        logger.info(f'[/message] user_detected from {request.sid}: {data}')
        state_machine.on_user_detected(data or {})

    def on_user_lost(self, data):
        logger.info(f'[/message] user_lost from {request.sid}')
        state_machine.on_user_lost(data or {})

    def on_tts_complete(self, data):
        logger.info(f'[/message] tts_complete from {request.sid}')
        state_machine.on_tts_complete(request.sid)

    def on_transcription_result(self, data):
        text = data.get('text', '').strip() if isinstance(data, dict) else str(data).strip()
        if text:
            logger.info(f'[/message] transcription_result: "{text}"')
            emit('client_message', {'text': text, 'sender': 'client'}, broadcast=True)
            state_machine.on_text_message(text, request.sid)


def _cleanup_audio_buffer(sid: str):
    buf = _audio_buffers.pop(sid, None)
    if buf:
        logger.debug(f'Audio buffer cleaned up for {sid}')
