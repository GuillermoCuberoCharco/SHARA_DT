"""
db.py

PostgreSQL connection management for SHARA.
Connection URL is read from the DATABASE_URL environment variable
(provided by Neon: postgresql://user:pass@host/db?sslmode=require).

Schema
------
users
    login_name    VARCHAR(255) PK   — login identifier (≠ Shara display name)
    password_hash TEXT              — werkzeug-hashed password
    created_at    TIMESTAMPTZ       — registration timestamp

conversation_messages
    id            SERIAL PK
    login_name    VARCHAR(255)      — foreign key to users.login_name
    role          VARCHAR(20)       — 'user' | 'assistant'
    content       TEXT              — raw message content
    session_id    VARCHAR(255)      — groups messages from the same interaction session
    created_at    TIMESTAMPTZ       — message timestamp (used to reconstruct order)

Indexes on (login_name) and (session_id) cover the main query patterns.
"""

import logging
import os

import psycopg2

logger = logging.getLogger('DB')

# ── Connection ────────────────────────────────────────────────────────────────

def get_connection():
    """
    Open and return a new psycopg2 connection.
    Always close it explicitly (or use a try/finally block) after use —
    psycopg2 connections are not context-manager-closable by default.
    """
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise RuntimeError(
            'DATABASE_URL environment variable is not set. '
            'Add it to your .env file or Render environment.'
        )
    return psycopg2.connect(url)


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    login_name    VARCHAR(255) PRIMARY KEY,
    password_hash TEXT         NOT NULL,
    created_at    TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id          SERIAL       PRIMARY KEY,
    login_name  VARCHAR(255) NOT NULL,
    role        VARCHAR(20)  NOT NULL,
    content     TEXT         NOT NULL,
    session_id  VARCHAR(255),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_login   ON conversation_messages (login_name);
CREATE INDEX IF NOT EXISTS idx_conv_session ON conversation_messages (session_id);
"""


def init_schema():
    """
    Create tables and indexes if they don't exist.
    Idempotent — safe to call on every startup.
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)
        conn.commit()
        logger.info('Database schema initialised (or already up to date)')
    except Exception as exc:
        logger.error('Failed to initialise database schema: %s', exc)
        raise
    finally:
        if conn:
            conn.close()
