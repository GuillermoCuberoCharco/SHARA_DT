"""All session transitions, emits and timers run on the Socket.IO gevent hub.
Native workers only consume audio or perform blocking database/cloud calls.
"""
import base64
import concurrent.futures
import logging
import os
import queue
import re
import uuid

import gevent

from auth import greeted_recently, update_shara_name
from proactive_service import ProactiveService
from robot_context import RobotContext

logger = logging.getLogger('StateMachine')
SERVER_QUERY_TIMEOUT = float(os.getenv('SERVER_QUERY_TIMEOUT_SECONDS', '45'))
LISTENING_RESPONSE_TIMEOUT_SECONDS = float(os.getenv('LISTENING_RESPONSE_TIMEOUT_SECONDS', '12'))
DEVICE_START_TIMEOUT = 45
PRESENCE_CHECK_TIMEOUT = 20
RECORDING_TIMEOUT = 55
MAX_AUDIO_BYTES = 16000 * 2 * RECORDING_TIMEOUT
STT_FINAL_WAIT = 2
TTS_WATCHDOG_MIN_SECONDS = float(os.getenv('TTS_WATCHDOG_MIN_SECONDS', '12'))
TTS_WATCHDOG_MAX_SECONDS = float(os.getenv('TTS_WATCHDOG_MAX_SECONDS', '75'))
TTS_WATCHDOG_SECONDS_PER_CHAR = float(os.getenv('TTS_WATCHDOG_SECONDS_PER_CHAR', '0.09'))
TTS_WATCHDOG_GRACE_SECONDS = float(os.getenv('TTS_WATCHDOG_GRACE_SECONDS', '6'))
TTS_WATCHDOG_ACK_GRACE_SECONDS = float(os.getenv('TTS_WATCHDOG_ACK_GRACE_SECONDS', '8'))

_sessions = {}
_proactive = ProactiveService()
_stt_executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
_socketio = _server = _eyes = None


class AudioStream:
    def __init__(self):
        self.buffer = bytearray()
        self.queue = queue.Queue()
        self.future = _stt_executor.submit(_server.streaming_stt, self.chunks())
        self.closed = False

    def chunks(self):
        yield from iter(self.queue.get, None)

    def append(self, chunk):
        self.buffer.extend(chunk)
        self.queue.put_nowait(chunk)

    def close(self):
        if not self.closed:
            self.closed = True
            self.queue.put_nowait(None)

    def transcribe(self):
        try:
            text = self.future.result(timeout=STT_FINAL_WAIT)
            if text:
                return text
        except Exception as exc:
            logger.info('Final streaming transcript unavailable: %s', exc)
            self.future.cancel()
        return _server.speech_to_text(bytes(self.buffer))


def init(socketio_instance, server_module, eyes_instance=None):
    global _socketio, _server, _eyes
    _socketio, _server, _eyes = socketio_instance, server_module, eyes_instance


def _blocking(fn, *args):
    return gevent.get_hub().threadpool.spawn(fn, *args).get()


def register_session(sid, login_name, username):
    _sessions[sid] = RobotContext(sid, login_name, username=username,
                                  needs_identification=not bool(username))


def get_active_sessions_count():
    return len(_sessions)


def get_session_states():
    return {sid: {'state': c.state} for sid, c in _sessions.items()}


def _emit(c, event, **data):
    _socketio.emit(event, dict(data, sessionId=c.face_session_id, turnId=c.turn_id),
                   to=c.sid, namespace='/message')


def _state(c):
    _emit(c, 'state_update', state=c.state, presenceCheck=c.presence_check,
          messageId=c.current_tts_message_id, microphoneReady=c.mic_ready)


def _valid(c, turn_id):
    return _sessions.get(c.sid) is c and c.turn_id == turn_id


def _cancel_timer(c):
    timer, c.timer = c.timer, None
    if timer is not None and timer is not gevent.getcurrent():
        timer.kill(block=False)


def _deadline(c, seconds, callback, *args):
    _cancel_timer(c)
    turn_id = c.turn_id

    def expired():
        if c.timer is gevent.getcurrent() and _valid(c, turn_id):
            c.timer = None
            callback(c, *args)

    c.timer = gevent.spawn_later(seconds, expired)


def _end_turn(c):
    _cancel_timer(c)
    if c.stream is not None:
        c.stream.close()
        c.stream.future.cancel()
        c.stream = None
    _proactive.release(c.login_username, c.sid)
    c.turn_id = uuid.uuid4().hex
    c.response = c.current_tts_message_id = c.presence_check = None
    c.greeting = ''
    c.mic_ready = False


def _absent(c):
    _end_turn(c)
    c.state = 'idle'
    c.proactive_question = ''
    _state(c)


def _rest(c, recheck=False, error=None):
    _end_turn(c)
    c.state = 'idle_presence'
    if not recheck:
        c.proactive_question = ''
    if recheck and c.protocol >= 2:
        c.presence_check = uuid.uuid4().hex
        _deadline(c, PRESENCE_CHECK_TIMEOUT, _absent)
    _state(c)
    if error:
        _emit(c, 'interaction_error', text=error)


def _listen(c):
    _end_turn(c)
    c.state = 'listening'
    if c.protocol >= 2:
        _deadline(c, DEVICE_START_TIMEOUT, _rest, False,
                  'El micrófono no está disponible. Comprueba el permiso y vuelve a intentarlo.')
    else:
        _deadline(c, LISTENING_RESPONSE_TIMEOUT_SECONDS, _rest, True)
    _state(c)


def on_session_login(sid, data):
    c = _sessions.get(sid)
    session_id = data.get('sessionId')
    if not c or not isinstance(session_id, str) or not 0 < len(session_id) <= 255:
        return
    if c.face_session_id and c.face_session_id != session_id:
        return
    c.face_session_id = session_id
    c.protocol = 2 if data.get('protocolVersion') == 2 else 1
    _state(c)


def _session(sid, data, check_turn=True):
    c = _sessions.get(sid)
    if not c or not c.face_session_id or not isinstance(data, dict):
        return None
    if c.protocol >= 2 or data.get('sessionId'):
        if data.get('sessionId') != c.face_session_id:
            return None
    if check_turn and (c.protocol >= 2 or data.get('turnId')):
        if data.get('turnId') != c.turn_id:
            return None
    return c


def flush_session(session_data):
    return any(c.login_username == session_data.get('loginName')
               and c.face_session_id == session_data.get('sessionId') for c in _sessions.values())


def on_client_disconnect(sid):
    c = _sessions.pop(sid, None)
    if c:
        _end_turn(c)


def on_session_logout(data):
    for c in list(_sessions.values()):
        if c.login_username == data.get('loginName') and (
            not data.get('sessionId') or data['sessionId'] == c.face_session_id
        ):
            on_client_disconnect(c.sid)
            _socketio.server.disconnect(c.sid, namespace='/message')


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


def on_user_detected(sid, data):
    c = _session(sid, data)
    if not c:
        return
    if c.presence_check:
        if data.get('presenceCheck') != c.presence_check:
            return
        c.presence_check = None
        if c.state == 'processing_query' and c.response is not None:
            _speak(c)
        elif c.state == 'idle_presence':
            _listen(c)
        return
    if c.state != 'idle':
        return
    c.state = 'idle_presence'
    _state(c)
    if _proactive.reserve(c.login_username, sid):
        c.greeting = 'how_are_you' if c.username else 'who_are_you'
        _process(c)
    else:
        _listen(c)


def on_user_lost(sid, data):
    # Hiding the page invalidates even a transition the browser has not seen yet.
    c = _session(sid, data, check_turn=data.get('reason') != 'document_hidden')
    if c:
        _absent(c)


def on_resume(sid, data):
    c = _session(sid, data)
    if c and c.state == 'idle_presence':
        _rest(c, recheck=True)


def on_microphone_ready(sid, data):
    c = _session(sid, data)
    if c and c.state == 'listening' and not c.mic_ready:
        c.mic_ready = True
        _deadline(c, LISTENING_RESPONSE_TIMEOUT_SECONDS, _rest, True)
        _state(c)


def on_device_error(sid, data):
    c = _session(sid, data)
    if not c:
        return
    if data.get('device') == 'microphone' and c.state in ('listening', 'recording'):
        _rest(c, error='No se pudo usar el micrófono. Comprueba el permiso y pulsa para retomar.')
    elif data.get('device') == 'camera':
        _absent(c)


def on_audio_stream_start(sid, data):
    c = _session(sid, data)
    if not c or c.state != 'listening' or (c.protocol >= 2 and not c.mic_ready):
        return False
    c.stream = AudioStream()
    c.state = 'recording'
    _deadline(c, RECORDING_TIMEOUT, _rest, True)
    _state(c)
    return True


def on_audio_chunk(chunk, sid, data):
    c = _session(sid, data)
    if c and c.state == 'recording' and c.stream:
        if len(c.stream.buffer) + len(chunk) > MAX_AUDIO_BYTES:
            _rest(c, error='La grabación superó el límite de duración.')
            return
        c.stream.append(chunk)


def on_audio_stream_end(sid, data):
    c = _session(sid, data)
    if c and c.state == 'listening' and data.get('reason') == 'silence':
        _rest(c, recheck=True)
        return True
    if not c or c.state != 'recording' or not c.stream:
        return False
    stream, c.stream = c.stream, None
    stream.close()
    _process(c, transcribe=stream.transcribe)
    return True


def on_audio_message(sid, data):
    c = _session(sid, data)
    if not c or c.state != 'listening':
        return
    try:
        audio = base64.b64decode(data['data'], validate=True)
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValueError('audio too large')
    except (KeyError, ValueError, TypeError):
        _rest(c, error='La grabación recibida no es válida.')
        return
    # Older MediaRecorder clients omitted the type. Read the container signature.
    mime = data.get('mimeType')
    if not mime:
        mime = ('audio/ogg' if audio.startswith(b'OggS') else
                'audio/wav' if audio.startswith(b'RIFF') else 'audio/webm')
    _process(c, transcribe=lambda: _server.speech_to_text(audio, mime))


def on_text_message(sid, data):
    c = _session(sid, data)
    text = data.get('text', '').strip()
    if c and text and c.state in ('listening', 'idle_presence', 'idle'):
        _emit(c, 'client_message', text=text, sender='client')
        _process(c, text=text)


def _process(c, text=None, transcribe=None):
    c.state = 'processing_query'
    c.mic_ready = False
    _deadline(c, SERVER_QUERY_TIMEOUT, _rest, False, 'La respuesta ha tardado demasiado. Puedes retomar la conversación.')
    _state(c)
    gevent.spawn(_prepare_response, c, c.turn_id, text, transcribe)


def _prepare_response(c, turn_id, text, transcribe):
    try:
        if not _valid(c, turn_id):
            return
        if c.greeting and _blocking(greeted_recently, c.login_username, _proactive.COOLDOWN):
            if _valid(c, turn_id):
                _listen(c)
            return
        if transcribe:
            text = _blocking(transcribe)
        if not _valid(c, turn_id):
            return
        if transcribe and not text:
            _emit(c, 'audio_empty')
            _rest(c, recheck=True)
            return
        if transcribe:
            _emit(c, 'transcription_result', text=text)
        question = c.greeting or c.proactive_question
        name = _extract_requested_shara_name(text, c)
        request = _server.Request(text=text, username=name or c.username, login_name=c.login_username,
                                  session_id=c.face_session_id, turn_id=turn_id, proactive_question=question)
        response = _blocking(_server.query_with_text, request)
        if not _valid(c, turn_id):
            return
        response.audio = _blocking(_server.text_to_speech, response.text)
        if not _valid(c, turn_id):
            return
        name = name or _clean_name_candidate(response.username)
        if name:
            saved = _blocking(update_shara_name, c.login_username, name)
            if not _valid(c, turn_id):
                return
            if not saved:
                raise RuntimeError('Could not persist preferred name')
            c.username, c.needs_identification = name, False
            _emit(c, 'session_identity_updated', userName=name, sharaName=name, isNewUser=False,
                  needsIdentification=False, userStatus='existing', loginName=c.login_username)
        c.response = response
        if c.protocol >= 2:
            # Verify a fresh stable face after the cloud returns, even on a fast reply.
            c.presence_check = uuid.uuid4().hex
            _deadline(c, PRESENCE_CHECK_TIMEOUT, _absent)
            _state(c)
        else:
            _speak(c)
    except Exception:
        logger.exception('Query failed for %s', c.sid)
        if _valid(c, turn_id):
            _rest(c, error='No se pudo preparar la respuesta. Puedes retomar la conversación.')


def _speak(c):
    response = c.response
    c.state = 'speaking'
    c.current_tts_message_id = uuid.uuid4().hex
    estimate = len(response.text) * TTS_WATCHDOG_SECONDS_PER_CHAR + TTS_WATCHDOG_GRACE_SECONDS
    timeout = max(TTS_WATCHDOG_MIN_SECONDS, min(TTS_WATCHDOG_MAX_SECONDS, estimate))
    _deadline(c, timeout + TTS_WATCHDOG_ACK_GRACE_SECONDS, _rest, False,
              'No se ha confirmado la reproducción de la respuesta.')
    _state(c)
    if _eyes:
        _eyes.set(response.robot_mood, sid=c.sid, session_id=c.face_session_id)
    _emit(c, 'robot_message', messageId=c.current_tts_message_id, text=response.text,
          audio=base64.b64encode(response.audio).decode() if response.audio else None,
          state=response.robot_mood, audioMimeType=response.audio_mime_type,
          ttsTimeoutMs=int(timeout * 1000), **{'continue': response.continue_conversation})


def on_tts_complete(sid, data):
    c = _session(sid, data)
    if not c or c.state != 'speaking' or not c.current_tts_message_id:
        return
    if (c.protocol >= 2 or data.get('messageId')) and data.get('messageId') != c.current_tts_message_id:
        return
    if data.get('status', 'played' if c.protocol == 1 else None) != 'played':
        _rest(c, error='No se pudo reproducir la respuesta. Comprueba el sonido y pulsa para retomar.')
        return
    _cancel_timer(c)
    c.current_tts_message_id = None  # Claim this ACK before yielding.
    c.state = 'processing_query'
    _state(c)
    turn_id, response, greeting = c.turn_id, c.response, c.greeting
    _proactive.release(c.login_username, c.sid, played=bool(greeting))
    gevent.spawn(_save_delivered, c, turn_id, response, greeting)


def _save_delivered(c, turn_id, response, greeting):
    for attempt in range(2):
        try:
            with gevent.Timeout(15, TimeoutError('history write timed out')):
                _blocking(_server.persist_exchange, c.login_username, response.exchange,
                          response.request.session_id, turn_id, bool(greeting))
            break
        except Exception:
            logger.exception('Could not save delivered turn %s (attempt %d)', turn_id, attempt + 1)
    else:
        if _valid(c, turn_id):
            _rest(c, error='La respuesta se reprodujo, pero no se pudo confirmar que se guardara en el historial.')
        return
    if not _valid(c, turn_id):
        return
    if greeting == 'who_are_you':
        c.proactive_question = 'who_are_you_response'
    elif not greeting and not c.username:
        c.proactive_question = 'casual_ask_known_username'
    else:
        c.proactive_question = ''
    if greeting == 'who_are_you' or response.continue_conversation:
        if c.protocol >= 2:
            _rest(c, recheck=True)
        else:
            _listen(c)
    else:
        _rest(c)
