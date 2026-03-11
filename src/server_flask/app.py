"""
app.py

Flask-SocketIO server — single-service deployment on Render.
Flask serves both the React frontend (static build) and the WebSocket API.

Since frontend and backend share the same origin, CORS is not needed.

Architecture:
    /message   namespace — conversation (audio, text, face events)
    /video     namespace — video stream from browser
    /animation namespace — eye animation frames relay (Python → Web)
    /*                   — serves React SPA static build
"""

# ── Gevent monkey-patch — MUST be first, before any other import ──────────────
# This patches stdlib queue.Queue so it works correctly across greenlets and
# native threads (ThreadPoolExecutor). Without this, put() from a greenlet
# does not wake up a thread blocked in get(), breaking the PCM streaming pipeline.
from gevent import monkey
monkey.patch_all()

import base64
import json
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import Namespace, SocketIO

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger('App')

# ── Flask app — static folder points to React build output ────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'shara-woz-secret')

# ── Socket.IO — same origin, no CORS needed ───────────────────────────────────
socketio = SocketIO(
    app,
    cors_allowed_origins='*',   # same-origin in production; '*' for local dev
    async_mode='gevent',
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25,
)

# ── Services ──────────────────────────────────────────────────────────────────
from eyes.service import Eyes

eyes = Eyes(socketio_instance=socketio)

from services.cloud import server as cloud_server
from services.camera_service import recognize_face_with_batch
from proactive_service import ProactiveService
import state_machine

proactive = ProactiveService(callback=state_machine.proactive_event_handler)

state_machine.init(
    socketio_instance=socketio,
    server_module=cloud_server,
    eyes_instance=eyes,
    proactive_instance=proactive,
)

# ── Socket namespaces ─────────────────────────────────────────────────────────
from sockets.message_handler import MessageNamespace
from sockets.video_handler import VideoNamespace


socketio.on_namespace(MessageNamespace('/message'))
socketio.on_namespace(VideoNamespace('/video'))

logger.info('Namespaces registered: /message, /video, /animation')

@app.route('/health')
def health():
    return {'status': 'ok', 'robot_state': state_machine.robot_context.state}


@app.route('/api/synthesize', methods=['POST'])
def synthesize():
    data = request.get_json(silent=True) or {}
    text = data.get('text', '').strip()

    if not text:
        return jsonify({'error': 'No text provided'}), 400

    try:
        from services.cloud.google_api import text_to_speech
        audio_bytes = text_to_speech(text)
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        return jsonify({'audioContent': audio_b64})
    except Exception as e:
        logger.error(f'TTS synthesis error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/recognize-face', methods=['POST'])
def recognize_face():
    """
    Batch face recognition endpoint.
    Receives multipart images in field 'faces'.
    """
    try:
        files = request.files.getlist('faces')
        if not files:
            return jsonify({'error': 'No face images provided in batch.'}), 400

        face_buffers = []
        for file in files[:10]:
            data = file.read()
            if data:
                face_buffers.append(data)

        if not face_buffers:
            return jsonify({'error': 'Invalid or empty image files.'}), 400

        known_user_id = request.form.get('userId') or None
        client_id = request.form.get('clientId') or request.headers.get('X-Client-Id') or 'client_web'
        session_id = request.form.get('sessionId') or f'session_{client_id}'
        descriptors_raw = request.form.get('descriptors')
        descriptors = None
        if descriptors_raw:
            try:
                parsed = json.loads(descriptors_raw)
                if isinstance(parsed, list):
                    descriptors = parsed
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning('Invalid descriptors payload, falling back to image-based extraction')

        result = recognize_face_with_batch(
            face_buffers,
            session_id,
            known_user_id,
            descriptors=descriptors,
        )
        if result.get('error'):
            return jsonify({'error': result['error']}), 500

        user_status = 'existing'
        if result.get('isUncertain'):
            user_status = 'uncertain'
        elif result.get('isNewUser'):
            user_status = 'new_unknown'
        elif result.get('needsIdentification'):
            user_status = 'existing_unknown'

        response = {
            'userId': result.get('userId', 'unknown'),
            'userName': result.get('userName', 'unknown'),
            'isNewUser': bool(result.get('isNewUser', False)),
            'needsIdentification': bool(result.get('needsIdentification', True)),
            'userStatus': user_status,
            'sessionId': session_id,
            'clientId': client_id,
            'batchSize': len(face_buffers),
            'isUncertain': bool(result.get('isUncertain', False)),
            'isConfirmed': bool(result.get('isConfirmed', False)),
            'consensusRatio': result.get('consensusRatio'),
            'confidence': result.get('confidence'),
            'avgDistance': result.get('distance'),
            'detectionProgress': result.get('detectionProgress'),
            'totalRequired': result.get('totalRequired'),
        }
        return jsonify(response)
    except Exception as e:
        logger.error(f'Face recognition error: {e}', exc_info=True)
        return jsonify({'error': str(e)}), 500


# ── React SPA — catch-all serves index.html for client-side routing ───────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    if path and os.path.exists(os.path.join(STATIC_DIR, path)):
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, 'index.html')

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.getenv('PORT', 8081))
    logger.info(f'Starting SHARA server on port {port}')
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
