"""
state_machine.py

Per-user state machine for the authenticated chat interface.

Each user has independent processing state, so multiple users can query
the LLM simultaneously without blocking each other.

Flow:
    user sends text/audio -> mark user as processing -> STT/LLM call
    -> optional TTS -> emit robot_message -> mark idle
"""

import base64
import concurrent.futures
import logging
import threading

logger = logging.getLogger('StateMachine')

QUERY_TIMEOUT = 30  # seconds
TTS_TIMEOUT = 20    # seconds

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
_query_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

_socketio = None
_server = None

_processing_users: set[str] = set()
_tts_preferences: dict[str, bool] = {}
_lock = threading.Lock()


def _processing_key(user_id: str, subject_code: str) -> str:
    return f"{user_id}::{subject_code or '-'}"


def init(socketio_instance, server_module):
    """Inject dependencies. Called once from app.py."""
    global _socketio, _server
    _socketio = socketio_instance
    _server = server_module
    logger.info('StateMachine initialized')


def register_session(sid: str, tts_enabled: bool = True):
    with _lock:
        _tts_preferences[sid] = bool(tts_enabled)


def unregister_session(sid: str):
    with _lock:
        _tts_preferences.pop(sid, None)


def set_tts_enabled(sid: str, enabled: bool):
    with _lock:
        _tts_preferences[sid] = bool(enabled)


def on_text_message(
    text: str,
    sid: str,
    user_id: str,
    user_role: str = 'student',
    subject_code: str = '',
):
    """User sent a text message."""
    logger.info('Text message from %s [%s] (%s): "%s"', user_id, subject_code, sid, text)
    processing_key = _processing_key(user_id, subject_code)

    with _lock:
        if processing_key in _processing_users:
            logger.warning('User %s [%s] already processing a query, ignoring', user_id, subject_code)
            return
        _processing_users.add(processing_key)

    _emit_state_update('processing_query', sid)
    _executor.submit(_process_text_query, text, sid, user_id, user_role, subject_code)


def on_audio_stream_start(
    sid: str,
    user_id: str,
    user_role: str = 'student',
    subject_code: str = '',
) -> bool:
    """The browser started streaming PCM audio for this user."""
    processing_key = _processing_key(user_id, subject_code)
    with _lock:
        if processing_key in _processing_users:
            logger.warning('User %s [%s] already processing a query, ignoring audio start', user_id, subject_code)
            return False

    _emit_state_update('recording', sid)
    return True


def on_audio_stream_end(
    audio_bytes: bytes,
    sid: str,
    user_id: str,
    user_role: str = 'student',
    subject_code: str = '',
):
    """User finished sending PCM audio."""
    logger.info('Audio stream end from %s [%s] (%s bytes)', user_id, subject_code, len(audio_bytes))
    processing_key = _processing_key(user_id, subject_code)

    with _lock:
        if processing_key in _processing_users:
            logger.warning('User %s [%s] already processing a query, ignoring audio end', user_id, subject_code)
            return
        _processing_users.add(processing_key)

    _emit_state_update('processing_query', sid)
    _executor.submit(_process_audio_query, audio_bytes, sid, user_id, user_role, subject_code)


def _process_text_query(text: str, sid: str, user_id: str, user_role: str, subject_code: str):
    try:
        request = _server.Request(text=text, user_id=user_id, user_role=user_role, subject_code=subject_code)
        future = _query_executor.submit(_server.query, request)
        response = future.result(timeout=QUERY_TIMEOUT)

        if response is None:
            logger.warning('Empty response for user %s', user_id)
            _emit_error(sid, user_id, subject_code)
            return

        _handle_response(response, sid, user_id, subject_code)

    except concurrent.futures.TimeoutError:
        logger.error('Timeout processing text query for %s [%s]', user_id, subject_code)
        _emit_error(sid, user_id, subject_code)
    except Exception as exc:
        logger.error('Error processing text query for %s [%s]: %s', user_id, subject_code, exc, exc_info=True)
        _emit_error(sid, user_id, subject_code)


def _process_audio_query(audio_bytes: bytes, sid: str, user_id: str, user_role: str, subject_code: str):
    try:
        if not audio_bytes:
            logger.warning('Empty audio payload for user %s', user_id)
            _emit_audio_empty(sid, user_id, subject_code)
            return

        request = _server.Request(audio=audio_bytes, user_id=user_id, user_role=user_role, subject_code=subject_code)
        future = _query_executor.submit(_server.query, request)
        response = future.result(timeout=QUERY_TIMEOUT)

        if response is None:
            logger.warning('Empty transcription or response for user %s', user_id)
            _emit_audio_empty(sid, user_id, subject_code)
            return

        if response.request.text:
            _emit_transcription_result(response.request.text, sid)

        _handle_response(response, sid, user_id, subject_code)

    except concurrent.futures.TimeoutError:
        logger.error('Timeout processing audio query for %s [%s]', user_id, subject_code)
        _emit_error(sid, user_id, subject_code)
    except Exception as exc:
        logger.error('Error processing audio query for %s [%s]: %s', user_id, subject_code, exc, exc_info=True)
        _emit_error(sid, user_id, subject_code)


def _handle_response(response, sid: str, user_id: str, subject_code: str):
    audio_b64 = None

    if _is_tts_enabled(sid):
        try:
            future = _query_executor.submit(_server.synthesize_response, response.text)
            audio_bytes = future.result(timeout=TTS_TIMEOUT)
            if audio_bytes:
                audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        except concurrent.futures.TimeoutError:
            logger.error('Timeout synthesizing TTS for %s', user_id)
        except Exception as exc:
            logger.error('Error synthesizing TTS for %s: %s', user_id, exc, exc_info=True)

    message = {
        'text': response.text or '',
        'state': response.robot_mood or 'neutral',
    }
    if audio_b64:
        message['audio'] = audio_b64

    with _lock:
        _processing_users.discard(_processing_key(user_id, subject_code))

    _emit_robot_message(message, sid)
    _emit_state_update('idle', sid)

    logger.info('Response emitted to %s [%s]: mood=%s', user_id, subject_code, response.robot_mood)


def _emit_robot_message(message: dict, sid: str):
    if _socketio is None:
        return
    _socketio.emit('robot_message', message, to=sid, namespace='/message')


def _emit_state_update(state: str, sid: str):
    if _socketio is None:
        return
    _socketio.emit('state_update', {'state': state}, to=sid, namespace='/message')


def _emit_error(sid: str, user_id: str, subject_code: str):
    with _lock:
        _processing_users.discard(_processing_key(user_id, subject_code))
    _emit_state_update('idle', sid)
    if sid and _socketio:
        _socketio.emit(
            'robot_message',
            {
                'text': 'Lo siento, ha ocurrido un error. Por favor, intentalo de nuevo.',
                'state': 'neutral',
            },
            to=sid,
            namespace='/message',
        )


def _emit_audio_empty(sid: str, user_id: str, subject_code: str):
    with _lock:
        _processing_users.discard(_processing_key(user_id, subject_code))
    _emit_state_update('idle', sid)
    if sid and _socketio:
        _socketio.emit(
            'robot_message',
            {
                'text': 'No he podido transcribir el audio. Prueba a grabarlo otra vez.',
                'state': 'neutral',
            },
            to=sid,
            namespace='/message',
        )


def _emit_transcription_result(text: str, sid: str):
    if not sid or _socketio is None or not text:
        return
    _socketio.emit(
        'transcription_result',
        {'text': text},
        to=sid,
        namespace='/message',
    )


def _is_tts_enabled(sid: str) -> bool:
    with _lock:
        return _tts_preferences.get(sid, True)


def get_active_users_count() -> int:
    """Return number of users currently waiting for an LLM response."""
    with _lock:
        return len(_processing_users)
