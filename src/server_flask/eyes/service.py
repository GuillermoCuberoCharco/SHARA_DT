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

    def set(self, face: str):
        if self.socketio:
            self.socketio.emit('set_face', {'face': face}, namespace='/message')
            logger.debug(f'set_face → {face}')

    def start(self): pass
    def stop(self):  pass
