"""
state_machine.py

Socket-driven state machine for the SHARA web deployment.

The physical robot has one global conversation state. The web deployment can
have many browser clients connected at the same time, so this module keeps one
RobotContext per Socket.IO sid and emits every user-facing event back to that
sid only.
"""

import base64
import concurrent.futures
import logging
import os
import queue
import re
import threading

import gevent

from auth import get_shara_name, update_shara_name
from proactive_service import ProactiveService
from robot_context import RobotContext, robot_context

logger = logging.getLogger('StateMachine')

SERVER_QUERY_TIMEOUT = float(os.getenv('SERVER_QUERY_TIMEOUT_SECONDS', '45'))  # seconds
AUDIO_STREAM_QUEUE_MAX_CHUNKS = 600
_AUDIO_STREAM_END = object()

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
_query_executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
_stt_executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

_socketio = None
_server = None
_eyes = None
_proactive = None  # Kept for backwards-compatible init signature.

_contexts_lock = threading.RLock()
_audio_streams_lock = threading.RLock()
_session_contexts: dict[str, RobotContext] = {}
_proactive_services: dict[str, ProactiveService] = {}
_audio_streams: dict[str, '_AudioStream'] = {}


class _AudioStream:
    """Live PCM stream feeding Google streaming STT while keeping a batch fallback."""

    def __init__(self):
        self.queue = queue.Queue(maxsize=AUDIO_STREAM_QUEUE_MAX_CHUNKS)
        self.buffer = bytearray()
        self.future = None
        self.closed = False
        self.streaming_transcript = ''
        self.streaming_is_final = False
        self.streaming_silence_detection_time = None
        self.lock = threading.RLock()

    def append(self, audio_bytes: bytes) -> bool:
        if not audio_bytes:
            return False

        with self.lock:
            if self.closed:
                return False
            self.buffer.extend(audio_bytes)

        try:
            self.queue.put_nowait(audio_bytes)
            return True
        except queue.Full:
            logger.warning('Audio stream STT queue full; live chunk dropped but kept for fallback')
            return False

    def snapshot_audio(self) -> bytes:
        with self.lock:
            return bytes(self.buffer)

    def update_streaming_result(
        self,
        transcript: str,
        is_final: bool = False,
        silence_detection_time=None,
    ):
        clean_transcript = (transcript or '').strip()
        if not clean_transcript:
            return

        with self.lock:
            self.streaming_transcript = clean_transcript
            self.streaming_is_final = bool(is_final)
            if silence_detection_time is not None:
                self.streaming_silence_detection_time = silence_detection_time

    def latest_streaming_transcript(self) -> str:
        with self.lock:
            return self.streaming_transcript

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True

        try:
            self.queue.put_nowait(_AUDIO_STREAM_END)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(_AUDIO_STREAM_END)
            except queue.Full:
                logger.warning('Could not signal audio stream end; STT queue stayed full')


def init(socketio_instance, server_module, eyes_instance=None, proactive_instance=None):
    """Inject dependencies, called once from app.py."""
    global _socketio, _server, _eyes, _proactive
    _socketio = socketio_instance
    _server = server_module
    _eyes = eyes_instance
    _proactive = proactive_instance
    logger.info('StateMachine initialized')


def register_session(sid: str):
    """Create the per-client context as soon as the socket connects."""
    if not sid:
        return
    _get_context(sid)
    _get_proactive_service(sid)
    logger.info('Registered runtime session: %s', sid)


def unregister_session(sid: str):
    """Remove all runtime state associated with a disconnected socket."""
    if not sid:
        return

    with _contexts_lock:
        _session_contexts.pop(sid, None)
        proactive = _proactive_services.pop(sid, None)

    if proactive:
        proactive.cancel_timers()

    _discard_audio_stream(sid)

    logger.info('Unregistered runtime session: %s', sid)


def get_active_sessions_count() -> int:
    with _contexts_lock:
        return len(_session_contexts)


def get_session_states() -> dict:
    with _contexts_lock:
        return {
            sid: {
                'state': ctx.state,
                'loginName': ctx.login_username,
                'sessionId': ctx.face_session_id,
            }
            for sid, ctx in _session_contexts.items()
        }


def _get_context(sid: str) -> RobotContext:
    if not sid:
        return robot_context

    with _contexts_lock:
        context = _session_contexts.get(sid)
        if context is None:
            context = RobotContext()
            _session_contexts[sid] = context
        return context


def _get_existing_context(sid: str):
    if not sid:
        return None
    with _contexts_lock:
        return _session_contexts.get(sid)


def _context_items():
    with _contexts_lock:
        return list(_session_contexts.items())


def _get_proactive_service(sid: str):
    if not sid:
        return None

    with _contexts_lock:
        service = _proactive_services.get(sid)
        if service is None:
            service = ProactiveService(
                callback=lambda event, params=None, _sid=sid: proactive_event_handler(
                    event,
                    params,
                    sid=_sid,
                )
            )
            _proactive_services[sid] = service
        return service


def _get_existing_proactive_service(sid: str):
    if not sid:
        return None
    with _contexts_lock:
        return _proactive_services.get(sid)


def _audio_stream_generator(audio_stream: _AudioStream):
    while True:
        chunk = audio_stream.queue.get()
        if chunk is _AUDIO_STREAM_END:
            break
        if chunk:
            yield chunk


def _discard_audio_stream(sid: str):
    if not sid:
        return

    with _audio_streams_lock:
        audio_stream = _audio_streams.pop(sid, None)

    if not audio_stream:
        return

    audio_stream.close()
    if audio_stream.future and not audio_stream.future.done():
        audio_stream.future.cancel()
    logger.debug('Discarded audio stream for sid=%s', sid)


def _start_streaming_stt(audio_stream: _AudioStream, sid: str):
    if _server is None or not hasattr(_server, 'streaming_stt'):
        logger.info('Streaming STT unavailable; will use batch STT for sid=%s', sid)
        return

    def _on_streaming_update(transcript, is_final=False, silence_detection_time=None):
        audio_stream.update_streaming_result(
            transcript,
            is_final=is_final,
            silence_detection_time=silence_detection_time,
        )

    try:
        audio_stream.future = _stt_executor.submit(
            _server.streaming_stt,
            _audio_stream_generator(audio_stream),
            _on_streaming_update,
        )
        logger.info('Streaming STT started for sid=%s', sid)
    except Exception as exc:
        logger.warning('Could not start streaming STT for sid=%s: %s', sid, exc, exc_info=True)


def _load_conversation_history_for(username):
    if _server is None or not username:
        return

    try:
        _server.load_conversation_db(username)
    except Exception as exc:
        logger.warning('Could not load conversation history for %s: %s', username, exc)


def _persist_current_conversation(context: RobotContext, username=None):
    key = context.login_username or username
    if _server is None or not key:
        return

    try:
        _server.dump_conversation_db(key, session_id=context.face_session_id)
    except Exception as exc:
        logger.warning('Could not persist conversation history for %s: %s', key, exc)


def _session_matches_context(context: RobotContext, session_data: dict = None) -> bool:
    session_data = session_data or {}

    active_login = _normalize_username(context.login_username)
    active_session_id = context.face_session_id
    incoming_login = _normalize_username(
        session_data.get('loginName') or session_data.get('login_name')
    )
    incoming_session_id = session_data.get('sessionId') or session_data.get('session_id')

    if incoming_login and active_login and incoming_login != active_login:
        return False

    if incoming_session_id and active_session_id and incoming_session_id != active_session_id:
        return False

    if incoming_login and active_login:
        return True

    if incoming_session_id and active_session_id:
        return True

    return bool(active_login)


def _matching_contexts(session_data: dict = None):
    return [
        (sid, context)
        for sid, context in _context_items()
        if _session_matches_context(context, session_data)
    ]


def _target_contexts(session_data: dict = None, sid: str = None):
    if sid:
        context = _get_existing_context(sid)
        if not context:
            return []
        if session_data and not _session_matches_context(context, session_data):
            logger.info('Session data does not match sid %s: %s', sid, session_data)
            return []
        return [(sid, context)]

    return _matching_contexts(session_data)


def _reset_runtime_session_state(context: RobotContext, sid: str, clear_login: bool):
    context.face_session_id = None
    context.proactive_question = ''
    context.continue_conversation = False
    _reset_unknown_user_tracking(context)

    if clear_login:
        context.login_username = None
        context.username = None
        context.needs_identification = False

    proactive = _get_existing_proactive_service(sid)
    if proactive:
        proactive.cancel_timers()

    _discard_audio_stream(sid)

    if context.state != 'idle':
        context.state = 'idle'
        _emit_state_update(sid, context)


def flush_session(session_data: dict = None, sid: str = None) -> bool:
    targets = _target_contexts(session_data, sid=sid)
    if not targets:
        logger.info('Flush skipped - no matching runtime session: %s', session_data)
        return False

    for target_sid, context in targets:
        login_name = _normalize_username(
            (session_data or {}).get('loginName') or (session_data or {}).get('login_name')
        ) or context.login_username

        logger.info(
            'Flushing conversation for sid=%s login=%s session=%s',
            target_sid,
            login_name,
            (session_data or {}).get('sessionId') or context.face_session_id,
        )
        _persist_current_conversation(context, login_name)

    return True


def on_client_disconnect(sid: str, session_data: dict = None):
    context = _get_existing_context(sid)
    if not context:
        unregister_session(sid)
        return

    if _session_matches_context(context, session_data):
        flush_session(session_data, sid=sid)
    else:
        logger.info('Disconnect session data did not match context for %s: %s', sid, session_data)
        _persist_current_conversation(context)

    _reset_runtime_session_state(context, sid, clear_login=True)
    unregister_session(sid)
    logger.info('Client disconnect handled for sid=%s session=%s', sid, session_data)


def on_session_logout(session_data: dict = None, sid: str = None):
    targets = _target_contexts(session_data, sid=sid)
    if not targets:
        logger.info('Logout ignored - no matching runtime session: %s', session_data)
        return False

    for target_sid, context in targets:
        flush_session(session_data, sid=target_sid)
        _reset_runtime_session_state(context, target_sid, clear_login=True)
        logger.info('Logout handled for sid=%s session=%s', target_sid, session_data)

    return True


def _reset_unknown_user_tracking(context: RobotContext):
    context.unknown_user_interactions = 0


def _mark_unknown_user_interaction(context: RobotContext):
    context.unknown_user_interactions += 1

    if context.unknown_user_interactions >= 1:
        context.proactive_question = 'casual_ask_known_username'
        logger.info(
            'Time to ask casual_ask_known_username (unknown interactions=%s)',
            context.unknown_user_interactions,
        )


def _normalize_username(username):
    clean_username = (username or '').strip()
    if not clean_username or clean_username.lower() == 'unknown':
        return None
    return clean_username


_NEGATED_NAME_CHANGE_RE = re.compile(r'\b(?:no|nunca)\s+(?:me\s+)?llames\b', re.IGNORECASE)
_NAME_CHANGE_PATTERNS = (
    re.compile(
        r'\b(?:ll[aá]mame|puedes llamarme|puede llamarme|me puedes llamar|'
        r'me puede llamar|quiero que me llames|prefiero que me llames)\s+'
        r'([^,.!?;:\n]+)',
        re.IGNORECASE,
    ),
    re.compile(r'\b(?:me llamo|mi nombre es)\s+([^,.!?;:\n]+)', re.IGNORECASE),
    re.compile(
        r'\b(?:mi nuevo nombre es|ahora me llamo|de ahora en adelante me llamo|'
        r'cambia mi nombre a|cambiar mi nombre a)\s+([^,.!?;:\n]+)',
        re.IGNORECASE,
    ),
)
_IDENTIFICATION_NAME_PATTERNS = (
    re.compile(r'\bsoy\s+([^,.!?;:\n]+)', re.IGNORECASE),
)
_NAME_RESPONSE_QUESTIONS = {'who_are_you_response', 'casual_ask_known_username'}
_STANDALONE_NAME_RESPONSE_QUESTIONS = {'who_are_you_response'}
_NAME_CANDIDATE_STOP_RE = re.compile(
    r'\b(?:por favor|gracias|porque|pero|aunque|y|a partir de ahora)\b.*$',
    re.IGNORECASE,
)
_INVALID_NAME_STARTS = {
    'de',
    'el',
    'la',
    'lo',
    'los',
    'las',
    'me',
    'mi',
    'que',
    'como',
    'soy',
    'tu',
    'un',
    'una',
    'yo',
}
_INVALID_NAME_VALUES = {
    'claro',
    'adios',
    'buenas',
    'de acuerdo',
    'desconocido',
    'gracias',
    'hola',
    'mi nombre',
    'no',
    'ok',
    'okay',
    'si',
    'unknown',
    'vale',
    'yo',
}


def _fold_name_text(text: str):
    return (
        str(text or '')
        .lower()
        .replace('á', 'a')
        .replace('é', 'e')
        .replace('í', 'i')
        .replace('ó', 'o')
        .replace('ú', 'u')
        .replace('ü', 'u')
    )


def _clean_name_candidate(candidate: str):
    candidate = _NAME_CANDIDATE_STOP_RE.sub('', str(candidate or ''))
    candidate = re.sub(r'\s+', ' ', candidate).strip(' "\'()[]{}')
    candidate = candidate.strip('.,;:!?')

    words = candidate.split()
    if not words or len(words) > 4 or len(candidate) > 80:
        return None
    if not re.search(r'[^\W\d_]', candidate, re.UNICODE):
        return None

    folded_candidate = _fold_name_text(candidate)
    if folded_candidate in _INVALID_NAME_VALUES:
        return None
    if _fold_name_text(words[0]) in _INVALID_NAME_STARTS:
        return None

    return _normalize_username(candidate)


def _is_identification_context(context: RobotContext):
    if not context:
        return False
    return context.needs_identification or context.proactive_question in _NAME_RESPONSE_QUESTIONS


def _accepts_standalone_name_response(context: RobotContext):
    if not context:
        return False
    return context.proactive_question in _STANDALONE_NAME_RESPONSE_QUESTIONS


def _extract_requested_shara_name(text: str, context: RobotContext = None):
    if not text or _NEGATED_NAME_CHANGE_RE.search(text):
        return None

    for pattern in _NAME_CHANGE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        return _clean_name_candidate(match.group(1))

    if _is_identification_context(context):
        for pattern in _IDENTIFICATION_NAME_PATTERNS:
            match = pattern.search(text)
            if match:
                return _clean_name_candidate(match.group(1))

    if _accepts_standalone_name_response(context):
        return _clean_name_candidate(text)

    return None


def _set_shara_name_for_session(
    context: RobotContext,
    shara_name,
    sid: str = None,
    source: str = 'unknown',
    emit_update: bool = True,
):
    clean_shara = _clean_name_candidate(shara_name)
    if not clean_shara:
        logger.warning('Rejected invalid shara_name from %s: %r', source, shara_name)
        return False

    clean_login = _normalize_username(context.login_username)
    previous_username = _normalize_username(context.username)

    if clean_login:
        if not update_shara_name(clean_login, clean_shara):
            logger.warning(
                'Rejected runtime shara_name update after DB failure for login=%s source=%s',
                clean_login,
                source,
            )
            return False
    else:
        logger.info('No login_name available; storing shara_name runtime-only from %s', source)

    if previous_username != clean_shara:
        logger.info(
            'shara_name accepted from %s for login=%s: %s -> %s',
            source,
            clean_login,
            previous_username,
            clean_shara,
        )

    context.username = clean_shara
    context.needs_identification = False
    if context.proactive_question in _NAME_RESPONSE_QUESTIONS:
        context.proactive_question = ''
    _reset_unknown_user_tracking(context)

    if not clean_login and previous_username != clean_shara:
        _load_conversation_history_for(clean_shara)

    if emit_update:
        _emit_session_identity_updated(
            sid=sid,
            session_id=context.face_session_id,
            username=clean_shara,
            login_name=clean_login,
        )

    return True


def _maybe_update_shara_name_from_text(context: RobotContext, text: str, sid: str = None):
    requested_name = _extract_requested_shara_name(text, context=context)
    if not requested_name:
        return

    _set_shara_name_for_session(
        context,
        requested_name,
        sid=sid,
        source='user_text',
    )


def _get_stored_shara_name(login_name):
    clean_login = _normalize_username(login_name)
    if not clean_login:
        return None
    return _clean_name_candidate(get_shara_name(clean_login))


def _persist_shara_name_for_login(context: RobotContext, shara_name):
    _set_shara_name_for_session(
        context,
        shara_name,
        source='legacy_persist_helper',
        emit_update=False,
    )


def proactive_event_handler(event: str, params: dict = None, sid: str = None):
    params = params or {}
    logger.info('Proactive event for sid=%s: %s - %s', sid, event, params)

    if not sid:
        logger.warning('Ignoring proactive event without sid: %s', event)
        return

    if event == 'ask_how_are_you':
        gevent.spawn(
            process_transition,
            'proactive2processingquery',
            {'question': 'how_are_you', **params},
            sid,
        )
    elif event == 'ask_who_are_you':
        gevent.spawn(
            process_transition,
            'proactive2processingquery',
            {'question': 'who_are_you'},
            sid,
        )


def on_session_login(sid: str, session_data: dict):
    context = _get_context(sid)
    _get_proactive_service(sid)

    session_data = session_data or {}
    session_id = session_data.get('sessionId')

    login_name = _normalize_username(session_data.get('loginName'))
    is_new_user = bool(session_data.get('isNewUser', False))
    incoming_username = _clean_name_candidate(session_data.get('userName') or session_data.get('username'))
    previous_login = context.login_username
    previous_session_id = context.face_session_id
    previous_username = _normalize_username(context.username)

    if (
        context.state in ('recording', 'processing_query', 'speaking')
        and previous_login == login_name
        and previous_session_id == session_id
        and previous_username == incoming_username
    ):
        logger.debug(
            'Ignoring unchanged session identity refresh while state=%s sid=%s',
            context.state,
            sid,
        )
        return

    shara_name = None if is_new_user else _get_stored_shara_name(login_name)

    if not shara_name and incoming_username:
        if login_name:
            if update_shara_name(login_name, incoming_username):
                shara_name = incoming_username
            else:
                logger.warning('Could not persist incoming shara_name for login=%s', login_name)
        else:
            shara_name = incoming_username

    preserve_runtime_flags = (
        context.state in ('recording', 'processing_query', 'speaking')
        and previous_login == login_name
        and (
            not session_id
            or not previous_session_id
            or previous_session_id == session_id
        )
    )

    logger.info(
        'Session login: sid=%s session_id=%s login_name=%s shara_name=%s is_new=%s previous_login=%s',
        sid,
        session_id,
        login_name,
        shara_name,
        is_new_user,
        previous_login,
    )

    if previous_login and previous_login != login_name:
        _persist_current_conversation(context)

    if login_name:
        _load_conversation_history_for(login_name)

    context.face_session_id = session_id
    context.login_username = login_name
    context.username = shara_name
    context.needs_identification = is_new_user or not bool(shara_name)

    if not preserve_runtime_flags:
        context.proactive_question = ''
        context.continue_conversation = False
        _reset_unknown_user_tracking(context)


def on_user_detected(sid: str, user_data: dict):
    """Face detected by FaceDetection.jsx."""
    context = _get_context(sid)
    proactive = _get_proactive_service(sid)
    user_data = user_data or {}

    incoming_username = _clean_name_candidate(user_data.get('userName'))
    login_name = _normalize_username(user_data.get('loginName')) or context.login_username
    face_session_id = user_data.get('sessionId')
    incoming_needs_identification = bool(user_data.get('needsIdentification', False))
    is_new_user = user_data.get('isNewUser', True)
    previous_username = context.username
    previous_login = context.login_username

    logger.info(
        'User detected: sid=%s session_id=%s login_name=%s username=%s needs_identification=%s new=%s state=%s',
        sid,
        face_session_id,
        login_name,
        incoming_username,
        incoming_needs_identification,
        is_new_user,
        context.state,
    )

    if login_name and login_name != previous_login:
        if previous_login:
            _persist_current_conversation(context)
        context.login_username = login_name

    if login_name:
        _load_conversation_history_for(login_name)

    context.face_session_id = face_session_id

    if login_name:
        if not context.username:
            context.username = _get_stored_shara_name(login_name)
        username = _normalize_username(context.username)
        needs_identification = not bool(username)
    else:
        username = incoming_username
        needs_identification = incoming_needs_identification

    context.needs_identification = needs_identification
    is_known_user = not needs_identification and username is not None

    if is_known_user:
        if not login_name:
            if previous_username and previous_username != username:
                _persist_current_conversation(context, previous_username)
            if previous_username != username:
                _load_conversation_history_for(username)
        context.username = username
        if proactive:
            proactive.update('sensor', 'close_face_recognized', {'username': username})
    else:
        if not login_name and previous_username:
            _persist_current_conversation(context, previous_username)
        context.username = None
        if proactive:
            proactive.update('sensor', 'unknown_face')

    if context.state == 'idle_presence':
        gevent.spawn(process_transition, 'idle_presence2listening', {}, sid)
    elif context.state == 'idle':
        gevent.spawn(process_transition, 'idle2idle_presence', {}, sid)
        gevent.spawn(process_transition, 'idle_presence2listening', {}, sid)


def on_user_lost(sid: str, user_data: dict):
    """Face lost by FaceDetection.jsx."""
    context = _get_existing_context(sid)
    if not context:
        return

    logger.info('User lost: sid=%s state=%s', sid, context.state)
    _persist_current_conversation(context)
    context.face_session_id = None
    context.proactive_question = ''
    context.continue_conversation = False
    _reset_unknown_user_tracking(context)

    proactive = _get_existing_proactive_service(sid)
    if proactive:
        proactive.cancel_timers()

    if context.state == 'listening':
        gevent.spawn(process_transition, 'listening2idle_presence', {}, sid)


def on_audio_stream_start(sid: str) -> bool:
    """PCM LINEAR16 stream started after browser-side VAD detected speech."""
    context = _get_context(sid)
    logger.info('Audio stream start from %s, state=%s', sid, context.state)

    if context.state not in ('listening', 'idle_presence', 'idle'):
        logger.warning('audio_stream_start in unexpected state for %s: %s', sid, context.state)
        return False

    context.state = 'recording'
    _emit_state_update(sid, context)

    _discard_audio_stream(sid)
    audio_stream = _AudioStream()
    with _audio_streams_lock:
        _audio_streams[sid] = audio_stream
    _start_streaming_stt(audio_stream, sid)

    return True


def on_audio_chunk(audio_bytes: bytes, sid: str) -> bool:
    """PCM LINEAR16 chunk received from AudioWorklet."""
    with _audio_streams_lock:
        audio_stream = _audio_streams.get(sid)

    if not audio_stream:
        logger.debug('Ignoring audio_chunk for sid=%s with no active stream', sid)
        return False

    return audio_stream.append(audio_bytes)


def on_audio_stream_end(sid: str) -> bool:
    """PCM stream ended; finish live STT or fall back to batch STT."""
    logger.info('Audio stream end from %s', sid)
    if not _get_existing_context(sid):
        logger.warning('Ignoring audio_stream_end for unknown sid: %s', sid)
        _discard_audio_stream(sid)
        return False

    with _audio_streams_lock:
        audio_stream = _audio_streams.pop(sid, None)

    if not audio_stream:
        logger.warning('Ignoring audio_stream_end for sid=%s with no active stream', sid)
        return False

    audio_stream.close()
    _executor.submit(_process_audio_stream_end, audio_stream, sid)
    return True


def on_audio_message(audio_b64: str, sid: str):
    """Legacy full audio blob path."""
    context = _get_context(sid)
    logger.info('Legacy audio blob from %s, state=%s', sid, context.state)

    if context.state not in ('listening', 'idle_presence', 'idle'):
        logger.warning('Audio received in unexpected state for %s: %s', sid, context.state)
        return

    context.state = 'recording'
    _emit_state_update(sid, context)
    _executor.submit(_process_audio_query, audio_b64, sid)


def on_text_message(text: str, sid: str):
    """Text typed in chat, bypassing STT."""
    context = _get_context(sid)
    logger.info('Text message from %s: "%s"', sid, text)

    if context.state == 'processing_query':
        logger.warning('Session %s is already processing a query, ignoring', sid)
        return

    context.state = 'processing_query'
    _emit_state_update(sid, context)
    _executor.submit(_process_text_query, text, sid)


def on_tts_complete(sid: str):
    """Frontend finished playing TTS audio."""
    context = _get_existing_context(sid)
    if not context:
        return

    logger.info('TTS complete from %s, continue=%s', sid, context.continue_conversation)

    if context.continue_conversation:
        gevent.spawn(process_transition, 'speaking2listening', {}, sid)
    else:
        gevent.spawn(process_transition, 'speaking2idle_presence', {}, sid)


def process_transition(transition: str, params: dict = None, sid: str = None):
    params = params or {}
    context = _get_existing_context(sid)
    if not context:
        logger.warning('Transition %s ignored for unknown sid=%s', transition, sid)
        return

    current = context.state
    logger.info('Transition: %s | sid=%s | State: %s', transition, sid, current)

    try:
        if transition == 'idle2idle_presence' and current == 'idle':
            context.state = 'idle_presence'
            _emit_state_update(sid, context)

        elif transition == 'idle_presence2idle' and current == 'idle_presence':
            context.state = 'idle'
            _emit_state_update(sid, context)

        elif transition == 'idle_presence2listening' and current == 'idle_presence':
            context.state = 'listening'
            _emit_state_update(sid, context)

        elif transition == 'listening2idle_presence' and current == 'listening':
            context.state = 'idle_presence'
            _emit_state_update(sid, context)

        elif transition == 'speaking2listening' and current == 'speaking':
            context.state = 'listening'
            _emit_state_update(sid, context)

        elif transition == 'speaking2idle_presence' and current == 'speaking':
            context.state = 'idle_presence'
            if context.proactive_question not in _NAME_RESPONSE_QUESTIONS:
                context.proactive_question = ''
            context.continue_conversation = False
            _reset_unknown_user_tracking(context)
            _emit_state_update(sid, context)

        elif transition == 'proactive2processingquery':
            _handle_proactive_query(params, sid, context)

        else:
            logger.debug('Transition %s discarded for sid=%s (state=%s)', transition, sid, current)

    except Exception as exc:
        logger.error('Error in transition %s for sid=%s: %s', transition, sid, exc, exc_info=True)


def _build_request(context: RobotContext, audio: bytes = b'', text: str = None):
    return _server.Request(
        audio=audio,
        text=text,
        username=context.username,
        login_name=context.login_username,
        session_id=context.face_session_id,
        proactive_question=context.proactive_question,
    )


def _return_to_listening_after_empty_audio(sid: str, context: RobotContext, reason: str):
    logger.info('Empty audio input for sid=%s (%s); returning to listening', sid, reason)
    context.state = 'listening'
    _emit_state_update(sid, context)
    _emit_audio_empty(sid, context)


def _process_audio_stream_end(audio_stream: _AudioStream, sid: str):
    """Streaming STT -> LLM -> TTS pipeline with batch STT fallback."""
    context = _get_existing_context(sid)
    if not context:
        logger.warning('Audio processing abandoned for unknown sid=%s', sid)
        return

    try:
        context.state = 'processing_query'
        _emit_state_update(sid, context)

        audio_bytes = audio_stream.snapshot_audio()
        logger.info('Audio stream collected from %s: %s bytes', sid, len(audio_bytes))

        if not audio_bytes:
            _return_to_listening_after_empty_audio(sid, context, 'empty audio buffer')
            return

        transcript = ''
        streaming_error = None
        if audio_stream.future:
            if audio_stream.future.done():
                try:
                    transcript = audio_stream.future.result()
                except Exception as exc:
                    streaming_error = exc
                    logger.warning('Streaming STT failed for sid=%s: %s', sid, exc, exc_info=True)
            else:
                audio_stream.future.cancel()
                transcript = audio_stream.latest_streaming_transcript()
                logger.warning(
                    'Streaming STT final result not ready at stream_end for sid=%s; %s',
                    sid,
                    'using latest interim transcript' if transcript else 'falling back to batch STT',
                )

        if not transcript:
            transcript = audio_stream.latest_streaming_transcript()

        if transcript:
            logger.info('Using streaming STT transcript for sid=%s: %s', sid, transcript)
            _maybe_update_shara_name_from_text(context, transcript, sid=sid)
            _emit_transcription_result(transcript, sid, context)

            request = _build_request(context, text=transcript)
            future = _query_executor.submit(_server.query_with_text, request)
            response = future.result(timeout=SERVER_QUERY_TIMEOUT)
        else:
            if streaming_error is None:
                logger.info('Streaming STT returned empty for sid=%s; falling back to batch STT', sid)
            request = _build_request(context, audio=audio_bytes)
            future = _query_executor.submit(_server.query, request)
            response = future.result(timeout=SERVER_QUERY_TIMEOUT)

        if response is None:
            _return_to_listening_after_empty_audio(sid, context, 'empty transcription')
            return

        if response.request.text and not transcript:
            _maybe_update_shara_name_from_text(context, response.request.text, sid=sid)
            _emit_transcription_result(response.request.text, sid, context)

        _handle_response(response, sid, context)

    except concurrent.futures.TimeoutError:
        logger.error('Timeout in audio stream processing for sid=%s', sid)
        _emit_error(sid)
    except Exception as exc:
        logger.error('Error in audio stream processing for sid=%s: %s', sid, exc, exc_info=True)
        _emit_error(sid)


def _process_audio_query(audio_b64: str, sid: str):
    """STT -> LLM -> TTS pipeline for legacy audio input."""
    context = _get_existing_context(sid)
    if not context:
        logger.warning('Legacy audio processing abandoned for unknown sid=%s', sid)
        return

    try:
        context.state = 'processing_query'
        _emit_state_update(sid, context)

        audio_bytes = base64.b64decode(audio_b64)
        request = _build_request(context, audio=audio_bytes)

        future = _query_executor.submit(_server.query, request)
        response = future.result(timeout=SERVER_QUERY_TIMEOUT)

        if response is None:
            _return_to_listening_after_empty_audio(sid, context, 'empty legacy transcription')
            return

        if response.request.text:
            _maybe_update_shara_name_from_text(context, response.request.text, sid=sid)

        _handle_response(response, sid, context)

    except concurrent.futures.TimeoutError:
        logger.error('Timeout in legacy audio processing for sid=%s', sid)
        _emit_error(sid)
    except Exception as exc:
        logger.error('Error processing legacy audio for sid=%s: %s', sid, exc, exc_info=True)
        _emit_error(sid)


def _process_text_query(text: str, sid: str):
    """LLM -> TTS pipeline for text input."""
    context = _get_existing_context(sid)
    if not context:
        logger.warning('Text processing abandoned for unknown sid=%s', sid)
        return

    try:
        _maybe_update_shara_name_from_text(context, text, sid=sid)
        request = _build_request(context, text=text)

        future = _query_executor.submit(_server.query_with_text, request)
        response = future.result(timeout=SERVER_QUERY_TIMEOUT)

        if response is None:
            logger.warning('Empty response for sid=%s', sid)
            _emit_error(sid)
            return

        _handle_response(response, sid, context)

    except concurrent.futures.TimeoutError:
        logger.error('Timeout in text processing for sid=%s', sid)
        _emit_error(sid)
    except Exception as exc:
        logger.error('Error processing text for sid=%s: %s', sid, exc, exc_info=True)
        _emit_error(sid)


def _handle_proactive_query(params: dict, sid: str, context: RobotContext):
    """Proactive question pipeline: no STT, direct LLM -> TTS."""
    question = params.get('question')
    username = params.get('username', context.username)

    logger.info('Proactive query for sid=%s: %s for %s', sid, question, username)

    try:
        context.state = 'processing_query'
        _emit_state_update(sid, context)

        request = _server.Request(
            username=username,
            login_name=context.login_username,
            session_id=context.face_session_id,
            proactive_question=question or '',
        )

        future = _query_executor.submit(_server.proactive_query, request)
        response = future.result(timeout=SERVER_QUERY_TIMEOUT)

        if response is None:
            logger.warning('Empty proactive response for sid=%s', sid)
            context.state = 'idle_presence'
            _emit_state_update(sid, context)
            return

        next_proactive_question = 'who_are_you_response' if question == 'who_are_you' else ''
        if next_proactive_question:
            response.continue_conversation = True

        _handle_response(
            response,
            sid,
            context,
            next_proactive_question=next_proactive_question,
            mark_unknown_interaction=False,
        )

        proactive = _get_existing_proactive_service(sid)
        if proactive:
            proactive.update('confirm', question, {'username': username})

    except concurrent.futures.TimeoutError:
        logger.error('Timeout in proactive query for sid=%s', sid)
        context.state = 'idle_presence'
        _emit_state_update(sid, context)
    except Exception as exc:
        logger.error('Error in proactive query for sid=%s: %s', sid, exc, exc_info=True)
        context.state = 'idle_presence'
        _emit_state_update(sid, context)


def _handle_response(
    response,
    sid: str,
    context: RobotContext,
    next_proactive_question: str = '',
    mark_unknown_interaction: bool = True,
):
    """
    Common response handler. Updates only this session context and emits only to
    this socket sid.
    """
    context.state = 'speaking'
    context.continue_conversation = response.continue_conversation
    context.proactive_question = next_proactive_question or ''

    if response.action == 'record_face':
        _set_shara_name_for_session(
            context,
            response.username,
            sid=sid,
            source='record_face_tool',
        )

    elif response.action == 'set_username':
        logger.info(
            'Updating username to %s for sid=%s (unknown interactions=%s)',
            response.username,
            sid,
            context.unknown_user_interactions,
        )
        _set_shara_name_for_session(
            context,
            response.username,
            sid=sid,
            source='set_username_tool',
        )

    elif response.username:
        _set_shara_name_for_session(
            context,
            response.username,
            sid=sid,
            source='response_username',
        )

    if mark_unknown_interaction and sid is not None and not context.username:
        _mark_unknown_user_interaction(context)

    if _eyes and response.robot_mood:
        try:
            _eyes.set(response.robot_mood, sid=sid, session_id=context.face_session_id)
        except Exception as exc:
            logger.warning('Could not set eye state for sid=%s: %s', sid, exc)

    audio_b64 = base64.b64encode(response.audio).decode('utf-8') if response.audio else None

    message = {
        'text': response.text or '',
        'state': response.robot_mood or 'neutral',
        'audio': audio_b64,
        'audioMimeType': getattr(response, 'audio_mime_type', 'audio/mpeg'),
        'continue': response.continue_conversation,
        'sessionId': context.face_session_id,
    }

    _emit_robot_message(message, sid)
    _emit_state_update(sid, context)

    logger.info(
        'Response emitted to sid=%s: mood=%s continue=%s',
        sid,
        response.robot_mood,
        response.continue_conversation,
    )


def _emit_robot_message(message: dict, sid: str = None):
    if _socketio is None:
        return
    if not sid:
        logger.warning('robot_message without sid skipped')
        return
    _socketio.emit('robot_message', message, to=sid, namespace='/message')


def _emit_state_update(sid: str = None, context: RobotContext = None):
    if _socketio is None:
        return
    if not sid:
        logger.debug('state_update without sid skipped')
        return

    context = context or _get_existing_context(sid)
    if not context:
        return

    _socketio.emit(
        'state_update',
        {
            'state': context.state,
            'sessionId': context.face_session_id,
        },
        to=sid,
        namespace='/message',
    )


def _emit_session_identity_updated(sid=None, session_id=None, username=None, login_name=None):
    if _socketio is None or sid is None or not session_id:
        return

    payload = {
        'sessionId': session_id,
        'userName': username,
        'sharaName': username,
        'isNewUser': False,
        'needsIdentification': False,
        'userStatus': 'existing',
    }
    if login_name:
        payload['loginName'] = login_name

    _socketio.emit(
        'session_identity_updated',
        payload,
        to=sid,
        namespace='/message',
    )


def _emit_transcription_result(text: str, sid: str, context: RobotContext):
    if not text or not sid or _socketio is None:
        return

    _socketio.emit(
        'transcription_result',
        {
            'text': text,
            'sessionId': context.face_session_id,
        },
        to=sid,
        namespace='/message',
    )


def _emit_audio_empty(sid: str, context: RobotContext):
    if not sid or _socketio is None:
        return
    _socketio.emit(
        'audio_empty',
        {'sessionId': context.face_session_id},
        to=sid,
        namespace='/message',
    )


def _emit_error(sid=None):
    context = _get_existing_context(sid)
    if context:
        context.state = 'idle_presence'
        _emit_state_update(sid, context)

    if sid and _socketio:
        _socketio.emit(
            'robot_message',
            {
                'text': 'Lo siento, ha ocurrido un error. Por favor, intentalo de nuevo.',
                'state': 'neutral',
                'sessionId': context.face_session_id if context else None,
            },
            to=sid,
            namespace='/message',
        )
