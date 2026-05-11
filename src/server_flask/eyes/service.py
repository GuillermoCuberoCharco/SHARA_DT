"""
eyes/service.py

Minimal eyes service for ViSHARA web deployment.
All rendering, interpolation and blink logic runs on the React frontend.
This module emits set_face events on the shared /message namespace.
"""

import logging

logger = logging.getLogger('Eyes')


class Eyes:

    def __init__(self, socketio_instance=None, **kwargs):
        # **kwargs absorbs legacy params (faces_dir, sc_width, sc_height, etc.)
        self.socketio = socketio_instance
        logger.info('Eyes ready (frontend rendering mode)')

    def set(self, face: str, sid: str = None, session_id: str = None):
        if not self.socketio:
            return

        if not sid:
            logger.debug('set_face without sid skipped: %s', face)
            return

        self.socketio.emit(
            'set_face',
            {'face': face, 'sessionId': session_id},
            to=sid,
            namespace='/message',
        )
        logger.debug('set_face -> %s (sid=%s)', face, sid)

    def start(self): pass
    def stop(self):  pass
