"""
sockets/message_handler.py

Socket.IO namespace /message — text-only chat interface.

Events received from frontend:
    register_client  — web client registration
    client_message   — text message from user

Events emitted to frontend:
    registration_success
    robot_message    — {text, state}
    state_update     — {state}
"""

import logging

from flask import request
from flask_socketio import Namespace, emit

import state_machine

logger = logging.getLogger('MessageHandler')

_clients: dict = {}


class MessageNamespace(Namespace):

    def on_connect(self):
        logger.info(f'[/message] Client connected: {request.sid}')
        _clients[request.sid] = {'registered': False}

    def on_disconnect(self):
        logger.info(f'[/message] Client disconnected: {request.sid}')
        _clients.pop(request.sid, None)

    def on_register_client(self, data):
        client_type = data if isinstance(data, str) else data.get('client', 'web')
        logger.info(f'[/message] Registering client {request.sid} as {client_type}')

        if request.sid in _clients:
            _clients[request.sid]['registered'] = True

        emit('registration_success', {'status': 'ok', 'role': client_type})

    def on_client_message(self, data):
        """Text message from the user."""
        if not isinstance(data, dict):
            logger.warning(f'[/message] Unexpected client_message format: {type(data)}')
            return

        text = data.get('text', '').strip()
        if text:
            logger.info(f'[/message] Text received from {request.sid}: "{text}"')
            emit('client_message', {'text': text, 'sender': 'client'}, broadcast=True)
            state_machine.on_text_message(text, request.sid)
        else:
            logger.warning('[/message] Empty text message received')
