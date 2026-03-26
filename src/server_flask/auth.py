"""
auth.py

Authentication blueprint: POST /auth/login, POST /auth/register + JWT
utilities backed by Postgres.

Users are persisted in the users table:
    users(username text primary key, password_hash text, created_at timestamptz)

Environment variables:
    DATABASE_URL       Postgres connection string
    JWT_SECRET         Signing secret (change in production)
    JWT_EXPIRY_HOURS   Token lifetime in hours (default: 8)
"""

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import psycopg
from flask import Blueprint, jsonify, request

from db import ensure_schema, get_db_connection

logger = logging.getLogger("Auth")

auth_bp = Blueprint("auth", __name__)

JWT_SECRET = os.getenv("JWT_SECRET", "shara-jwt-secret-change-in-prod")
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "8"))

USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,20}$")
MIN_PASSWORD_LEN = 6


def _issue_token(user_id: str) -> str:
    return jwt.encode(
        {
            "user_id": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _fetch_user(username: str):
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select username, password_hash, created_at
                from users
                where username = %s
                """,
                (username,),
            )
            return cur.fetchone()


def _create_user(username: str, password_hash: str) -> bool:
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into users (username, password_hash)
                values (%s, %s)
                on conflict (username) do nothing
                returning username
                """,
                (username, password_hash),
            )
            return cur.fetchone() is not None


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Usuario y contrasena requeridos"}), 400

    try:
        user = _fetch_user(username)
    except psycopg.Error:
        logger.exception("[Auth] Database error during login")
        return jsonify({"error": "Servicio de autenticacion no disponible"}), 500

    if not user or not bcrypt.checkpw(
        password.encode("utf-8"),
        user["password_hash"].encode("utf-8"),
    ):
        logger.warning(f"[Auth] Failed login attempt for: {username}")
        return jsonify({"error": "Credenciales incorrectas"}), 401

    logger.info(f"[Auth] Login successful: {username}")
    return jsonify({"token": _issue_token(username), "user_id": username})


@auth_bp.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Usuario y contrasena requeridos"}), 400

    if not USERNAME_RE.match(username):
        return jsonify({"error": "Usuario: 3-20 caracteres, solo letras, numeros, _ o -"}), 400

    if len(password) < MIN_PASSWORD_LEN:
        return jsonify({"error": f"La contrasena debe tener al menos {MIN_PASSWORD_LEN} caracteres"}), 400

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
        created = _create_user(username, password_hash)
    except psycopg.Error:
        logger.exception("[Auth] Database error during registration")
        return jsonify({"error": "Servicio de autenticacion no disponible"}), 500

    if not created:
        return jsonify({"error": "El nombre de usuario ya esta en uso"}), 409

    logger.info(f"[Auth] Registered new user: {username}")
    return jsonify({"token": _issue_token(username), "user_id": username}), 201


def verify_token(token: str) -> str | None:
    """Decode JWT and return user_id, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("user_id")
    except jwt.InvalidTokenError:
        return None
