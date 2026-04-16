"""
auth.py

User authentication utilities for SHARA.
Backed by PostgreSQL (Neon) via psycopg2.
Passwords are hashed with werkzeug.security (Flask dependency — no extra install needed).
"""

import logging

import psycopg2
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_connection

logger = logging.getLogger('Auth')


def user_exists(login_name: str) -> bool:
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM users WHERE login_name = %s', (login_name.strip(),))
            return cur.fetchone() is not None
    finally:
        if conn:
            conn.close()


def register_user(login_name: str, password: str) -> bool:
    """
    Register a new user.
    Returns True on success, False if login_name is already taken.
    """
    login_name = login_name.strip()
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO users (login_name, password_hash) VALUES (%s, %s)',
                (login_name, generate_password_hash(password)),
            )
        conn.commit()
        logger.info('New user registered: %s', login_name)
        return True
    except psycopg2.errors.UniqueViolation:
        if conn:
            conn.rollback()
        logger.info('Registration rejected — user already exists: %s', login_name)
        return False
    except Exception as exc:
        if conn:
            conn.rollback()
        logger.error('Registration error for %s: %s', login_name, exc)
        return False
    finally:
        if conn:
            conn.close()


def verify_user(login_name: str, password: str) -> bool:
    """
    Verify login credentials.
    Returns True if login_name exists and password matches.
    """
    login_name = login_name.strip()
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                'SELECT password_hash FROM users WHERE login_name = %s',
                (login_name,),
            )
            row = cur.fetchone()
    finally:
        if conn:
            conn.close()

    if not row:
        logger.info('Login failed — unknown user: %s', login_name)
        return False

    ok = check_password_hash(row[0], password)
    if not ok:
        logger.info('Login failed — wrong password for: %s', login_name)
    return ok


def get_shara_name(login_name: str):
    """
    Return the Shara display name for this user (e.g. 'María'), or None if not set yet.
    This is the name Shara uses to address the person, which may differ from login_name.
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                'SELECT shara_name FROM users WHERE login_name = %s',
                (login_name.strip(),),
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else None
    except Exception as exc:
        logger.error('Error fetching shara_name for %s: %s', login_name, exc)
        return None
    finally:
        if conn:
            conn.close()


def update_shara_name(login_name: str, shara_name: str) -> None:
    """
    Persist the Shara display name for this user.
    Called when the user introduces themselves to Shara during conversation.
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE users SET shara_name = %s WHERE login_name = %s',
                (shara_name, login_name.strip()),
            )
        conn.commit()
        logger.info('shara_name updated: %s → %s', login_name, shara_name)
    except Exception as exc:
        if conn:
            conn.rollback()
        logger.error('Error updating shara_name for %s: %s', login_name, exc)
    finally:
        if conn:
            conn.close()
