"""
app.py

Flask-SocketIO server for the SHARA web deployment.
Flask serves both the React frontend build and the WebSocket API.
"""

from gevent import monkey
monkey.patch_all()

import base64
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from auth import get_shara_name, register_user, verify_user
from flask_socketio import SocketIO

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger('App')

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'shara-woz-secret')

socketio = SocketIO(
    app,
    cors_allowed_origins='*',
    async_mode='gevent',
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25,
)

from db import init_schema as _init_db_schema
from eyes.service import Eyes
from proactive_service import ProactiveService
from services.cloud import server as cloud_server
from sockets.message_handler import MessageNamespace
import state_machine

_init_db_schema()

eyes = Eyes(socketio_instance=socketio)
proactive = ProactiveService(callback=state_machine.proactive_event_handler)

state_machine.init(
    socketio_instance=socketio,
    server_module=cloud_server,
    eyes_instance=eyes,
    proactive_instance=proactive,
)

socketio.on_namespace(MessageNamespace('/message'))
logger.info('Namespace registered: /message')


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json(silent=True) or {}
    login_name = (data.get('loginName') or '').strip()
    password = data.get('password', '')

    if not login_name or not password:
        return jsonify({'error': 'Nombre de usuario y contraseña requeridos'}), 400

    if not verify_user(login_name, password):
        return jsonify({'error': 'Usuario o contraseña incorrectos'}), 401

    shara_name = get_shara_name(login_name)

    logger.info('Login successful: %s', login_name)
    return jsonify({'loginName': login_name, 'sharaName': shara_name, 'isNewUser': False})


@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    data = request.get_json(silent=True) or {}
    login_name = (data.get('loginName') or '').strip()
    password = data.get('password', '')

    if not login_name or not password:
        return jsonify({'error': 'Nombre de usuario y contraseña requeridos'}), 400

    if len(password) < 4:
        return jsonify({'error': 'La contraseña debe tener al menos 4 caracteres'}), 400

    if not register_user(login_name, password):
        return jsonify({'error': 'El usuario ya existe'}), 409

    logger.info('Registration successful: %s', login_name)
    return jsonify({'loginName': login_name, 'isNewUser': True}), 201


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
    Compatibility endpoint for older clients.
    Face recognition is now replaced by the initial session login.
    """
    try:
        client_id = request.form.get('clientId') or request.headers.get('X-Client-Id') or 'client_web'
        session_id = request.form.get('sessionId') or f'session_{client_id}'
        raw_username = (request.form.get('userName') or request.form.get('username') or '').strip()
        normalized_username = raw_username if raw_username and raw_username.lower() != 'unknown' else 'unknown'
        is_known_user = normalized_username != 'unknown'

        response = {
            'userName': normalized_username,
            'recognitionBackend': 'session_login',
            'isNewUser': not is_known_user,
            'needsIdentification': not is_known_user,
            'userStatus': 'existing' if is_known_user else 'new_unknown',
            'sessionId': session_id,
            'clientId': client_id,
            'batchSize': len(request.files.getlist('faces')),
            'isUncertain': False,
            'isConfirmed': True,
            'consensusRatio': 1,
            'confidence': 1,
            'avgDistance': 0,
            'pendingRecognition': False,
            'historyCount': None,
            'detectionProgress': None,
            'totalRequired': None,
        }

        logger.info(
            'Session identity compatibility endpoint used: client_id=%s session_id=%s username=%s',
            client_id,
            session_id,
            normalized_username,
        )
        return jsonify(response)
    except Exception as e:
        logger.error(f'Face recognition compatibility error: {e}', exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    if path and os.path.exists(os.path.join(STATIC_DIR, path)):
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, 'index.html')


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8081))
    logger.info(f'Starting SHARA server on port {port}')
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
