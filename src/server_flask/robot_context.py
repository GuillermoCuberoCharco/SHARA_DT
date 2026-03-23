"""
robot_context.py

Global conversation state. Thread-safe access via RobotContext class.

States:
    idle             — waiting for user input
    processing_query — calling OpenAI API
"""

import threading


class RobotContext:
    """Thread-safe container for global robot state."""

    VALID_STATES = {
        'idle',
        'processing_query',
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {
            'state': 'idle',
        }

    def get(self, key, default=None):
        with self._lock:
            return self._state.get(key, default)

    def set(self, key, value):
        with self._lock:
            self._state[key] = value

    def snapshot(self) -> dict:
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


# Singleton instance shared across the application
robot_context = RobotContext()
