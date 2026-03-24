"""
services/cloud/server.py

Chat server module. Receives text input, calls OpenAI, returns text response.
"""

import logging
import time
from dataclasses import dataclass, field

from .openai_api import generate_response

logger = logging.getLogger('Server')


@dataclass
class Request:
    text: str = ''
    user_id: str = ''


@dataclass
class Response:
    request: Request
    text: str
    robot_mood: str = 'neutral'


def query(request: Request):
    """
    Process a text query through the LLM.

    Args:
        request: Request object with user text and user_id.

    Returns:
        Response object with assistant text and mood, or None if input is empty.
    """
    if not request.text:
        return None

    logger.info(f"Processing query for '{request.user_id}': '{request.text}'")
    start = time.time()

    text_response, robot_mood = generate_response(request.text, request.user_id)

    logger.info(f"LLM response in {time.time() - start:.2f}s: '{text_response}'")

    if not text_response:
        return None

    return Response(
        request=request,
        text=text_response,
        robot_mood=robot_mood,
    )
