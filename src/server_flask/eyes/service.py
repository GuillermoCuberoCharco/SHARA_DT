"""
eyes/service.py

Eyes service — greatly simplified for the ViSHARA web deployment.

The original service rendered frames with OpenCV and streamed PNGs over
WebSocket.  This version delegates ALL rendering to the React frontend:
  - The server only emits { face: <name> } when the expression changes.
  - Interpolation, blink animation, and canvas drawing run client-side.
  - No OpenCV, no NumPy, no base64 encoding, no background render thread.

The public API (set / stop / start) is preserved for compatibility with
state_machine.py and any other callers.
"""

import logging
import random
import time
from pathlib import Path
from threading import Event, Lock, Thread

logger = logging.getLogger('Eyes')

class Eyes:

    def __init__(
        self,
        faces_dir: str = 'files/faces',
        face_cache: str = 'files/face_cache',  # kept for API compatibility, unused here
        sc_width: int = 1080,                  # kept for API compatibility, unused here
        sc_height: int = 1920,                 # kept for API compatibility, unused here
        server_url: str = None,       # kept for API compatibility, unused here
        socketio_instance=None,       # Flask-SocketIO instance for direct emission
    ):

        self.faces_dir = Path(faces_dir)
        self.socketio = socketio_instance

        self.current_face = 'neutral'

        self.stopped = Event()
        self.lock = Lock()

        logger.info('Eyes service ready. Frontend rendering mode')

        self._emit('neutral')

        self.start()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _set(self, face: str):
        """Set face (must be called with self.lock held)."""
        face_path = self.faces_dir / f'{face}.json'
        if not face_path.exists():
            logger.warning(f"Face '{face}' not found, defaulting to 'neutral'")
            face = 'neutral'

        if self.current_face == face:
            return

        self.current_face = face
        self._emit(face)

    def _emit(self, face: str):
        """Broadcast set_face to all /animation clients."""
        if self.socketio is None:
            return
        try:
            self.socketio.emit(
                'set_face',
                {'face': face},
                namespace='/animation',
            )
            logger.debug(f'[Eyes] set_face → {face}')
        except Exception as e:
            logger.error(f'[Eyes] emit error: {e}')

    def _blink_loop(self):
        """
        Mirrors the original blink logic: every 4–7 s, if not already on a
        _closed face, trigger face_closed → face (frontend handles the
        interpolation and timing of each transition).
        """
        while not self.stopped.wait(timeout=random.uniform(4, 7)):
            with self.lock:
                face = self.current_face
                if '_closed' not in face:
                    self._set(f'{face}_closed')
                    # Brief hold before reopening (frontend will interpolate)
                    time.sleep(0.12)
                    self._set(face)

# ── Public Api ────────────────────────────────────────────────────────────────

    def set(self, face: str):
        with self.lock:
            self._set(face)

    def stop(self):
        self.stopped.set()
        if hasattr(self, '_thread'):
            self._thread.join(timeout=5)
        logger.info('Eyes service stopped')

    def start(self):
        self.stopped.clear()
        self._thread = Thread(target=self._blink_loop, daemon=True)
        self._thread.start()
        logger.info('Eyes blink loop started')