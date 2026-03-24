"""
auth.py

Authentication blueprint — POST /auth/login, POST /auth/register + JWT utilities.

Users are stored in files/users.json:
    {
        "username": { "password_hash": "<bcrypt hash>" }
    }

Use create_user.py to add/update users from the CLI.

Environment variables:
    JWT_SECRET         — signing secret (change in production!)
    JWT_EXPIRY_HOURS   — token lifetime in hours (default: 8)
"""

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from flask import Blueprint, jsonify, request

logger = logging.getLogger('Auth')

auth_bp = Blueprint('auth', __name__)

JWT_SECRET = os.getenv('JWT_SECRET', 'shara-jwt-secret-change-in-prod')
JWT_EXPIRY_HOURS = int(os.getenv('JWT_EXPIRY_HOURS', '8'))
USERS_FILE = os.path.join(os.path.dirname(__file__), 'files', 'users.json')

USERNAME_RE = re.compile(r'^[a-z0-9_-]{3,20}$')
MIN_PASSWORD_LEN = 6

_file_lock = threading.Lock()


def _load_users() -> dict:
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_users(users: dict):
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def _issue_token(user_id: str) -> str:
    return jwt.encode(
        {
            'user_id': user_id,
            'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        },
        JWT_SECRET,
        algorithm='HS256',
    )


@auth_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'Usuario y contraseña requeridos'}), 400

    users = _load_users()
    user = users.get(username)

    if not user or not bcrypt.checkpw(
        password.encode('utf-8'),
        user['password_hash'].encode('utf-8'),
    ):
        logger.warning(f'[Auth] Failed login attempt for: {username}')
        return jsonify({'error': 'Credenciales incorrectas'}), 401

    logger.info(f'[Auth] Login successful: {username}')
    return jsonify({'token': _issue_token(username), 'user_id': username})


@auth_bp.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'Usuario y contraseña requeridos'}), 400

    if not USERNAME_RE.match(username):
        return jsonify({'error': 'Usuario: 3-20 caracteres, solo letras, números, _ o -'}), 400

    if len(password) < MIN_PASSWORD_LEN:
        return jsonify({'error': f'La contraseña debe tener al menos {MIN_PASSWORD_LEN} caracteres'}), 400

    with _file_lock:
        users = _load_users()

        if username in users:
            return jsonify({'error': 'El nombre de usuario ya está en uso'}), 409

        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        users[username] = {'password_hash': password_hash}
        _save_users(users)

    logger.info(f'[Auth] Registered new user: {username}')
    return jsonify({'token': _issue_token(username), 'user_id': username}), 201


def verify_token(token: str) -> str | None:
    """Decode JWT and return user_id, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return payload.get('user_id')
    except jwt.InvalidTokenError:
        return None
