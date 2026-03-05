"""
sockets/message_handler.py

Socket.IO namespace /message — equivalent to Node.js messageHandler.cjs.

Events received from frontend:
    register_client     — web client registration
    client_message      — audio (base64 webm/opus blob, legacy) or text from user
    audio_stream_start  — PCM LINEAR16 stream begins
    audio_chunk         — PCM LINEAR16 chunk (base64 Int16 bytes)
    audio_stream_end    — PCM stream finished, trigger streaming STT
    user_detected       — face detected by FaceDetection.jsx
    user_lost           — face lost
    tts_complete        — frontend finished playing TTS audio
    transcription_result— STT result (text) from browser fallback

Events emitted to frontend:
    registration_success
    robot_message       — {text, state, audio (base64), continue}
    state_update        — {state}
    transcription_result— {text} echo of what the user said (for chat display)
"""

import logging
import queue

from flask import request
from flask_socketio import Namespace, emit

import state_machine

logger = logging.getLogger('MessageHandler')

# Track connected web clients: sid → {username, registered}
_clients: dict = {}

# Per-session audio queues for PCM streaming
# sid → queue.Queue of bytes chunks
_audio_queues: dict = {}


class MessageNamespace(Namespace):

    def on_connect(self):
        logger.info(f'[/message] Client connected: {request.sid}')
        _clients[request.sid] = {'registered': False, 'username': None}

    def on_disconnect(self):
        logger.info(f'[/message] Client disconnected: {request.sid}')
        _clients.pop(request.sid, None)
        # Clean up any active audio queue for this session
        _cleanup_audio_queue(request.sid)

    def on_register_client(self, data):
        """
        Client registration. data can be a string ('web') or dict.
        Equivalent to socket.on('register_client') in messageHandler.cjs.
        """
        client_type = data if isinstance(data, str) else data.get('client', 'web')
        logger.info(f'[/message] Registering client {request.sid} as {client_type}')

        if request.sid in _clients:
            _clients[request.sid]['registered'] = True

        emit('registration_success', {'status': 'ok', 'role': client_type})

    # ── PCM Streaming handlers ────────────────────────────────────────────────

    def on_audio_stream_start(self, data):
        """
        Browser signals start of a new PCM LINEAR16 audio stream.
        Creates a queue that will receive PCM chunks, then passes the
        generator to state_machine so it can launch Google streaming STT
        in a background thread — identical to the robot's mic.enable_streaming().
        """
        sid = request.sid
        logger.info(f'[/message] audio_stream_start from {sid}')

        # Cancel any previous incomplete stream
        _cleanup_audio_queue(sid)

        # Create fresh queue (maxsize=0 → unlimited)
        audio_q = queue.Queue()
        _audio_queues[sid] = audio_q

        # Pass a generator over the queue to the state machine.
        # The generator blocks until chunks arrive or None sentinel is pushed.
        def pcm_generator():
            while True:
                chunk = audio_q.get()
                if chunk is None:
                    break
                yield chunk

        state_machine.on_audio_stream_start(pcm_generator(), sid)

    def on_audio_chunk(self, data):
        """
        PCM chunk (base64-encoded Int16 bytes) from AudioWorklet.
        Puts decoded bytes into the session queue — the generator in
        pcm_generator() will yield it to Google streaming STT.
        """
        sid = request.sid
        audio_q = _audio_queues.get(sid)
        if audio_q is None:
            logger.warning(f'[/message] audio_chunk from {sid} with no active queue — ignoring')
            return

        b64_data = data.get('data', '') if isinstance(data, dict) else ''
        if not b64_data:
            return

        try:
            import base64
            raw_bytes = base64.b64decode(b64_data)
            audio_q.put(raw_bytes)
        except Exception as e:
            logger.warning(f'[/message] Failed to decode audio_chunk: {e}')

    def on_audio_stream_end(self, data):
        """
        Browser signals end of stream.
        Sends None sentinel to unblock the generator → Google STT finalizes.
        """
        sid = request.sid
        logger.info(f'[/message] audio_stream_end from {sid}')

        audio_q = _audio_queues.get(sid)
        if audio_q:
            audio_q.put(None)  # sentinel → generator stops
        # Queue entry remains until STT thread finishes; cleaned on disconnect or next stream_start

    # ── Legacy audio blob handler (kept for backwards compatibility) ──────────

    def on_client_message(self, data):
        """
        Message from user — text only (legacy audio blob path removed in favour
        of streaming PCM pipeline). Text path is kept for manual chat input.
        """
        if not isinstance(data, dict):
            logger.warning(f'[/message] Unexpected client_message format: {type(data)}')
            return

        msg_type = data.get('type', '')

        if msg_type == 'audio':
            # Legacy blob path — kept as fallback if worklet unavailable
            audio_b64 = data.get('data', '')
            if audio_b64:
                logger.info(f'[/message] Legacy audio blob received from {request.sid}')
                state_machine.on_audio_message(audio_b64, request.sid)
            else:
                logger.warning('[/message] Audio message with empty data')

        elif msg_type in ('client_message', 'text'):
            text = data.get('text', '').strip()
            if text:
                logger.info(f'[/message] Text received from {request.sid}: "{text}"')
                emit('client_message', {'text': text, 'sender': 'client'}, broadcast=True)
                state_machine.on_text_message(text, request.sid)

        else:
            text = data.get('text', '').strip()
            if text:
                state_machine.on_text_message(text, request.sid)

    # ── Face / TTS events ─────────────────────────────────────────────────────

    def on_user_detected(self, data):
        """Face detected by FaceDetection.jsx."""
        logger.info(f'[/message] user_detected from {request.sid}: {data}')
        state_machine.on_user_detected(data or {})

    def on_user_lost(self, data):
        """Face lost by FaceDetection.jsx."""
        logger.info(f'[/message] user_lost from {request.sid}')
        state_machine.on_user_lost(data or {})

    def on_tts_complete(self, data):
        """Frontend finished playing TTS audio."""
        logger.info(f'[/message] tts_complete from {request.sid}')
        state_machine.on_tts_complete(request.sid)

    def on_transcription_result(self, data):
        """Browser-side STT result (text already transcribed) — legacy fallback."""
        text = data.get('text', '').strip() if isinstance(data, dict) else str(data).strip()
        if text:
            logger.info(f'[/message] transcription_result: "{text}"')
            emit('client_message', {'text': text, 'sender': 'client'}, broadcast=True)
            state_machine.on_text_message(text, request.sid)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _cleanup_audio_queue(sid: str):
    """Drain and remove the audio queue for a session."""
    audio_q = _audio_queues.pop(sid, None)
    if audio_q:
        # Send sentinel so any blocked generator exits cleanly
        audio_q.put(None)
        logger.debug(f'Audio queue cleaned up for {sid}')