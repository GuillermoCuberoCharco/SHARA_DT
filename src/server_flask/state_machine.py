"""
state_machine.py

State machine adapted from the physical robot's main.py.

Hardware events → WebSocket events mapping:
    mic start_recording       → audio_stream_start  (from useAudioRecorder)
    mic audio chunks          → audio_chunk         (PCM LINEAR16 via AudioWorklet)
    mic stop_recording        → audio_stream_end
    speaker finish_speak      → tts_complete        (from frontend)
    wakeface face_listen      → user_detected       (from FaceDetection.jsx)
    wakeface face_not_listen  → user_lost

Batch STT pipeline:
    1. audio_stream_start → on_audio_stream_start(sid)
       → state = 'recording'
    2. audio_chunk events → message_handler appends bytes to buffer
    3. audio_stream_end  → message_handler collects buffer → on_audio_stream_end(audio_bytes, sid)
       → _executor.submit(_process_audio_stream_end, audio_bytes, sid)
    4. _process_audio_stream_end:
       a. server.query(audio_bytes) → STT [Google recognize, unary] + LLM + TTS
       b. _handle_response → emit robot_message

Note: batch STT (unary gRPC) is used instead of streaming_recognize to avoid
gevent hub starvation. After monkey.patch_all(), ThreadPoolExecutor workers run
as greenlets; gRPC's streaming C-threads calling back into a gevent queue can
block the hub. A unary gRPC call releases the GIL cleanly during I/O.
"""

import base64
import concurrent.futures
import logging
import gevent

from robot_context import robot_context
from proactive_service import ProactiveService
from services.camera_service import record_face_for_session

logger = logging.getLogger('StateMachine')

SERVER_QUERY_TIMEOUT = 20  # seconds

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

_socketio = None
_server = None
_eyes = None
_proactive: ProactiveService = None


def init(socketio_instance, server_module, eyes_instance, proactive_instance):
    """Inject dependencies — called once from app.py."""
    global _socketio, _server, _eyes, _proactive
    _socketio = socketio_instance
    _server = server_module
    _eyes = eyes_instance
    _proactive = proactive_instance
    logger.info('StateMachine initialized')


def _load_conversation_history_for(username):
    if _server is None:
        return

    try:
        _server.load_conversation_db(username)
    except Exception as e:
        logger.warning(f'Could not load conversation history: {e}')


def _persist_current_conversation(username):
    if _server is None:
        return

    try:
        _server.dump_conversation_db(username)
    except Exception as e:
        logger.warning(f'Could not persist conversation history: {e}')


# ── Proactive callback ────────────────────────────────────────────────────────

def proactive_event_handler(event: str, params: dict = None):
    params = params or {}
    logger.info(f'Proactive event: {event} — {params}')

    if event == 'ask_how_are_you':
        gevent.spawn(
            process_transition,
            'proactive2processingquery',
            {'question': 'how_are_you', **params}
        )
    elif event == 'ask_who_are_you':
        gevent.spawn(
            process_transition,
            'proactive2processingquery',
            {'question': 'who_are_you'}
        )


# ── WebSocket entry points (called from message_handler.py) ──────────────────

def on_user_detected(user_data: dict):
    """Face detected by FaceDetection.jsx — replaces wf_event_handler 'face_listen'."""
    username = user_data.get('userName')
    face_session_id = user_data.get('sessionId')
    needs_identification = bool(user_data.get('needsIdentification', False))
    is_new_user = user_data.get('isNewUser', True)
    previous_username = robot_context.username

    logger.info(
        f'User detected: session_id={face_session_id}, username={username}, '
        f'needs_identification={needs_identification}, new={is_new_user}, state={robot_context.state}'
    )

    robot_context.face_session_id = face_session_id
    robot_context.needs_identification = needs_identification

    is_known_user = not needs_identification and username not in (None, '', 'unknown')

    if is_known_user:
        if previous_username and previous_username != username:
            _persist_current_conversation(previous_username)
        if previous_username != username:
            _load_conversation_history_for(username)
        robot_context.username = username
        _proactive.update('sensor', 'close_face_recognized', {'username': username})
    else:
        if previous_username:
            _persist_current_conversation(previous_username)
        robot_context.username = None
        _proactive.update('sensor', 'unknown_face')

    if robot_context.state == 'idle_presence':
        gevent.spawn(process_transition, 'idle_presence2listening', {})
    elif robot_context.state == 'idle':
        gevent.spawn(process_transition, 'idle2idle_presence', {})
        gevent.spawn(process_transition, 'idle_presence2listening', {})


def on_user_lost(user_data: dict):
    """Face lost — replaces wf_event_handler 'face_not_listen'."""
    logger.info(f'User lost, state={robot_context.state}')
    _persist_current_conversation(robot_context.username)
    robot_context.face_session_id = None
    robot_context.username = None
    robot_context.needs_identification = False
    _proactive.cancel_timers()

    if robot_context.state == 'listening':
        gevent.spawn(process_transition, 'listening2idle_presence', {})


def on_audio_stream_start(sid: str):
    """
    PCM LINEAR16 stream started from AudioWorklet.
    Just transitions to 'recording' state; actual STT runs on stream_end.
    """
    logger.info(f'Audio stream start from {sid}, state={robot_context.state}')

    if robot_context.state not in ('listening', 'idle_presence', 'idle'):
        logger.warning(f'audio_stream_start in unexpected state: {robot_context.state} — ignoring')
        return

    robot_context.state = 'recording'
    _emit_state_update()


def on_audio_stream_end(audio_bytes: bytes, sid: str):
    """
    PCM stream ended with all collected audio.
    Submits batch STT → LLM → TTS pipeline.

    Batch STT (clientSTT.recognize) is a unary gRPC call: releases the GIL
    during its single network round-trip, so the gevent hub stays responsive.
    This avoids the gRPC-streaming / gevent incompatibility that caused
    transport close errors with the previous streaming pipeline.
    """
    logger.info(f'Audio stream end from {sid}, received {len(audio_bytes)} bytes')
    _executor.submit(_process_audio_stream_end, audio_bytes, sid)


def on_audio_message(audio_b64: str, sid: str):
    """
    Legacy: full audio blob (base64 webm/opus) — used when AudioWorklet unavailable.
    Equivalent to the old on_audio_message path.
    """
    logger.info(f'Legacy audio blob from {sid}, state={robot_context.state}')

    if robot_context.state not in ('listening', 'idle_presence', 'idle'):
        logger.warning(f'Audio received in unexpected state: {robot_context.state}')
        return

    robot_context.state = 'recording'
    _emit_state_update()
    _executor.submit(_process_audio_query, audio_b64, sid)


def on_text_message(text: str, sid: str):
    """Text typed in chat — bypasses STT."""
    logger.info(f'Text message from {sid}: "{text}"')

    if robot_context.state == 'processing_query':
        logger.warning('Already processing a query, ignoring')
        return

    robot_context.state = 'processing_query'
    _emit_state_update()
    _executor.submit(_process_text_query, text, sid)


def on_tts_complete(sid: str):
    """Frontend finished playing TTS audio."""
    logger.info(f'TTS complete from {sid}, continue={robot_context.continue_conversation}')

    if robot_context.continue_conversation:
        gevent.spawn(process_transition, 'speaking2listening', {})
    else:
        gevent.spawn(process_transition, 'speaking2idle_presence', {})


# ── Core state transitions ────────────────────────────────────────────────────

def process_transition(transition: str, params: dict = None):
    params = params or {}
    current = robot_context.state
    logger.info(f'Transition: {transition} | State: {current}')

    try:
        if transition == 'idle2idle_presence' and current == 'idle':
            robot_context.state = 'idle_presence'
            _emit_state_update()

        elif transition == 'idle_presence2idle' and current == 'idle_presence':
            robot_context.state = 'idle'
            _emit_state_update()

        elif transition == 'idle_presence2listening' and current == 'idle_presence':
            robot_context.state = 'listening'
            _emit_state_update()

        elif transition == 'listening2idle_presence' and current == 'listening':
            robot_context.state = 'idle_presence'
            _emit_state_update()

        elif transition == 'speaking2listening' and current == 'speaking':
            robot_context.state = 'listening'
            _emit_state_update()

        elif transition == 'speaking2idle_presence' and current == 'speaking':
            robot_context.state = 'idle_presence'
            _emit_state_update()

        elif transition == 'proactive2processingquery':
            _handle_proactive_query(params)

        else:
            logger.debug(f'Transition {transition} discarded (state={current})')

    except Exception as e:
        logger.error(f'Error in transition {transition}: {e}', exc_info=True)


# ── Query pipelines ───────────────────────────────────────────────────────────

def _process_audio_stream_end(audio_bytes: bytes, sid: str):
    """
    Batch STT → LLM → TTS pipeline for collected PCM audio.

    Replaces the old _process_streaming_query. Uses clientSTT.recognize()
    (unary gRPC) instead of streaming_recognize() (long-lived gRPC stream).
    A unary call releases the GIL during I/O and does not require gRPC C-threads
    to call back into the Python generator, avoiding gevent hub starvation.
    """
    try:
        robot_context.state = 'processing_query'
        _emit_state_update()

        if not audio_bytes:
            logger.warning('Empty audio buffer — nothing to transcribe')
            robot_context.state = 'idle_presence'
            _emit_state_update()
            if _socketio and sid:
                _socketio.emit('audio_empty', {}, to=sid, namespace='/message')
            return

        # Batch STT + LLM + TTS in one call
        request = _server.Request(
            audio=audio_bytes,
            username=robot_context.username,
            proactive_question=robot_context.proactive_question,
        )
        response = _server.query(request)

        if response is None:
            logger.warning('Empty transcription or response — returning to idle')
            robot_context.state = 'idle_presence'
            _emit_state_update()
            if _socketio and sid:
                _socketio.emit('audio_empty', {}, to=sid, namespace='/message')
            return

        # Echo transcription so front-end can display what was heard
        if _socketio and response.request.text:
            _socketio.emit(
                'transcription_result',
                {'text': response.request.text},
                to=sid,
                namespace='/message'
            )

        _handle_response(response, sid)

    except Exception as e:
        logger.error(f'Error in audio stream end processing: {e}', exc_info=True)
        _emit_error(sid)


def _process_audio_query(audio_b64: str, sid: str):
    """STT → LLM → TTS pipeline for audio input."""
    try:
        robot_context.state = 'processing_query'
        _emit_state_update()

        audio_bytes = base64.b64decode(audio_b64)
        request = _server.Request(
            audio=audio_bytes,
            username=robot_context.username,
            proactive_question=robot_context.proactive_question,
        )

        future = _executor.submit(_server.query, request)
        response = future.result(timeout=SERVER_QUERY_TIMEOUT)

        if response is None:
            logger.warning('Empty transcription or response — returning to listening silently')
            robot_context.state = 'listening'
            _emit_state_update()
            return

        _handle_response(response, sid)

    except concurrent.futures.TimeoutError:
        logger.error('Timeout in audio query processing')
        _emit_error(sid)
    except Exception as e:
        logger.error(f'Error processing audio query: {e}', exc_info=True)
        _emit_error(sid)


def _process_text_query(text: str, sid: str):
    """LLM → TTS pipeline for text input (STT already done by browser)."""
    try:
        request = _server.Request(
            text=text,
            username=robot_context.username,
            proactive_question=robot_context.proactive_question,
        )

        future = _executor.submit(_server.query_with_text, request)
        response = future.result(timeout=SERVER_QUERY_TIMEOUT)

        if response is None:
            logger.warning('Empty response from server.query_with_text')
            _emit_error(sid)
            return

        _handle_response(response, sid)

    except concurrent.futures.TimeoutError:
        logger.error('Timeout in text query processing')
        _emit_error(sid)
    except Exception as e:
        logger.error(f'Error processing text query: {e}', exc_info=True)
        _emit_error(sid)


def _handle_proactive_query(params: dict):
    """Proactive question pipeline — no STT, direct LLM → TTS."""
    question = params.get('question')
    username = params.get('username', robot_context.username)

    logger.info(f'Proactive query: {question} for {username}')

    try:
        robot_context.state = 'processing_query'
        _emit_state_update()

        request = _server.Request(
            username=username,
            proactive_question=question or '',
        )

        future = _executor.submit(_server.proactive_query, request)
        response = future.result(timeout=SERVER_QUERY_TIMEOUT)

        if response is None:
            logger.warning('Empty response from proactive_query')
            robot_context.state = 'idle_presence'
            _emit_state_update()
            return

        next_proactive_question = 'who_are_you_response' if question == 'who_are_you' else ''

        _handle_response(response, sid=None, next_proactive_question=next_proactive_question)
        _proactive.update('confirm', question, {'username': username})

    except concurrent.futures.TimeoutError:
        logger.error('Timeout in proactive query')
        robot_context.state = 'idle_presence'
        _emit_state_update()
    except Exception as e:
        logger.error(f'Error in proactive query: {e}', exc_info=True)
        robot_context.state = 'idle_presence'
        _emit_state_update()


def _handle_response(response, sid, next_proactive_question: str = ''):
    """
    Common response handler — updates context, sets eye state,
    emits robot_message to frontend.
    """
    robot_context.state = 'speaking'
    robot_context.continue_conversation = response.continue_conversation
    robot_context.proactive_question = next_proactive_question or ''

    if response.action == 'record_face':
        previous_username = robot_context.username
        if robot_context.face_session_id:
            try:
                update_result = record_face_for_session(robot_context.face_session_id, response.username)
                if not update_result.get('success'):
                    logger.warning(f"Could not persist recorded face: {update_result.get('error')}")
            except Exception as e:
                logger.warning(f'Could not record face in embedding database: {e}')
        else:
            logger.warning('record_face action received without current face_session_id')

        robot_context.username = response.username
        robot_context.face_session_id = None
        robot_context.needs_identification = False

        if previous_username != response.username:
            _load_conversation_history_for(response.username)

    elif response.action == 'set_username':
        previous_username = robot_context.username
        robot_context.username = response.username
        robot_context.needs_identification = False

        if previous_username != response.username:
            _load_conversation_history_for(response.username)

    elif response.username:
        previous_username = robot_context.username
        robot_context.username = response.username
        robot_context.needs_identification = False
        if previous_username != response.username:
            _load_conversation_history_for(response.username)

    if _eyes and response.robot_mood:
        try:
            _eyes.set(response.robot_mood)
        except Exception as e:
            logger.warning(f'Could not set eye state: {e}')

    audio_b64 = base64.b64encode(response.audio).decode('utf-8') if response.audio else None

    message = {
        'text': response.text or '',
        'state': response.robot_mood or 'neutral',
        'audio': audio_b64,
        'continue': response.continue_conversation,
    }

    _emit_robot_message(message, sid)
    _emit_state_update()

    logger.info(f'Response emitted: mood={response.robot_mood}, continue={response.continue_conversation}')


# ── Emission helpers ──────────────────────────────────────────────────────────

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
    robot_context.state = 'idle_presence'
    _emit_state_update()
    if sid and _socketio:
        _socketio.emit(
            'robot_message',
            {'text': 'Lo siento, ha ocurrido un error. Por favor, inténtalo de nuevo.', 'state': 'neutral'},
            to=sid,
            namespace='/message'
        )
