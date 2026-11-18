"""Cloud operations used independently by each stage of a conversation turn."""
from dataclasses import dataclass

from .google_api import TTS_AUDIO_MIME_TYPE, speech_to_text, streaming_speech_to_text, text_to_speech
from .openai_api import generate_response, persist_exchange

@dataclass
class Request:
    audio: bytes = b''
    text: str = None
    username: str = None
    login_name: str = None
    session_id: str = None
    turn_id: str = None
    proactive_question: str = ''

@dataclass
class Response:
    request: Request
    audio: bytes
    action: str
    username: str
    continue_conversation: bool
    robot_mood: str = 'neutral'
    text: str = None
    audio_mime_type: str = TTS_AUDIO_MIME_TYPE
    exchange: list = None


def query_with_text(request: Request):
    context = dict(username=request.username, proactive_question=request.proactive_question)
    text, result = generate_response(request.text or '', context, history_key=request.login_name,
                                     session_id=request.session_id, turn_id=request.turn_id)
    if not text:
        raise ValueError('Empty model response')
    return Response(
        request=request, text=text, audio=None,
        action=result.get('action'), username=result.get('username'),
        continue_conversation=result['continue'], robot_mood=result['robot_mood'],
        exchange=result['exchange'],
    )


def streaming_stt(chunks):
    return streaming_speech_to_text(chunks)
