"""
state_machine.py

Simplified state machine for text-only chat interface.

Flow:
    user sends text → processing_query → emit robot_message → idle
"""

import concurrent.futures
import logging

from robot_context import robot_context

logger = logging.getLogger('StateMachine')

QUERY_TIMEOUT = 30  # seconds

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

_socketio = None
_server = None


def init(socketio_instance, server_module):
    """Inject dependencies — called once from app.py."""
    global _socketio, _server
    _socketio = socketio_instance
    _server = server_module
    logger.info('StateMachine initialized')


def on_text_message(text: str, sid: str):
    """User sent a text message — submit to LLM pipeline."""
    logger.info(f'Text message from {sid}: "{text}"')

    if robot_context.state == 'processing_query':
        logger.warning('Already processing a query, ignoring')
        return

    robot_context.state = 'processing_query'
    _emit_state_update()
    _executor.submit(_process_text_query, text, sid)


def _process_text_query(text: str, sid: str):
    """LLM pipeline for text input."""
    try:
        request = _server.Request(text=text)

        future = _executor.submit(_server.query, request)
        response = future.result(timeout=QUERY_TIMEOUT)

        if response is None:
            logger.warning('Empty response from server')
            _emit_error(sid)
            return

        _handle_response(response, sid)

    except concurrent.futures.TimeoutError:
        logger.error('Timeout processing text query')
        _emit_error(sid)
    except Exception as e:
        logger.error(f'Error processing text query: {e}', exc_info=True)
        _emit_error(sid)


def _handle_response(response, sid):
    """Emit robot_message to frontend and return to idle."""
    message = {
        'text': response.text or '',
        'state': response.robot_mood or 'neutral',
    }

    robot_context.state = 'idle'
    _emit_robot_message(message, sid)
    _emit_state_update()

    logger.info(f'Response emitted: mood={response.robot_mood}')


def _emit_robot_message(message: dict, sid=None):
    if _socketio is None:
        return
    if sid:
        _socketio.emit('robot_message', message, to=sid, namespace='/message')
    else:
        _socketio.emit('robot_message', message, namespace='/message')


def _emit_state_update():
    if _socketio is None:
        return
    _socketio.emit(
        'state_update',
        {'state': robot_context.state},
        namespace='/message'
    )


def _emit_error(sid=None):
    robot_context.state = 'idle'
    _emit_state_update()
    if sid and _socketio:
        _socketio.emit(
            'robot_message',
            {'text': 'Lo siento, ha ocurrido un error. Por favor, inténtalo de nuevo.', 'state': 'neutral'},
            to=sid,
            namespace='/message'
        )
