"""
auth.py

User authentication utilities for SHARA.
User credentials are stored in files/users_db.json.
Passwords are hashed with werkzeug.security (Flask dependency — no extra install needed).
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger('Auth')

_USERS_DB = Path(__file__).parent / 'files' / 'users_db.json'


def _load_users() -> dict:
    try:
        return json.loads(_USERS_DB.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_users(users: dict) -> None:
    _USERS_DB.write_text(
        json.dumps(users, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def user_exists(login_name: str) -> bool:
    return login_name.strip() in _load_users()


def register_user(login_name: str, password: str) -> bool:
    """
    Register a new user.
    Returns True on success, False if the login_name is already taken.
    """
    login_name = login_name.strip()
    users = _load_users()
    if login_name in users:
        logger.info('Registration rejected — user already exists: %s', login_name)
        return False

    users[login_name] = {
        'password_hash': generate_password_hash(password),
        'created_at': datetime.now().isoformat(),
    }
    _save_users(users)
    logger.info('New user registered: %s', login_name)
    return True


def verify_user(login_name: str, password: str) -> bool:
    """
    Verify login credentials.
    Returns True if login_name exists and password matches.
    """
    login_name = login_name.strip()
    users = _load_users()
    user = users.get(login_name)
    if not user:
        logger.info('Login failed — unknown user: %s', login_name)
        return False

    ok = check_password_hash(user['password_hash'], password)
    if not ok:
        logger.info('Login failed — wrong password for: %s', login_name)
    return ok
