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
from subject_codes import is_valid_subject_code, normalize_subject_code, parse_subject_codes
from user_roles import STUDENT_USER_ROLE, normalize_user_role

logger = logging.getLogger("Auth")

auth_bp = Blueprint("auth", __name__)

JWT_SECRET = os.getenv("JWT_SECRET", "shara-jwt-secret-change-in-prod")
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "8"))

USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,20}$")
MIN_PASSWORD_LEN = 6


def _issue_token(user_id: str, role: str, subject_code: str) -> str:
    return jwt.encode(
        {
            "user_id": user_id,
            "role": normalize_user_role(role),
            "subject_code": normalize_subject_code(subject_code),
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
                select username, password_hash, role, created_at
                from users
                where username = %s
                """,
                (username,),
            )
            return cur.fetchone()


def _create_user(username: str, password_hash: str, role: str = STUDENT_USER_ROLE) -> bool:
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into users (username, password_hash, role)
                values (%s, %s, %s)
                on conflict (username) do nothing
                returning username
                """,
                (username, password_hash, normalize_user_role(role)),
            )
            return cur.fetchone() is not None


def _create_subjects(subject_codes: list[str]):
    if not subject_codes:
        return

    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for subject_code in subject_codes:
                cur.execute(
                    """
                    insert into subjects (code)
                    values (%s)
                    on conflict (code) do nothing
                    """,
                    (subject_code,),
                )


def _assign_subjects(username: str, subject_codes: list[str]):
    if not subject_codes:
        return

    _create_subjects(subject_codes)

    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for subject_code in subject_codes:
                cur.execute(
                    """
                    insert into user_subjects (user_id, subject_code)
                    values (%s, %s)
                    on conflict (user_id, subject_code) do nothing
                    """,
                    (username, subject_code),
                )


def _fetch_user_subjects(username: str) -> list[str]:
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select subject_code
                from user_subjects
                where user_id = %s
                order by subject_code asc
                """,
                (username,),
            )
            return [row["subject_code"] for row in cur.fetchall()]


def _user_has_subject(username: str, subject_code: str) -> bool:
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from user_subjects
                where user_id = %s and subject_code = %s
                """,
                (username, subject_code),
            )
            return cur.fetchone() is not None


def _extract_bearer_token() -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    if not auth_header:
        return ""

    prefix = "bearer "
    if not auth_header.lower().startswith(prefix):
        return ""

    return auth_header[len(prefix):].strip()


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    subject_code = normalize_subject_code(data.get("subject_code"))

    if not username or not password or not subject_code:
        return jsonify({"error": "Usuario, contrasena y asignatura requeridos"}), 400

    if not is_valid_subject_code(subject_code):
        return jsonify({"error": "Codigo de asignatura invalido"}), 400

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

    try:
        has_subject = _user_has_subject(username, subject_code)
        user_subjects = _fetch_user_subjects(username)
    except psycopg.Error:
        logger.exception("[Auth] Database error loading user subjects during login")
        return jsonify({"error": "Servicio de autenticacion no disponible"}), 500

    if not has_subject:
        return jsonify({"error": "No tienes acceso a esa asignatura"}), 403

    user_role = normalize_user_role(user.get("role"))
    logger.info(f"[Auth] Login successful: {username} ({subject_code})")
    return jsonify({
        "token": _issue_token(username, user_role, subject_code),
        "user_id": username,
        "role": user_role,
        "subject_code": subject_code,
        "subject_codes": user_subjects,
    })


@auth_bp.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    raw_subject_codes = data.get("subject_codes", data.get("subject_code"))
    subject_codes = parse_subject_codes(raw_subject_codes)

    if not username or not password or not subject_codes:
        return jsonify({"error": "Usuario, contrasena y asignatura requeridos"}), 400

    if not USERNAME_RE.match(username):
        return jsonify({"error": "Usuario: 3-20 caracteres, solo letras, numeros, _ o -"}), 400

    if len(password) < MIN_PASSWORD_LEN:
        return jsonify({"error": f"La contrasena debe tener al menos {MIN_PASSWORD_LEN} caracteres"}), 400

    if any(not is_valid_subject_code(subject_code) for subject_code in subject_codes):
        return jsonify({"error": "Codigo de asignatura invalido"}), 400

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
        created = _create_user(username, password_hash, STUDENT_USER_ROLE)
        if created:
            _assign_subjects(username, subject_codes)
    except psycopg.Error:
        logger.exception("[Auth] Database error during registration")
        return jsonify({"error": "Servicio de autenticacion no disponible"}), 500

    if not created:
        return jsonify({"error": "El nombre de usuario ya esta en uso"}), 409

    logger.info(f"[Auth] Registered new user: {username}")
    return jsonify({
        "token": _issue_token(username, STUDENT_USER_ROLE, subject_codes[0]),
        "user_id": username,
        "role": STUDENT_USER_ROLE,
        "subject_code": subject_codes[0],
        "subject_codes": subject_codes,
    }), 201


@auth_bp.route("/auth/subjects", methods=["POST"])
def add_subjects():
    token = _extract_bearer_token()
    auth_context = verify_token(token) if token else None
    if not auth_context:
        return jsonify({"error": "Sesion no valida"}), 401

    data = request.get_json(silent=True) or {}
    raw_subject_codes = data.get("subject_codes", data.get("subject_code"))
    subject_codes = parse_subject_codes(raw_subject_codes)

    if not subject_codes:
        return jsonify({"error": "Debes indicar al menos una asignatura"}), 400

    if any(not is_valid_subject_code(subject_code) for subject_code in subject_codes):
        return jsonify({"error": "Codigo de asignatura invalido"}), 400

    user_id = auth_context["user_id"]

    try:
        previous_subjects = set(_fetch_user_subjects(user_id))
        _assign_subjects(user_id, subject_codes)
        updated_subjects = _fetch_user_subjects(user_id)
    except psycopg.Error:
        logger.exception("[Auth] Database error while adding subjects")
        return jsonify({"error": "Servicio de autenticacion no disponible"}), 500

    added_subjects = [subject_code for subject_code in updated_subjects if subject_code not in previous_subjects]
    logger.info("[Auth] Added subjects for %s: %s", user_id, ", ".join(added_subjects) or "none")

    return jsonify({
        "user_id": user_id,
        "role": auth_context["role"],
        "subject_code": auth_context["subject_code"],
        "subject_codes": updated_subjects,
        "added_subject_codes": added_subjects,
    })


def verify_token(token: str) -> dict[str, str] | None:
    """Decode JWT and return auth context, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = str(payload.get("user_id", "")).strip().lower()
        subject_code = normalize_subject_code(payload.get("subject_code"))
        if not user_id:
            return None
        if not is_valid_subject_code(subject_code):
            return None

        role = payload.get("role")
        if role is None:
            try:
                user = _fetch_user(user_id)
            except psycopg.Error:
                logger.exception("[Auth] Database error during token verification")
                user = None
            role = user.get("role") if user else None

        try:
            if not _user_has_subject(user_id, subject_code):
                return None
        except psycopg.Error:
            logger.exception("[Auth] Database error validating subject membership during token verification")
            return None

        return {
            "user_id": user_id,
            "role": normalize_user_role(role),
            "subject_code": subject_code,
        }
    except jwt.InvalidTokenError:
        return None
