"""
sockets/video_handler.py

Socket.IO namespace /video.

Receives video frames from the browser (WebSocketVideoComponent)
and rebroadcasts them. In the new architecture without a wizard operator,
the frames are still captured (for FaceDetection) but not forwarded
to any operator interface.

Events received:
    register        — web client registration
    video_frame     — {type, frame} JPEG base64 from browser

Events emitted:
    registration_success
    (video frames are not forwarded in this version — no operator)
"""

import logging

from flask_socketio import Namespace, emit
from flask import request

logger = logging.getLogger('VideoHandler')

_clients: dict = {}


class VideoNamespace(Namespace):

    def on_connect(self):
        logger.info(f'[/video] Client connected: {request.sid}')
        _clients[request.sid] = {'registered': False}

    def on_disconnect(self):
        logger.info(f'[/video] Client disconnected: {request.sid}')
        _clients.pop(request.sid, None)

    def on_register(self, data):
        client_type = data.get('client', 'web') if isinstance(data, dict) else str(data)
        logger.info(f'[/video] Registering {request.sid} as {client_type}')
        _clients[request.sid]['registered'] = True
        emit('registration_success', {'status': 'ok', 'role': client_type})

    def on_video_frame(self, data):
        """
        Receives video frame from browser.
        In this version (no wizard operator) frames are acknowledged but
        not rebroadcast. FaceDetection runs entirely in the browser.
        """
        # No-op: frame received and discarded.
        pass