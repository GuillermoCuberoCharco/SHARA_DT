"""
sockets/message_handler.py

Socket.IO namespace /message — equivalent to Node.js messageHandler.cjs.

Events received from frontend:
    register_client     — web client registration
    client_message      — audio (base64) or text from user
    user_detected       — face detected by FaceDetection.jsx
    user_lost           — face lost
    tts_complete        — frontend finished playing TTS audio
    transcription_result— STT result (text) from browser fallback

Events emitted to frontend:
    registration_success
    robot_message       — {text, state, audio (base64), continue}
    state_update        — {state}
"""

import logging

from flask_socketio import Namespace, emit, join_room
from flask import request

import state_machine

logger = logging.getLogger('MessageHandler')

# Track connected web clients: sid → {username, registered}
_clients: dict = {}


class MessageNamespace(Namespace):

    def on_connect(self):
        logger.info(f'[/message] Client connected: {request.sid}')
        _clients[request.sid] = {'registered': False, 'username': None}

    def on_disconnect(self):
        logger.info(f'[/message] Client disconnected: {request.sid}')
        _clients.pop(request.sid, None)

    def on_register_client(self, data):
        """
        Client registration. data can be a string ('web') or dict.
        Equivalent to socket.on('register_client') in messageHandler.cjs.
        """
        client_type = data if isinstance(data, str) else data.get('client', 'web')
        logger.info(f'[/message] Registering client {request.sid} as {client_type}')

        if request.sid in _clients:
            _clients[request.sid]['registered'] = True

        emit('registration_success', {'status': 'ok', 'role': client_type})

    def on_client_message(self, data):
        """
        Message from user — either audio blob (base64) or text.

        Expected payload:
            { type: 'audio', data: '<base64>', socketId: '...' }
            { type: 'client_message', text: '...', username: '...' }
        """
        if not isinstance(data, dict):
            logger.warning(f'[/message] Unexpected client_message format: {type(data)}')
            return

        msg_type = data.get('type', '')

        if msg_type == 'audio':
            audio_b64 = data.get('data', '')
            if audio_b64:
                logger.info(f'[/message] Audio received from {request.sid}')
                state_machine.on_audio_message(audio_b64, request.sid)
            else:
                logger.warning('[/message] Audio message with empty data')

        elif msg_type in ('client_message', 'text'):
            text = data.get('text', '').strip()
            if text:
                logger.info(f'[/message] Text received from {request.sid}: "{text}"')
                # Echo back so chat UI shows the user message
                emit('client_message', {'text': text, 'sender': 'client'}, broadcast=True)
                state_machine.on_text_message(text, request.sid)

        else:
            # Fallback: plain text message
            text = data.get('text', '').strip()
            if text:
                state_machine.on_text_message(text, request.sid)

    def on_user_detected(self, data):
        """
        Face detected by FaceDetection.jsx.
        Replaces wakeface 'face_listen' + face recognition hardware events.
        """
        logger.info(f'[/message] user_detected from {request.sid}: {data}')
        state_machine.on_user_detected(data or {})

    def on_user_lost(self, data):
        """Face lost by FaceDetection.jsx."""
        logger.info(f'[/message] user_lost from {request.sid}')
        state_machine.on_user_lost(data or {})

    def on_tts_complete(self, data):
        """Frontend finished playing TTS audio."""
        logger.info(f'[/message] tts_complete from {request.sid}')
        state_machine.on_tts_complete(request.sid)

    def on_transcription_result(self, data):
        """
        Browser-side STT result (text already transcribed).
        """
        text = data.get('text', '').strip() if isinstance(data, dict) else str(data).strip()
        if text:
            logger.info(f'[/message] transcription_result: "{text}"')
            emit('client_message', {'text': text, 'sender': 'client'}, broadcast=True)
            state_machine.on_text_message(text, request.sid)