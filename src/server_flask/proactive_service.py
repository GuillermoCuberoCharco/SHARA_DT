"""
proactive_service.py

ProactiveService adapted from the physical robot.

Original: driven by hardware sensors (PresenceDetector, Wakeface, LEDs).
This version: driven by WebSocket events from the frontend
(user_detected, user_lost, face_idle_timeout).

Proactive questions supported:
    - how_are_you  : triggered when a known user is detected or has been
                     present for a while without interaction.
    - who_are_you  : triggered when an unknown user is detected.

The callback receives ('ask_how_are_you', params) or ('ask_who_are_you', params)
and is handled by the state machine in state_machine.py.
"""

import logging
import threading
from datetime import datetime

logger = logging.getLogger('ProactiveService')


class ProactiveService:
    """
    Tracks sensor/event state and decides when to trigger proactive questions.

    Replaces hardware sensor callbacks with WebSocket event calls:
        update('sensor', 'presence')              ← user present, not identified
        update('sensor', 'close_face_recognized', {'username': name})
        update('sensor', 'unknown_face')
        update('confirm', 'how_are_you', ...)
        update('confirm', 'who_are_you')
    """

    # How long (seconds) a user must be present before a proactive greeting
    PRESENCE_TIMEOUT = 8
    # Cooldown (seconds) between proactive questions for the same user
    COOLDOWN = 120

    def __init__(self, callback):
        self.callback = callback
        self._lock = threading.Lock()

        # Internal state
        self._presence_timer = None
        self._last_asked: dict = {}
        self._pending_confirmation: str = None

        logger.info('ProactiveService ready')

    # ── Public API (called from socket handlers) ──────────────────────────────

    def update(self, event_type: str, event: str, args: dict = None):
        """
        Process a sensor or confirmation event.

        Args:
            event_type: 'sensor' | 'confirm'
            event:      event name
            args:       optional extra data
        """
        args = args or {}
        logger.debug(f'ProactiveService.update({event_type}, {event}, {args})')

        if event_type == 'sensor':
            self._handle_sensor(event, args)
        elif event_type == 'confirm':
            self._handle_confirm(event, args)

    def cancel_timers(self):
        """Cancel all pending timers (call on user lost or shutdown)."""
        with self._lock:
            if self._presence_timer:
                self._presence_timer.cancel()
                self._presence_timer = None
        logger.debug('ProactiveService timers cancelled')

    # ── Internal sensor handling ──────────────────────────────────────────────

    def _handle_sensor(self, event: str, args: dict):
        if event == 'presence':
            self._start_presence_timer()

        elif event == 'close_face_recognized':
            username = args.get('username')
            self._cancel_presence_timer()

            if username and self._can_ask(username):
                self._fire('ask_how_are_you', {
                    'type': 'recognized',
                    'username': username
                })

        elif event == 'unknown_face':
            self._cancel_presence_timer()
            if self._can_ask(None):
                self._fire('ask_who_are_you', {})

    def _handle_confirm(self, event: str, args: dict):
        """Called after the robot has successfully handled a proactive question."""
        username = args.get('username')
        key = username or '__unknown__'

        with self._lock:
            self._last_asked[key] = datetime.now()
            self._pending_confirmation = None

        logger.info(f'Proactive question confirmed for {key}')

    # ── Timer helpers ─────────────────────────────────────────────────────────

    def _start_presence_timer(self):
        with self._lock:
            if self._presence_timer is not None:
                return
            self._presence_timer = threading.Timer(
                self.PRESENCE_TIMEOUT, self._on_presence_timeout
            )
            self._presence_timer.daemon = True
            self._presence_timer.start()
        logger.debug(f'Presence timer started ({self.PRESENCE_TIMEOUT}s)')

    def _cancel_presence_timer(self):
        with self._lock:
            if self._presence_timer:
                self._presence_timer.cancel()
                self._presence_timer = None

    def _on_presence_timeout(self):
        with self._lock:
            self._presence_timer = None
        logger.info('Presence timeout — firing ask_who_are_you')
        if self._can_ask(None):
            self._fire('ask_who_are_you', {})

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _can_ask(self, username) -> bool:
        """Returns True if enough time has passed since the last proactive question."""
        key = username or '__unknown__'
        with self._lock:
            last = self._last_asked.get(key)
        if last is None:
            return True
        elapsed = (datetime.now() - last).total_seconds()
        return elapsed >= self.COOLDOWN

    def _fire(self, event: str, params: dict):
        logger.info(f'Firing proactive event: {event} — {params}')
        try:
            self.callback(event, params)
        except Exception as e:
            logger.error(f'Error in proactive callback: {e}')