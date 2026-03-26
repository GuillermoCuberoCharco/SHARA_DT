"""
services/cloud/openai_api.py

OpenAI API wrapper. Maintains a separate conversation history per user
persisted in Postgres.
"""

from openai import OpenAI
from pydantic import BaseModel, Field

from db import ensure_schema, get_db_connection

client = OpenAI()

SYSTEM_PROMPT_FILE = "files/shara_prompt.txt"


def load_prompt(filename=SYSTEM_PROMPT_FILE):
    try:
        with open(filename, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        return "Eres un asistente conversacional util y amigable."


system_prompt = load_prompt()


class ResponseFormat(BaseModel):
    robot_mood: str = Field(default="neutral")
    response: str


def _load_user_history(user_id: str) -> list[dict[str, str]]:
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select role, content
                from chat_messages
                where user_id = %s
                order by created_at asc, id asc
                """,
                (user_id,),
            )
            return [
                {"role": row["role"], "content": row["content"]}
                for row in cur.fetchall()
            ]


def _store_message(user_id: str, role: str, content: str):
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into chat_messages (user_id, role, content)
                values (%s, %s, %s)
                """,
                (user_id, role, content),
            )


def load_user_messages(user_id: str) -> list[dict[str, str]]:
    """
    Return a user's persisted conversation in frontend-friendly format.
    """
    history = _load_user_history(user_id)
    messages = []
    for item in history:
        sender = "client" if item["role"] == "user" else "robot"
        messages.append({"text": item["content"], "sender": sender})
    return messages


def generate_response(input_text: str, user_id: str) -> tuple[str, str]:
    """
    Generate a response from OpenAI for the given user.
    Each user maintains an independent conversation history persisted in Postgres.

    Returns:
        (response_text, robot_mood)
    """
    history_snapshot = _load_user_history(user_id)
    history_snapshot.append({"role": "user", "content": input_text})

    completion_args = {
        "model": "gpt-4o-mini",
        "text_format": ResponseFormat,
        "temperature": 1,
        "top_p": 1,
        "instructions": system_prompt,
        "input": history_snapshot,
        "truncation": "auto",
    }

    response = client.responses.parse(**completion_args)
    parsed = response.output_parsed

    response_text = parsed.response.translate(str.maketrans("'", '"', '*_#'))
    robot_mood = parsed.robot_mood or "neutral"

    _store_message(user_id, "user", input_text)
    _store_message(user_id, "assistant", response_text)

    return response_text, robot_mood


def clear_user_history(user_id: str):
    """Remove the persisted conversation history for a specific user."""
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from chat_messages
                where user_id = %s
                """,
                (user_id,),
            )
