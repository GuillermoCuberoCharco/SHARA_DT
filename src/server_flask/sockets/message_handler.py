"""
sockets/message_handler.py

Socket.IO namespace /message for the authenticated chat interface.
"""

import base64
import logging

from flask import request
from flask_socketio import Namespace, emit

import state_machine
from auth import verify_token
from services.cloud.openai_api import load_user_messages

logger = logging.getLogger('MessageHandler')

_clients: dict[str, dict] = {}
_audio_buffers: dict[str, bytearray] = {}


class MessageNamespace(Namespace):

    def on_connect(self, auth):
        token = (auth or {}).get('token')
        auth_context = verify_token(token) if token else None

        if not auth_context:
            logger.warning('[/message] Rejected connection - invalid token (sid=%s)', request.sid)
            return False

        user_id = auth_context['user_id']
        user_role = auth_context['role']
        subject_code = auth_context['subject_code']

        logger.info(
            '[/message] Client connected: %s (user=%s, role=%s, subject=%s)',
            request.sid,
            user_id,
            user_role,
            subject_code,
        )
        _clients[request.sid] = {
            'user_id': user_id,
            'user_role': user_role,
            'subject_code': subject_code,
            'tts_enabled': True,
        }
        state_machine.register_session(request.sid, tts_enabled=True)

        emit('registration_success', {
            'status': 'ok',
            'user_id': user_id,
            'role': user_role,
            'subject_code': subject_code,
        })

        try:
            history = load_user_messages(user_id, subject_code)
            emit('conversation_history', {'messages': history})
        except Exception:
            logger.exception('[/message] Failed to load history for user %s [%s]', user_id, subject_code)

    def on_disconnect(self):
        client = _clients.pop(request.sid, None)
        user_id = client['user_id'] if client else '?'
        logger.info('[/message] Client disconnected: %s (user=%s)', request.sid, user_id)
        _cleanup_audio_buffer(request.sid)
        state_machine.unregister_session(request.sid)

    def on_tts_preference(self, data):
        client = _clients.get(request.sid)
        if not client:
            return

        enabled = True
        if isinstance(data, dict):
            enabled = bool(data.get('enabled', True))

        client['tts_enabled'] = enabled
        state_machine.set_tts_enabled(request.sid, enabled)

    def on_audio_stream_start(self, data):
        client = _clients.get(request.sid)
        if not client:
            logger.warning('[/message] audio_stream_start from unregistered sid %s', request.sid)
            return

        _cleanup_audio_buffer(request.sid)
        _audio_buffers[request.sid] = bytearray()

        accepted = state_machine.on_audio_stream_start(
            request.sid,
            client['user_id'],
            client.get('user_role', 'student'),
            client.get('subject_code', ''),
        )
        if not accepted:
            _cleanup_audio_buffer(request.sid)

    def on_audio_chunk(self, data):
        client = _clients.get(request.sid)
        if not client:
            logger.warning('[/message] audio_chunk from unregistered sid %s', request.sid)
            return

        buffer = _audio_buffers.get(request.sid)
        if buffer is None:
            logger.warning('[/message] audio_chunk from %s with no active buffer', request.sid)
            return

        if not isinstance(data, dict):
            return

        b64_data = data.get('data', '')
        if not b64_data:
            return

        try:
            buffer.extend(base64.b64decode(b64_data))
        except Exception as exc:
            logger.warning('[/message] Failed to decode audio chunk: %s', exc)

    def on_audio_stream_end(self, data):
        client = _clients.get(request.sid)
        if not client:
            logger.warning('[/message] audio_stream_end from unregistered sid %s', request.sid)
            return

        buffer = _audio_buffers.pop(request.sid, None)
        if buffer is None:
            logger.warning('[/message] audio_stream_end with no buffer for %s', request.sid)
            return

        state_machine.on_audio_stream_end(
            bytes(buffer),
            request.sid,
            client['user_id'],
            client.get('user_role', 'student'),
            client.get('subject_code', ''),
        )

    def on_client_message(self, data):
        client = _clients.get(request.sid)
        if not client:
            logger.warning('[/message] Message from unregistered sid %s', request.sid)
            return

        if not isinstance(data, dict):
            logger.warning('[/message] Unexpected message format: %s', type(data))
            return

        msg_type = data.get('type', 'client_message')
        user_id = client['user_id']

        if msg_type == 'audio':
            audio_b64 = data.get('data', '')
            if not audio_b64:
                logger.warning('[/message] Empty audio payload received')
                return

            try:
                audio_bytes = base64.b64decode(audio_b64)
            except Exception as exc:
                logger.warning('[/message] Failed to decode raw audio payload: %s', exc)
                return

            logger.info('[/message] Raw audio payload from %s (%s)', user_id, request.sid)
            state_machine.on_audio_stream_end(
                audio_bytes,
                request.sid,
                user_id,
                client.get('user_role', 'student'),
                client.get('subject_code', ''),
            )
            return

        text = data.get('text', '').strip()
        if not text:
            logger.warning('[/message] Empty text message received')
            return

        logger.info('[/message] Text from %s (%s): "%s"', user_id, request.sid, text)
        state_machine.on_text_message(
            text,
            request.sid,
            user_id,
            client.get('user_role', 'student'),
            client.get('subject_code', ''),
        )


def _cleanup_audio_buffer(sid: str):
    _audio_buffers.pop(sid, None)
