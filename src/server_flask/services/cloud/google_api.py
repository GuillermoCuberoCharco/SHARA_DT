"""
Google Cloud Speech-to-Text and Text-to-Speech helpers.
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
        1. Individual env vars used in cloud deployments.
        2. GOOGLE_APPLICATION_CREDENTIALS as JSON string.
        3. GOOGLE_APPLICATION_CREDENTIALS as file path.
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
            ],
        )

    app_creds = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if not app_creds:
        return None

    try:
        creds_dict = json.loads(app_creds)
        logger.info('Building Google credentials from JSON string env var')
        return service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/cloud-platform'],
        )
    except (json.JSONDecodeError, ValueError):
        logger.info('Using Google credentials file: %s', app_creds)
        return service_account.Credentials.from_service_account_file(
            app_creds,
            scopes=['https://www.googleapis.com/auth/cloud-platform'],
        )


_credentials = _build_credentials()
_client_tts = None
_client_stt = None

voice = texttospeech.VoiceSelectionParams(
    language_code='es-ES',
    ssml_gender=texttospeech.SsmlVoiceGender.FEMALE,
)

tts_config = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.LINEAR16,
    sample_rate_hertz=24000,
    pitch=-0.4,
)

stt_config = speech.RecognitionConfig(
    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
    sample_rate_hertz=16000,
    language_code='es-ES',
    enable_automatic_punctuation=True,
    model='latest_short',
    audio_channel_count=1,
)


def _get_tts_client():
    global _client_tts
    if _client_tts is None:
        _client_tts = (
            texttospeech.TextToSpeechClient(credentials=_credentials)
            if _credentials
            else texttospeech.TextToSpeechClient()
        )
    return _client_tts


def _get_stt_client():
    global _client_stt
    if _client_stt is None:
        _client_stt = (
            speech.SpeechClient(credentials=_credentials)
            if _credentials
            else speech.SpeechClient()
        )
    return _client_stt


def speech_to_text(audio_bytes: bytes) -> str:
    """
    Convert LINEAR16 PCM audio from the browser into text.
    """
    if not audio_bytes:
        return ''

    audio = speech.RecognitionAudio(content=audio_bytes)
    response = _get_stt_client().recognize(config=stt_config, audio=audio)
    return ''.join(
        result.alternatives[0].transcript
        for result in response.results
        if result.alternatives
    ).strip()


def text_to_speech(text: str) -> bytes:
    """
    Convert text into LINEAR16 audio.
    """
    if not text:
        return b''

    synthesis_input = texttospeech.SynthesisInput(text=text)
    response = _get_tts_client().synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=tts_config,
    )
    return response.audio_content
