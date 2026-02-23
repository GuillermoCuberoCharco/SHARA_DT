"""
eyes/service.py

Eyes service adapted for the Flask server.

Changes from original (physical robot):
    - cv2.imshow() replaced by socketio.emit('eye_frame', ...) to /animation namespace
    - cv2.namedWindow / setWindowProperty removed
    - EyeSender (external WebSocket client) not needed — runs in-process
    - socketio_instance injected at construction time

The rendering loop, transition queue, blink logic, and cache remain unchanged.
"""

import base64
import logging
import os
import queue
import random
import time
from pathlib import Path
from threading import Event, Lock, Thread

import cv2

from .draw import draw_face
from .utils import get_face_from_file
from .interpolation import get_in_between_faces


class Eyes:

    def __init__(
        self,
        faces_dir: str = 'files/faces',
        face_cache: str = 'files/face_cache',
        sc_width: int = 1080,
        sc_height: int = 1920,
        server_url: str = None,       # kept for API compatibility, unused here
        socketio_instance=None,       # Flask-SocketIO instance for direct emission
    ):
        self.logger = logging.getLogger('Eyes')
        self.logger.setLevel(logging.DEBUG)

        self.faces_dir = Path(faces_dir)
        self.face_cache = Path(face_cache)
        self.screen_width = sc_width
        self.screen_height = sc_height
        self.socketio = socketio_instance

        # Ensure cache directory exists
        self.face_cache.mkdir(parents=True, exist_ok=True)

        # Transition queue
        self.transition_faces = queue.Queue()

        self.current_face = 'neutral'
        self.current_face_points = get_face_from_file(self.faces_dir / 'neutral.json')
        self.transition_faces.put((self.current_face, self.current_face_points))

        self.stopped = Event()
        self.lock = Lock()

        self.logger.info('Ready')
        self.start()

    # ── State management ──────────────────────────────────────────────────────

    def _set(self, face: str, steps: int = 3):
        if self.current_face == face:
            return

        face_file_path = self.faces_dir / f'{face}.json'
        if not face_file_path.exists():
            self.logger.warning(f"Face '{face}' not found, defaulting to 'neutral'.")
            face = 'neutral'

        target_face = get_face_from_file(self.faces_dir / f'{face}.json')
        in_between_faces = get_in_between_faces(self.current_face_points, target_face, steps)

        for index, face_points in enumerate(in_between_faces):
            self.transition_faces.put(
                (f'{self.current_face}TO{face}_{index + 1}of{steps}', face_points)
            )

        self.transition_faces.put((face, target_face))
        self.logger.info(f'Queued transitions: {self.current_face} → {face}')

        self.current_face_points = target_face
        self.current_face = face

    def set(self, face: str):
        with self.lock:
            self._set(face)

    # ── Rendering loop ────────────────────────────────────────────────────────

    def _run(self):
        next_blink = time.time() + random.randint(4, 7)

        while not self.stopped.is_set():
            try:
                name_transition, new_face = self.transition_faces.get(timeout=0.1)

                # Use cache if available
                face_file = str(self.face_cache / f'{name_transition}.png')
                if os.path.exists(face_file):
                    canvas = cv2.imread(face_file)
                else:
                    canvas = draw_face(new_face, self.screen_width, self.screen_height)
                    cv2.imwrite(face_file, canvas)

                self._emit_frame(canvas)

            except queue.Empty:
                if time.time() > next_blink and '_closed' not in self.current_face:
                    current_face = self.current_face
                    with self.lock:
                        self._set(f'{current_face}_closed', 1)
                        self._set(current_face, 1)
                    next_blink = time.time() + random.randint(4, 7)

    def _emit_frame(self, canvas):
        """Encode canvas as PNG base64 and emit to /animation namespace."""
        if self.socketio is None:
            return

        try:
            success, buffer = cv2.imencode('.png', canvas)
            if not success:
                self.logger.warning('Failed to encode frame as PNG')
                return

            frame_b64 = base64.b64encode(buffer).decode('utf-8')
            self.socketio.emit(
                'eye_frame',
                {'frame': frame_b64},
                namespace='/animation'
            )
        except Exception as e:
            self.logger.error(f'Error emitting eye frame: {e}')

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        self.thread = Thread(target=self._run, daemon=True)
        self.stopped.clear()
        self.thread.start()
        self.logger.info('Eyes service started')

    def stop(self):
        self.stopped.set()
        self.thread.join(timeout=5)
        self.logger.info('Eyes service stopped')