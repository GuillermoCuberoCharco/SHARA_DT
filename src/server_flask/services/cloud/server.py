"""
services/cloud/server.py

Chat server module. Receives text or audio input, calls OpenAI,
and can synthesize a spoken response with Google Cloud.
"""

import logging
import time
from dataclasses import dataclass

from .google_api import speech_to_text, text_to_speech
from .openai_api import generate_response

logger = logging.getLogger('Server')


@dataclass
class Request:
    text: str = ''
    user_id: str = ''
    user_role: str = 'student'
    subject_code: str = ''
    audio: bytes = b''


@dataclass
class Response:
    request: Request
    text: str
    robot_mood: str = 'neutral'
    audio: bytes = b''


def query(request: Request):
    """
    Process a text or audio query.

    When audio is provided, Google STT is used first. The LLM response is
    returned as text and mood; TTS is triggered separately so the current
    speaker toggle can be respected right before synthesis.
    """
    if request.audio and not request.text:
        stt_start = time.time()
        request.text = speech_to_text(request.audio)
        logger.info("STT response in %.2fs: '%s'", time.time() - stt_start, request.text)

    request.text = (request.text or '').strip()
    if not request.text:
        return None

    logger.info("Processing query for '%s': '%s'", request.user_id, request.text)
    start = time.time()

    text_response, robot_mood = generate_response(
        request.text,
        request.user_id,
        request.user_role,
        request.subject_code,
    )

    logger.info("LLM response in %.2fs: '%s'", time.time() - start, text_response)

    if not text_response:
        return None

    return Response(
        request=request,
        text=text_response,
        robot_mood=robot_mood,
    )


def synthesize_response(text: str) -> bytes:
    """
    Synthesize assistant text into audio using the main-branch TTS settings.
    """
    start = time.time()
    audio_response = text_to_speech(text)
    logger.info('TTS response in %.2fs', time.time() - start)
    return audio_response
