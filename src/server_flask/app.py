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
from flask_cors import CORS
from flask_socketio import SocketIO
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from auth import get_shara_name, register_user, user_exists, verify_user

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger('App')

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

AUTH_COOKIE_NAME = 'shara_auth'
AUTH_COOKIE_SALT = 'shara-auth-cookie'
AUTH_COOKIE_MAX_AGE_SECONDS = int(
    os.getenv('AUTH_COOKIE_MAX_AGE_SECONDS', str(30 * 24 * 60 * 60))
)
AUTH_COOKIE_SAMESITE = os.getenv('AUTH_COOKIE_SAMESITE', 'Lax')
AUTH_COOKIE_SECURE = os.getenv('AUTH_COOKIE_SECURE', 'auto').strip().lower()
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        'FRONTEND_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173',
    ).split(',')
    if origin.strip()
]

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'shara-woz-secret')

CORS(
    app,
    supports_credentials=True,
    resources={r'/api/*': {'origins': FRONTEND_ORIGINS}},
)

socketio = SocketIO(
    app,
    cors_allowed_origins='*',
    async_mode='gevent',
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25,
)

_auth_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt=AUTH_COOKIE_SALT)

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


def _should_use_secure_cookie():
    if AUTH_COOKIE_SECURE in ('1', 'true', 'yes', 'on'):
        return True

    if AUTH_COOKIE_SECURE in ('0', 'false', 'no', 'off'):
        return False

    forwarded_proto = (request.headers.get('X-Forwarded-Proto') or '').split(',')[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto == 'https'

    if request.is_secure:
        return True

    host = request.host.split(':', 1)[0].strip().lower()
    return host not in ('localhost', '127.0.0.1')


def _clear_auth_cookie(response):
    response.set_cookie(
        AUTH_COOKIE_NAME,
        '',
        max_age=0,
        expires=0,
        httponly=True,
        secure=_should_use_secure_cookie(),
        samesite=AUTH_COOKIE_SAMESITE,
        path='/',
    )
    return response


def _disable_auth_caching(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def _set_auth_cookie(response, login_name: str):
    token = _auth_serializer.dumps({'loginName': login_name})
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=AUTH_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=_should_use_secure_cookie(),
        samesite=AUTH_COOKIE_SAMESITE,
        path='/',
    )
    return response


def _build_auth_payload(login_name: str):
    return {
        'loginName': login_name,
        'sharaName': get_shara_name(login_name),
        'isNewUser': False,
    }


def _get_authenticated_login_name():
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None

    try:
        payload = _auth_serializer.loads(token, max_age=AUTH_COOKIE_MAX_AGE_SECONDS)
    except SignatureExpired:
        logger.info('Auth cookie expired')
        return None
    except BadSignature:
        logger.warning('Invalid auth cookie signature')
        return None

    login_name = (payload.get('loginName') if isinstance(payload, dict) else '') or ''
    login_name = login_name.strip()

    if not login_name or not user_exists(login_name):
        logger.info('Auth cookie rejected for missing user: %s', login_name or '<empty>')
        return None

    return login_name


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json(silent=True) or {}
    login_name = (data.get('loginName') or '').strip()
    password = data.get('password', '')

    if not login_name or not password:
        return jsonify({'error': 'Nombre de usuario y contrasena requeridos'}), 400

    if not verify_user(login_name, password):
        return jsonify({'error': 'Usuario o contrasena incorrectos'}), 401

    logger.info('Login successful: %s', login_name)
    response = _disable_auth_caching(jsonify(_build_auth_payload(login_name)))
    return _set_auth_cookie(response, login_name)


@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    data = request.get_json(silent=True) or {}
    login_name = (data.get('loginName') or '').strip()
    password = data.get('password', '')

    if not login_name or not password:
        return jsonify({'error': 'Nombre de usuario y contrasena requeridos'}), 400

    if len(password) < 4:
        return jsonify({'error': 'La contrasena debe tener al menos 4 caracteres'}), 400

    if not register_user(login_name, password):
        return jsonify({'error': 'El usuario ya existe'}), 409

    logger.info('Registration successful: %s', login_name)
    response = _disable_auth_caching(jsonify({'loginName': login_name, 'sharaName': None, 'isNewUser': True}))
    response.status_code = 201
    return _set_auth_cookie(response, login_name)


@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    login_name = _get_authenticated_login_name()
    if not login_name:
        response = _disable_auth_caching(jsonify({'error': 'No authenticated session'}))
        response.status_code = 401
        return _clear_auth_cookie(response)

    logger.info('Session restored: %s', login_name)
    return _disable_auth_caching(jsonify(_build_auth_payload(login_name)))


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    login_name = _get_authenticated_login_name()
    if login_name:
        logger.info('Logout successful: %s', login_name)
    else:
        logger.info('Logout requested without active session')

    response = _disable_auth_caching(jsonify({'ok': True}))
    return _clear_auth_cookie(response)


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
    except Exception as exc:
        logger.error(f'TTS synthesis error: {exc}')
        return jsonify({'error': str(exc)}), 500


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
    except Exception as exc:
        logger.error(f'Face recognition compatibility error: {exc}', exc_info=True)
        return jsonify({'error': str(exc)}), 500


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
