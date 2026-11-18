"""
services/cloud/google_api.py

Google Cloud Speech-to-Text and Text-to-Speech wrappers.

STT configurations:
    stt_config          — batch recognition for complete LINEAR16 recordings
    streaming_config    — streaming recognition for LINEAR16 PCM from AudioWorklet
                          (same format as the physical robot's PyAudio stream)

TTS configuration:
    voice / tts_config  — Spanish female voice, MP3 for mobile browser playback
"""

import json
import logging
import os

from google.cloud import speech, texttospeech
from google.oauth2 import service_account

logger = logging.getLogger('GoogleAPI')
STREAMING_RECOGNIZE_RPC_TIMEOUT = float(os.getenv('GOOGLE_STREAMING_STT_RPC_TIMEOUT_SECONDS', '65'))


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

TTS_AUDIO_MIME_TYPE = 'audio/mpeg'

# MP3 avoids mobile browser playback issues seen with WAV/PCM blobs.
tts_config = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.MP3,
    pitch=-0.4,
)

# ── STT client ────────────────────────────────────────────────────────────────
clientSTT = speech.SpeechClient(
    credentials=_credentials
) if _credentials else speech.SpeechClient()

# Batch STT
stt_config = speech.RecognitionConfig(
    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
    sample_rate_hertz=16000,
    language_code='es-ES',
    enable_automatic_punctuation=True,
    model='latest_short',
    audio_channel_count=1,
)

# Streaming STT — LINEAR16 PCM from AudioWorklet (same as robot's PyAudio stream)
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

def speech_to_text(audio_bytes: bytes, mime_type='audio/pcm') -> str:
    """
    Recognize a complete PCM utterance or a legacy MediaRecorder file.
    """
    audio = speech.RecognitionAudio(content=audio_bytes)
    config = stt_config
    if mime_type != 'audio/pcm':
        encodings = {
            'audio/webm': speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            'audio/ogg': speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            'audio/wav': speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED,
        }
        encoding = encodings[mime_type.split(';')[0]]
        config = speech.RecognitionConfig(encoding=encoding, language_code='es-ES',
                                          enable_automatic_punctuation=True)
        if mime_type.split(';')[0] in ('audio/webm', 'audio/ogg'):
            config.sample_rate_hertz = 48000
    response = clientSTT.recognize(config=config, audio=audio, timeout=25)
    return ' '.join(
        result.alternatives[0].transcript.strip() for result in response.results if result.alternatives
    ).strip()

def create_streaming_stt_request_generator(audio_generator):
    for audio_chunk in audio_generator:
        yield speech.StreamingRecognizeRequest(audio_content=audio_chunk)


def streaming_speech_to_text(audio_generator):
    """Accept only a normally completed stream of final segments."""
    complete_input = False

    def requests():
        nonlocal complete_input
        yield from create_streaming_stt_request_generator(audio_generator)
        complete_input = True

    parts = []
    unfinished = False
    for response in clientSTT.streaming_recognize(streaming_config, requests(),
                                                  timeout=STREAMING_RECOGNIZE_RPC_TIMEOUT):
        for result in response.results:
            if not result.alternatives:
                continue
            unfinished = not result.is_final
            if result.is_final:
                parts.append(result.alternatives[0].transcript.strip())
    return ' '.join(parts).strip() if complete_input and not unfinished else ''


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
        audio_config=tts_config, timeout=25
    )
    return response.audio_content
