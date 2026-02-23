"""
robot_context.py

Global conversation state, equivalent to the robot_context dict in the
physical robot's main.py. Thread-safe access via RobotContext class.

States:
    idle              — no user present
    idle_presence     — user detected but not interacting
    listening         — face detected, waiting for speech
    recording         — speech detected, recording audio
    processing_query  — audio sent, waiting for LLM/TTS response
    speaking          — robot is playing TTS response
"""

import threading


class RobotContext:
    """Thread-safe container for global robot state."""

    VALID_STATES = {
        'idle',
        'idle_presence',
        'listening',
        'recording',
        'processing_query',
        'speaking',
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {
            'state': 'idle',
            'username': None,
            'continue_conversation': False,
            'proactive_question': '',
            'unknown_user_interactions': 0,
        }

    def get(self, key, default=None):
        with self._lock:
            return self._state.get(key, default)

    def set(self, key, value):
        with self._lock:
            self._state[key] = value

    def update(self, updates: dict):
        with self._lock:
            self._state.update(updates)

    def snapshot(self) -> dict:
        """Return a copy of the full state (for logging/debugging)."""
        with self._lock:
            return dict(self._state)

    @property
    def state(self) -> str:
        return self.get('state')

    @state.setter
    def state(self, value: str):
        if value not in self.VALID_STATES:
            raise ValueError(f"Invalid state: {value}. Valid: {self.VALID_STATES}")
        self.set('state', value)

    @property
    def username(self):
        return self.get('username')

    @username.setter
    def username(self, value):
        self.set('username', value)

    @property
    def continue_conversation(self) -> bool:
        return self.get('continue_conversation', False)

    @continue_conversation.setter
    def continue_conversation(self, value: bool):
        self.set('continue_conversation', value)

    @property
    def proactive_question(self) -> str:
        return self.get('proactive_question', '')

    @proactive_question.setter
    def proactive_question(self, value: str):
        self.set('proactive_question', value)


# Singleton instance shared across the application
robot_context = RobotContext()