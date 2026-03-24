"""
auth.py

Authentication blueprint — POST /auth/login + JWT utilities.

Users are stored in files/users.json:
    {
        "username": { "password_hash": "<bcrypt hash>" }
    }

Use create_user.py to add/update users.

Environment variables:
    JWT_SECRET         — signing secret (change in production!)
    JWT_EXPIRY_HOURS   — token lifetime in hours (default: 8)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from flask import Blueprint, jsonify, request

logger = logging.getLogger('Auth')

auth_bp = Blueprint('auth', __name__)

JWT_SECRET = os.getenv('JWT_SECRET', 'shara-jwt-secret-change-in-prod')
JWT_EXPIRY_HOURS = int(os.getenv('JWT_EXPIRY_HOURS', '8'))
USERS_FILE = os.path.join(os.path.dirname(__file__), 'files', 'users.json')


def _load_users() -> dict:
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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

    token = jwt.encode(
        {
            'user_id': username,
            'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        },
        JWT_SECRET,
        algorithm='HS256',
    )

    logger.info(f'[Auth] Login successful: {username}')
    return jsonify({'token': token, 'user_id': username})


def verify_token(token: str) -> str | None:
    """Decode JWT and return user_id, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return payload.get('user_id')
    except jwt.InvalidTokenError:
        return None
