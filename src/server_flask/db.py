"""
db.py

Small Postgres helper layer for persistent auth and chat data.

The application expects DATABASE_URL to point to a Postgres database,
such as a Neon pooled connection string. The required tables are created
automatically on first use.
"""

import logging
import os
import threading
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()

logger = logging.getLogger("DB")

_schema_lock = threading.Lock()
_schema_ready = False


def _get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return database_url


@contextmanager
def get_db_connection():
    with psycopg.connect(
        _get_database_url(),
        autocommit=True,
        row_factory=dict_row,
    ) as conn:
        yield conn


def ensure_schema():
    global _schema_ready

    if _schema_ready:
        return

    with _schema_lock:
        if _schema_ready:
            return

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    create table if not exists users (
                        username text primary key,
                        password_hash text not null,
                        created_at timestamptz not null default now()
                    )
                    """
                )
                cur.execute(
                    """
                    create table if not exists chat_messages (
                        id bigserial primary key,
                        user_id text not null references users(username) on delete cascade,
                        role text not null check (role in ('user', 'assistant')),
                        content text not null,
                        created_at timestamptz not null default now()
                    )
                    """
                )
                cur.execute(
                    """
                    create index if not exists chat_messages_user_created_idx
                    on chat_messages(user_id, created_at, id)
                    """
                )

        _schema_ready = True
        logger.info("Database schema ready")
