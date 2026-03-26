#!/usr/bin/env python3
"""
create_user.py

CLI utility to create or update users in Postgres.

Usage:
    python create_user.py <username> <password>

Example:
    python create_user.py admin shara2024
    python create_user.py alice mipassword
"""

import sys
import re

import bcrypt
import psycopg

from db import ensure_schema, get_db_connection

USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,20}$")
MIN_PASSWORD_LEN = 6


def main():
    if len(sys.argv) != 3:
        print(f"Uso: python {sys.argv[0]} <usuario> <contrasena>")
        sys.exit(1)

    username = sys.argv[1].strip().lower()
    password = sys.argv[2]

    if not username or not password:
        print("Error: usuario y contrasena no pueden estar vacios")
        sys.exit(1)

    if not USERNAME_RE.match(username):
        print("Error: usuario invalido. Usa 3-20 caracteres: letras, numeros, _ o -")
        sys.exit(1)

    if len(password) < MIN_PASSWORD_LEN:
        print(f"Error: la contrasena debe tener al menos {MIN_PASSWORD_LEN} caracteres")
        sys.exit(1)

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
        ensure_schema()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select 1
                    from users
                    where username = %s
                    """,
                    (username,),
                )
                is_update = cur.fetchone() is not None

                cur.execute(
                    """
                    insert into users (username, password_hash)
                    values (%s, %s)
                    on conflict (username) do update
                    set password_hash = excluded.password_hash
                    """,
                    (username, password_hash),
                )
    except psycopg.Error as exc:
        print(f"Error conectando con Postgres: {exc}")
        sys.exit(1)

    action = "Actualizado" if is_update else "Creado"
    print(f"{action} usuario: {username}")


if __name__ == "__main__":
    main()
