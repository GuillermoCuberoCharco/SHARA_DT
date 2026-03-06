"""
services/cloud/google_api.py

Google Cloud Speech-to-Text and Text-to-Speech wrappers.

STT configurations:
    stt_config          — batch recognition for WEBM_OPUS blobs (legacy fallback)
    streaming_config    — streaming recognition for LINEAR16 PCM from AudioWorklet
                          (same format as the physical robot's PyAudio stream)

TTS configuration:
    voice / tts_config  — Spanish female voice, LINEAR16 at 24kHz
"""

import json
import logging
import os

from google.cloud import speech, texttospeech
from google.oauth2 import service_account

logger = logging.getLogger('GoogleAPI')


def _build_credentials():
    """
    Build Google credentials from environment variables.

    Priority:
        1. Individual env vars (GOOGLE_CLIENT_EMAIL, GOOGLE_PRIVATE_KEY,
           GOOGLE_PROJECT_ID) — used in cloud deployments like Render.
        2. GOOGLE_APPLICATION_CREDENTIALS as JSON string — legacy Node.js style.
        3. GOOGLE_APPLICATION_CREDENTIALS as file path — local development.
    """
    client_email = os.getenv('GOOGLE_CLIENT_EMAIL')
    private_key = os.getenv('GOOGLE_PRIVATE_KEY', '').replace('\\n', '\n')
    project_id = os.getenv('GOOGLE_PROJECT_ID')

    if client_email and private_key and project_id:
        logger.info('Building Google credentials from individual env vars')
        credentials_dict = {
            'type': 'service_account',
            'project_id': project_id,
            'private_key': private_key,
            'client_email': client_email,
            'token_uri': 'https://oauth2.googleapis.com/token',
        }
        return service_account.Credentials.from_service_account_info(
            credentials_dict,
            scopes=[
                'https://www.googleapis.com/auth/cloud-platform',
                'https://www.googleapis.com/auth/speech',
            ]
        )

    # Fallback: GOOGLE_APPLICATION_CREDENTIALS as JSON string or file path
    app_creds = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if app_creds:
        try:
            creds_dict = json.loads(app_creds)
            logger.info('Building Google credentials from JSON string env var')
            return service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
        except (json.JSONDecodeError, ValueError):
            logger.info(f'Using Google credentials file: {app_creds}')
            return service_account.Credentials.from_service_account_file(
                app_creds,
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )


# Build credentials once at module load
_credentials = _build_credentials()
_project_id = os.getenv('GOOGLE_PROJECT_ID')

# ── TTS client ────────────────────────────────────────────────────────────────
clientTTS = texttospeech.TextToSpeechClient(
    credentials=_credentials
) if _credentials else texttospeech.TextToSpeechClient()

voice = texttospeech.VoiceSelectionParams(
    language_code='es-ES',
    ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
)

tts_config = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.LINEAR16,
    sample_rate_hertz=24000,
    pitch=-0.4,
)

# ── STT client ────────────────────────────────────────────────────────────────
clientSTT = speech.SpeechClient(
    credentials=_credentials
) if _credentials else speech.SpeechClient()

# Batch STT — WEBM_OPUS for legacy audio blob path
stt_config = speech.RecognitionConfig(
    encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
    sample_rate_hertz=48000,
    language_code='es-ES',
    enable_automatic_punctuation=True,
    model='latest_short',
    audio_channel_count=1,
)

# Streaming STT — LINEAR16 PCM from AudioWorklet (same as robot's PyAudio stream)
# AudioWorklet sends Int16 samples at 16000 Hz, mono.
streaming_config = speech.StreamingRecognitionConfig(
    config=speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code='es-ES',
        enable_automatic_punctuation=True,
        model='latest_long',   # optimised for continuous speech
        audio_channel_count=1,
    ),
    interim_results=True
)


# ── Public API ────────────────────────────────────────────────────────────────

def speech_to_text(audio_bytes: bytes) -> str:
    """
    Converts speech audio (WEBM_OPUS from browser) to text.

    Args:
        audio_bytes: Raw audio bytes from browser MediaRecorder

    Returns:
        Transcribed text string, or empty string if no speech detected
    """
    audio = speech.RecognitionAudio(content=audio_bytes)
    response = clientSTT.recognize(config=stt_config, audio=audio)
    return ''.join(
        result.alternatives[0].transcript for result in response.results
    )


def streaming_speech_to_text(pcm_generator) -> str:
    """
    Streaming STT for LINEAR16 PCM chunks from AudioWorklet.

    Equivalent to compose_streaming_fallback_speech_to_text() on the robot.
    Streams audio chunks to Google as they arrive, returns the final transcript
    once the utterance is complete (single_utterance=True stops the stream).

    Args:
        pcm_generator: Generator that yields raw bytes (Int16 PCM at 16000 Hz)

    Returns:
        Transcribed text string, or empty string if no speech detected
    """
    def request_generator():
        for chunk in pcm_generator:
            if chunk:
                yield speech.StreamingRecognizeRequest(audio_content=chunk)

    transcript = ''
    try:
        responses = clientSTT.streaming_recognize(streaming_config, request_generator())
        for response in responses:
            for result in response.results:
                if result.is_final and result.alternatives:
                    transcript = result.alternatives[0].transcript
                    logger.info(f'Streaming STT final result: "{transcript}"')
                    return transcript
    except Exception as e:
        logger.error(f'Streaming STT error: {e}', exc_info=True)

    if not transcript:
        logger.warning('Streaming STT returned empty transcript')
    return transcript


def text_to_speech(text: str) -> bytes:
    """
    Converts text to speech audio (LINEAR16).

    Args:
        text: Text to synthesize

    Returns:
        Audio bytes (LINEAR16, 24000 Hz)
    """
    synthesis_input = texttospeech.SynthesisInput(text=text)
    response = clientTTS.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=tts_config
    )
    return response.audio_content