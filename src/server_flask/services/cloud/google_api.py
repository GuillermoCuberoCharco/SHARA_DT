"""
services/cloud/google_api.py

Google STT and TTS wrapper — adapted from the physical robot for cloud deployment.

Changes from original:
    - Credentials built from individual env vars (GOOGLE_CLIENT_EMAIL,
      GOOGLE_PRIVATE_KEY, GOOGLE_PROJECT_ID) instead of a local JSON file.
    - Falls back to GOOGLE_APPLICATION_CREDENTIALS file path if individual
      vars are not set (preserves local development compatibility).
    - Audio encoding updated to WEBM_OPUS to match browser MediaRecorder output.

Original robot used LINEAR16 from PyAudio mic. Browser sends WEBM_OPUS (webm/opus).
"""

import json
import os

from google.cloud import speech, texttospeech
from google.oauth2 import service_account

import logging

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

    logger.warning('No Google credentials found — clients will use ADC')
    return None


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
    audio_encoding=texttospeech.AudioEncoding.MP3,
    pitch=-0.4,
)

# ── STT client ────────────────────────────────────────────────────────────────
clientSTT = speech.SpeechClient(
    credentials=_credentials
) if _credentials else speech.SpeechClient()

# STT Config — WEBM_OPUS matches browser MediaRecorder output
# (original robot used LINEAR16 from PyAudio physical mic)
stt_config = speech.RecognitionConfig(
    encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
    sample_rate_hertz=48000,
    language_code='es-ES',
    enable_automatic_punctuation=True,
    model='latest_short',
    audio_channel_count=1,
)


# ── Public API (unchanged from robot) ────────────────────────────────────────

_GOOGLE_API_TIMEOUT = 15.0  # seconds


def speech_to_text(audio_bytes: bytes) -> str:
    """
    Converts speech audio (WEBM_OPUS from browser) to text.

    Args:
        audio_bytes: Raw audio bytes from browser MediaRecorder

    Returns:
        Transcribed text string, or empty string if no speech detected
    """
    audio = speech.RecognitionAudio(content=audio_bytes)
    response = clientSTT.recognize(config=stt_config, audio=audio, timeout=_GOOGLE_API_TIMEOUT)
    return ''.join(
        result.alternatives[0].transcript for result in response.results
    )


def text_to_speech(text: str) -> bytes:
    """
    Converts text to speech audio (MP3).

    Args:
        text: Text to synthesize

    Returns:
        Audio bytes (MP3)
    """
    synthesis_input = texttospeech.SynthesisInput(text=text)
    response = clientTTS.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=tts_config,
        timeout=_GOOGLE_API_TIMEOUT,
    )
    return response.audio_content