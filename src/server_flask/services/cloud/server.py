"""
    services/cloud/server.py
Main server module for cloud services. Handles the main query flow: receiving audio input,
performing STT, generating LLM response, converting to TTS, and returning the response.

Same code as the original server module on the robot, but adapted to be used as a service module in the Flask server.
The web Socket.IO pipeline can stream PCM chunks to Google STT and then process the transcribed text.
"""

import logging
import time
from dataclasses import dataclass

from .google_api import (
    TTS_AUDIO_MIME_TYPE,
    speech_to_text,
    streaming_speech_to_text,
    text_to_speech,
)
from .openai_api import generate_response, load_conversation_history, save_conversation_history

logger = logging.getLogger('Server')
logger.setLevel(logging.DEBUG)


@dataclass
class Request:
    audio: str = b''
    text: str = None
    username: str = None
    login_name: str = None
    session_id: str = None
    proactive_question: str = ''

@dataclass
class Response:
    request: Request
    audio: str
    action: str
    username: str
    continue_conversation: bool
    robot_mood: str = 'neutral'
    text: str = None
    audio_mime_type: str = TTS_AUDIO_MIME_TYPE


def query(request: Request):
    """
    Perform query STT + LLM + TTS
    
    Args:
        request (Request): The user request containing audio and context information.

    Returns:
        Response: The response object containing audio and context information.
    """
    # STT
    start_time = time.time()
    request.text = speech_to_text(request.audio)
    logger.info(f"STT result ({time.time() - start_time:.2f} seconds) :: '{request.text}'")
    
    if not request.text:
        return None

    # Set context variables
    context_variables = {}
    context_variables["username"] = request.username
    context_variables["proactive_question"] = request.proactive_question 
    logger.info(f'Query context :: {context_variables}')

    # Generate the response
    start_time = time.time()
    text_response, robot_context = generate_response(
        request.text,
        context_variables,
        history_key=request.login_name or request.username,
        session_id=request.session_id,
    )
    logger.info(f'LLM response generated in {time.time() - start_time:.2f} seconds')
    logger.info(f'Response text :: {text_response}')
    logger.info(f'Response context :: {robot_context}')

    # Check if LLM response text robot is empty
    if not text_response:
        return None

    # TTS
    start_time = time.time()
    audio_response = text_to_speech(text_response)
    logger.info(f"TTS result obtained (response generated in {time.time() - start_time:.2f} seconds)")

    # Send back the response
    return Response(
        request,
        audio_response,
        robot_context.get('action', None),
        robot_context.get('username', None),
        bool(robot_context.get('continue', '')),
        robot_context['robot_mood'] if 'robot_mood' in robot_context and robot_context['robot_mood'] else 'neutral',
        text_response
    )

def query_with_text(request: Request):
    """Process query with text already transcribed LLM + TTS"""
    if not request.text:
        return None

    logger.info(f"Processing query with pre-transcribed text: '{request.text}'")

    # Set context variables
    context_variables = {}
    context_variables["username"] = request.username
    context_variables["proactive_question"] = request.proactive_question 
    logger.info(f'Query context :: {context_variables}')

    # Generate the response
    start_time = time.time()
    text_response, robot_context = generate_response(
        request.text,
        context_variables,
        history_key=request.login_name or request.username,
        session_id=request.session_id,
    )
    logger.info(f'LLM response generated in {time.time() - start_time:.2f} seconds')
    logger.info(f'Response text :: {text_response}')
    logger.info(f'Response context :: {robot_context}')

    # Check if LLM response text robot is empty
    if not text_response:
        return None

    # TTS
    start_time = time.time()
    audio_response = text_to_speech(text_response)
    logger.info(f"TTS result obtained (response generated in {time.time() - start_time:.2f} seconds)")

    # Send back the response
    return Response(
        request,
        audio_response,
        robot_context.get('action', None),
        robot_context.get('username', None),
        bool(robot_context.get('continue', '')),
        robot_context['robot_mood'] if 'robot_mood' in robot_context and robot_context['robot_mood'] else 'neutral',
        text_response
    )


def streaming_stt(audio_generator, on_transcript=None):
    """
    Perform only streaming STT.

    This mirrors the physical robot: the microphone/VAD layer feeds chunks,
    and the response generation starts from the already transcribed text.
    """
    transcript, silence_detection_time, _ = streaming_speech_to_text(
        audio_generator,
        on_transcript=on_transcript,
    )

    if silence_detection_time is not None:
        logger.info(
            "Streaming STT result (silence detection: %.3f seconds) :: '%s'",
            silence_detection_time,
            transcript,
        )
    else:
        logger.info("Streaming STT result (no final result) :: '%s'", transcript)

    return transcript


def proactive_query(request: Request):
    # Same as query but with empty input_text and without STT
    # Set context variables
    context_variables = {}
    context_variables["username"] = request.username
    context_variables["proactive_question"] = request.proactive_question 
    logger.info(f'Query context :: {context_variables}')

    # Generate the response
    start_time = time.time()
    text_response, robot_context = generate_response(
        '',
        context_variables,
        history_key=request.login_name or request.username,
        session_id=request.session_id,
    ) # Empty input_text since it's a proactive question
    logger.info(f'LLM response generated in {time.time() - start_time:.2f} seconds')
    logger.info(f'Response text :: {text_response}')
    logger.info(f'Response context :: {robot_context}')

    # TTS
    start_time = time.time()
    audio_response = text_to_speech(text_response)
    logger.info(f"TTS result obtained (response generated in {time.time() - start_time:.2f} seconds)")

    # Send back the response
    return Response(
        request,
        audio_response,
        robot_context.get('action', None),
        robot_context.get('username', None),
        bool(robot_context.get('continue', '')),
        robot_context['robot_mood'] if 'robot_mood' in robot_context and robot_context['robot_mood'] else 'neutral',
        text_response
    )

def load_conversation_db(username):
    # History is now loaded per request; this call warms/logs the DB path.
    load_conversation_history(username)

    logger.info(f'Conversation history of {username} loaded')

def dump_conversation_db(username, session_id=None):
    # Conversations are persisted per request; keep this as a compatibility hook.
    save_conversation_history(username, session_id=session_id)

    logger.info(f'Conversation history of {username} flushed (session={session_id})')
