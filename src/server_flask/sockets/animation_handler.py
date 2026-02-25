"""
sockets/animation_handler.py

Socket.IO namespace /animation.

Bridge between the Python Eyes service (sender) and the web client (receiver).

Client types:
    eyes  — Python EyeSender, sends eye_frame events
    web   — React RobotView, receives eye_frame events

Flow:
    Python Eyes → eye_frame → Server → eye_frame → React RobotView
"""

import logging

from flask_socketio import Namespace, emit
from flask import request

logger = logging.getLogger('AnimationHandler')

# Track connected sockets by type
_eyes_clients: set = set()
_web_clients: set = set()

# Reference to socketio instance for targeted emission
_socketio = None


def init_animation_handler(socketio_instance):
    global _socketio
    _socketio = socketio_instance


class AnimationNamespace(Namespace):

    def on_connect(self):
        logger.info(f'[/animation] Client connected: {request.sid}')

    def on_disconnect(self):
        logger.info(f'[/animation] Client disconnected: {request.sid}')
        _eyes_clients.discard(request.sid)
        _web_clients.discard(request.sid)
        _log_clients()

    def on_register_animation(self, data):
        client_type = data.get('client') if isinstance(data, dict) else str(data)
        logger.info(f'[/animation] Registering {request.sid} as {client_type}')

        if client_type == 'eyes':
            _eyes_clients.add(request.sid)
            emit('registration_success', {'status': 'ok', 'role': 'eyes'})

        elif client_type == 'web':
            _web_clients.add(request.sid)
            emit('registration_success', {'status': 'ok', 'role': 'web'})

        else:
            logger.warning(f'[/animation] Unknown client type: {client_type}')
            emit('registration_error', {'message': 'Unknown client type'})

        _log_clients()

    def on_eye_frame(self, data):
        """
        Received from Python Eyes service.
        Relay to all connected web clients.
        """
        if request.sid not in _eyes_clients:
            logger.warning(f'[/animation] eye_frame from non-eyes client: {request.sid}')
            return

        if not data or not data.get('frame'):
            logger.warning('[/animation] eye_frame received without frame data')
            return

        if _socketio is None:
            return

        # Forward to all registered web clients
        for web_sid in list(_web_clients):
            _socketio.emit('eye_frame', {'frame': data['frame']}, to=web_sid, namespace='/animation')


def _log_clients():
    logger.debug(f'[/animation] Connected — eyes: {len(_eyes_clients)}, web: {len(_web_clients)}')