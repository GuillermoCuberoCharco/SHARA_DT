#!/usr/bin/env python3
"""
migrate_users_json.py

Import legacy users from files/users.json into Postgres.

Usage:
    python migrate_users_json.py
    python migrate_users_json.py path/to/users.json
"""

import json
import os
import sys

import psycopg

from db import ensure_schema, get_db_connection

DEFAULT_USERS_FILE = os.path.join(os.path.dirname(__file__), "files", "users.json")


def main():
    users_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_USERS_FILE

    if not os.path.exists(users_file):
        print(f"Error: no existe el fichero {users_file}")
        sys.exit(1)

    try:
        with open(users_file, "r", encoding="utf-8") as f:
            users = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"Error leyendo JSON: {exc}")
        sys.exit(1)

    if not isinstance(users, dict):
        print("Error: el JSON de usuarios debe ser un objeto")
        sys.exit(1)

    migrated = 0

    try:
        ensure_schema()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for username, payload in users.items():
                    normalized_username = str(username).strip().lower()
                    password_hash = (payload or {}).get("password_hash")

                    if not normalized_username or not password_hash:
                        continue

                    cur.execute(
                        """
                        insert into users (username, password_hash)
                        values (%s, %s)
                        on conflict (username) do update
                        set password_hash = excluded.password_hash
                        """,
                        (normalized_username, password_hash),
                    )
                    migrated += 1
    except psycopg.Error as exc:
        print(f"Error conectando con Postgres: {exc}")
        sys.exit(1)

    print(f"Migrados {migrated} usuarios a Postgres")


if __name__ == "__main__":
    main()
