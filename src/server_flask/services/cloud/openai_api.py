"""
services/cloud/openai_api.py

OpenAI API wrapper. Maintains a separate conversation history per user.
"""
import threading
from openai import OpenAI
from pydantic import BaseModel, Field

client = OpenAI()

# Per-user conversation histories: { user_id: [{"role": ..., "content": ...}, ...] }
_histories: dict[str, list] = {}
_histories_lock = threading.Lock()

SYSTEM_PROMPT_FILE = "files/shara_prompt.txt"


def load_prompt(filename=SYSTEM_PROMPT_FILE):
    try:
        with open(filename, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        return "Eres un asistente conversacional útil y amigable."


system_prompt = load_prompt()


class ResponseFormat(BaseModel):
    robot_mood: str = Field(default="neutral")
    response: str


def generate_response(input_text: str, user_id: str) -> tuple[str, str]:
    """
    Generate a response from OpenAI for the given user.
    Each user maintains an independent conversation history.

    Returns:
        (response_text, robot_mood)
    """
    with _histories_lock:
        history = _histories.setdefault(user_id, [])
        history.append({"role": "user", "content": input_text})
        history_snapshot = list(history)

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

    with _histories_lock:
        history = _histories.setdefault(user_id, [])
        history.append({"role": "assistant", "content": response_text})

    return response_text, robot_mood


def clear_user_history(user_id: str):
    """Remove the conversation history for a specific user."""
    with _histories_lock:
        _histories.pop(user_id, None)
