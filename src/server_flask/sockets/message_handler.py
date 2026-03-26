"""
sockets/message_handler.py

Socket.IO namespace /message — text-only chat interface with JWT auth.

Connection flow:
    1. Frontend passes { token: <JWT> } in Socket.IO auth option.
    2. on_connect validates the token — rejects if invalid/missing.
    3. On success, emits registration_success with user_id.

Events received from frontend:
    client_message   — { type, text } — text message from user

Events emitted to frontend:
    registration_success — { status, user_id }
    robot_message        — { text, state }
    state_update         — { state }
"""

import logging

from flask import request
from flask_socketio import Namespace, emit

import state_machine
from auth import verify_token
from services.cloud.openai_api import load_user_messages

logger = logging.getLogger('MessageHandler')

# sid → { user_id }
_clients: dict = {}


class MessageNamespace(Namespace):

    def on_connect(self, auth):
        token = (auth or {}).get('token')
        user_id = verify_token(token) if token else None

        if not user_id:
            logger.warning(f'[/message] Rejected connection — invalid token (sid={request.sid})')
            return False  # refuse connection

        logger.info(f'[/message] Client connected: {request.sid} (user={user_id})')
        _clients[request.sid] = {'user_id': user_id}
        emit('registration_success', {'status': 'ok', 'user_id': user_id})
        try:
            history = load_user_messages(user_id)
            emit('conversation_history', {'messages': history})
        except Exception:
            logger.exception(f'[/message] Failed to load history for user {user_id}')

    def on_disconnect(self):
        client = _clients.pop(request.sid, None)
        user_id = client['user_id'] if client else '?'
        logger.info(f'[/message] Client disconnected: {request.sid} (user={user_id})')

    def on_client_message(self, data):
        """Text message from the user."""
        client = _clients.get(request.sid)
        if not client:
            logger.warning(f'[/message] Message from unregistered sid {request.sid}')
            return

        if not isinstance(data, dict):
            logger.warning(f'[/message] Unexpected message format: {type(data)}')
            return

        text = data.get('text', '').strip()
        if not text:
            logger.warning('[/message] Empty text message received')
            return

        user_id = client['user_id']
        logger.info(f'[/message] Text from {user_id} ({request.sid}): "{text}"')
        state_machine.on_text_message(text, request.sid, user_id)
