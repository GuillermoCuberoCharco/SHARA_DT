"""
state_machine.py

Per-user state machine for text-only chat interface.

Each user has independent processing state — multiple users can query
the LLM simultaneously without blocking each other.

Flow:
    user sends text → mark user as processing → LLM call → emit robot_message → mark idle
"""

import concurrent.futures
import logging
import threading

logger = logging.getLogger('StateMachine')

QUERY_TIMEOUT = 30  # seconds

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

_socketio = None
_server = None

# Per-user processing state: set of user_ids currently waiting for an LLM response
_processing_users: set[str] = set()
_lock = threading.Lock()


def init(socketio_instance, server_module):
    """Inject dependencies — called once from app.py."""
    global _socketio, _server
    _socketio = socketio_instance
    _server = server_module
    logger.info('StateMachine initialized')


def on_text_message(text: str, sid: str, user_id: str):
    """User sent a text message — submit to LLM pipeline."""
    logger.info(f'Text message from {user_id} ({sid}): "{text}"')

    with _lock:
        if user_id in _processing_users:
            logger.warning(f'User {user_id} already processing a query, ignoring')
            return
        _processing_users.add(user_id)

    _emit_state_update('processing_query', sid)
    _executor.submit(_process_text_query, text, sid, user_id)


def _process_text_query(text: str, sid: str, user_id: str):
    """LLM pipeline for text input."""
    try:
        request = _server.Request(text=text, user_id=user_id)

        future = _executor.submit(_server.query, request)
        response = future.result(timeout=QUERY_TIMEOUT)

        if response is None:
            logger.warning(f'Empty response for user {user_id}')
            _emit_error(sid, user_id)
            return

        _handle_response(response, sid, user_id)

    except concurrent.futures.TimeoutError:
        logger.error(f'Timeout processing query for user {user_id}')
        _emit_error(sid, user_id)
    except Exception as e:
        logger.error(f'Error processing query for {user_id}: {e}', exc_info=True)
        _emit_error(sid, user_id)


def _handle_response(response, sid: str, user_id: str):
    """Emit robot_message to the requesting client and mark user as idle."""
    message = {
        'text': response.text or '',
        'state': response.robot_mood or 'neutral',
    }

    with _lock:
        _processing_users.discard(user_id)

    _emit_robot_message(message, sid)
    _emit_state_update('idle', sid)

    logger.info(f'Response emitted to {user_id}: mood={response.robot_mood}')


def _emit_robot_message(message: dict, sid: str):
    if _socketio is None:
        return
    _socketio.emit('robot_message', message, to=sid, namespace='/message')


def _emit_state_update(state: str, sid: str):
    if _socketio is None:
        return
    _socketio.emit('state_update', {'state': state}, to=sid, namespace='/message')


def _emit_error(sid: str, user_id: str):
    with _lock:
        _processing_users.discard(user_id)
    _emit_state_update('idle', sid)
    if sid and _socketio:
        _socketio.emit(
            'robot_message',
            {'text': 'Lo siento, ha ocurrido un error. Por favor, inténtalo de nuevo.', 'state': 'neutral'},
            to=sid,
            namespace='/message',
        )


def get_active_users_count() -> int:
    """Return number of users currently waiting for an LLM response."""
    with _lock:
        return len(_processing_users)
