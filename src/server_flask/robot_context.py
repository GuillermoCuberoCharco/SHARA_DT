"""Runtime state owned by the Socket.IO event loop, one instance per connection."""
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class RobotContext:
    sid: str
    login_username: str
    face_session_id: str = None
    username: str = None
    needs_identification: bool = False
    proactive_question: str = ''
    state: str = 'idle'
    turn_id: str = field(default_factory=lambda: uuid4().hex)
    protocol: int = 1
    timer: object = None
    stream: object = None
    response: object = None
    current_tts_message_id: str = None
    presence_check: str = None
    mic_ready: bool = False
    greeting: str = ''
