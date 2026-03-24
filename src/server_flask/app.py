"""
app.py

Flask-SocketIO server — text-only chat interface with JWT authentication.
Flask serves both the React frontend (static build) and the WebSocket/REST API.
"""

from gevent import monkey
monkey.patch_all()

import logging
import os

from dotenv import load_dotenv
from flask import Flask, send_from_directory
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

from auth import auth_bp
from services.cloud import server as cloud_server
import state_machine

app.register_blueprint(auth_bp)

state_machine.init(
    socketio_instance=socketio,
    server_module=cloud_server,
)

from sockets.message_handler import MessageNamespace

socketio.on_namespace(MessageNamespace('/message'))
logger.info('Namespace registered: /message')


@app.route('/health')
def health():
    return {'status': 'ok', 'active_queries': state_machine.get_active_users_count()}


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    if path and os.path.exists(os.path.join(STATIC_DIR, path)):
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, 'index.html')


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8081))
    logger.info(f'Starting server on port {port}')
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
