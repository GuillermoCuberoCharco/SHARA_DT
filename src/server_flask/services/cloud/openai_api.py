"""
services/cloud/openai_api.py

OpenAI API wrapper. Handles conversation history and response generation.
"""
import json
from openai import OpenAI
from pydantic import BaseModel, Field

client = OpenAI()

conversation_history = []

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


def generate_response(input_text: str) -> tuple[str, str]:
    """
    Generate a response from OpenAI for the given user text.

    Returns:
        (response_text, robot_mood)
    """
    conversation_history.append({"role": "user", "content": input_text})

    completion_args = {
        "model": "gpt-4o-mini",
        "text_format": ResponseFormat,
        "temperature": 1,
        "top_p": 1,
        "instructions": system_prompt,
        "input": list(conversation_history),
        "truncation": "auto",
    }

    response = client.responses.parse(**completion_args)
    parsed = response.output_parsed

    response_text = parsed.response.translate(str.maketrans("'", '"', '*_#'))
    robot_mood = parsed.robot_mood or "neutral"

    conversation_history.append({"role": "assistant", "content": response_text})

    return response_text, robot_mood


def clear_conversation_history():
    conversation_history.clear()
