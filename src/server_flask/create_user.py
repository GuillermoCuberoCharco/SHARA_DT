#!/usr/bin/env python3
"""
create_user.py

CLI utility to create or update users in Postgres.

Usage:
    python create_user.py <username> <password> [student|teacher] <subject_codes>

Example:
    python create_user.py admin shara2024 teacher mat101,mat102
    python create_user.py alice mipassword mat101
"""

import sys
import re

import bcrypt
import psycopg

from db import ensure_schema, get_db_connection
from subject_codes import is_valid_subject_code, parse_subject_codes
from user_roles import STUDENT_USER_ROLE, VALID_USER_ROLES, normalize_user_role

USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,20}$")
MIN_PASSWORD_LEN = 6


def main():
    if len(sys.argv) not in {4, 5}:
        print(f"Uso: python {sys.argv[0]} <usuario> <contrasena> [student|teacher] <subject_codes>")
        sys.exit(1)

    username = sys.argv[1].strip().lower()
    password = sys.argv[2]
    extra_args = sys.argv[3:]
    role_arg = STUDENT_USER_ROLE
    subject_codes_arg = ""

    if len(extra_args) == 1:
        candidate = extra_args[0].strip().lower()
        if candidate in VALID_USER_ROLES:
            print("Error: debes indicar al menos una asignatura")
            sys.exit(1)
        subject_codes_arg = extra_args[0]
    elif len(extra_args) == 2:
        role_arg = extra_args[0].strip().lower()
        subject_codes_arg = extra_args[1]

    if not username or not password:
        print("Error: usuario y contrasena no pueden estar vacios")
        sys.exit(1)

    if not USERNAME_RE.match(username):
        print("Error: usuario invalido. Usa 3-20 caracteres: letras, numeros, _ o -")
        sys.exit(1)

    if len(password) < MIN_PASSWORD_LEN:
        print(f"Error: la contrasena debe tener al menos {MIN_PASSWORD_LEN} caracteres")
        sys.exit(1)

    if role_arg not in VALID_USER_ROLES:
        print("Error: rol invalido. Usa 'student' o 'teacher'")
        sys.exit(1)

    subject_codes = parse_subject_codes(subject_codes_arg)
    if not subject_codes:
        print("Error: debes indicar al menos una asignatura")
        sys.exit(1)

    if any(not is_valid_subject_code(subject_code) for subject_code in subject_codes):
        print("Error: codigo de asignatura invalido")
        sys.exit(1)

    role = normalize_user_role(role_arg)
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
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

                cur.execute(
                    """
                    select 1, role
                    from users
                    where username = %s
                    """,
                    (username,),
                )
                is_update = cur.fetchone() is not None

                cur.execute(
                    """
                    insert into users (username, password_hash, role)
                    values (%s, %s, %s)
                    on conflict (username) do update
                    set password_hash = excluded.password_hash,
                        role = excluded.role
                    """,
                    (username, password_hash, role),
                )

                for subject_code in subject_codes:
                    cur.execute(
                        """
                        insert into user_subjects (user_id, subject_code)
                        values (%s, %s)
                        on conflict (user_id, subject_code) do nothing
                        """,
                        (username, subject_code),
                    )
    except psycopg.Error as exc:
        print(f"Error conectando con Postgres: {exc}")
        sys.exit(1)

    action = "Actualizado" if is_update else "Creado"
    print(f"{action} usuario: {username} ({role}) -> {', '.join(subject_codes)}")


if __name__ == "__main__":
    main()
