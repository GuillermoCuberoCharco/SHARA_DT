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

# Batch STT
stt_config = speech.RecognitionConfig(
    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
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
    Converts speech audio (LINEAR16 from browser) to text.

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

def create_streaming_stt_request_generator(audio_generator):
    for audio_chunk in audio_generator:
        yield speech.StreamingRecognizeRequest(audio_content=audio_chunk)


def create_streaming_requests_with_collection(audio_generator):
    collected = []
    def gen():
        for audio_chunk in audio_generator:
            collected.append(audio_chunk)
            yield speech.StreamingRecognizeRequest(audio_content=audio_chunk)
    return gen(), collected


def streaming_speech_to_text(audio_generator):
    """
    Core streaming STT function. Pure streaming logic without fallback.
    
    Args:
        audio_generator: Generator that yields audio chunks (bytes)
    
    Returns:
        tuple: (transcript, silence_detection_time, audio_bytes) where:
            - transcript: The transcribed text from streaming
            - silence_detection_time: Time from last interim to final result
            - audio_bytes: Collected audio for potential fallback
    """
    # Create requests and collect audio for potential fallback
    requests, collected_audio = create_streaming_requests_with_collection(audio_generator)
    responses = clientSTT.streaming_recognize(streaming_config, requests)
    
    transcript = ""
    silence_detection_time = None
    last_interim_time = None
    last_interim_transcript = ""  # Store last interim result as fallback
    
    try:
        for response in responses:
            if not response.results:
                continue
                
            result = response.results[0]
            
            if not result.is_final:
                # Update the time of the last interim result (user still speaking)
                last_interim_transcript = result.alternatives[0].transcript  # Save interim transcript
                last_interim_time = time.time()
            else:
                # Final result - calculate time since last interim result
                final_result_time = time.time()
                transcript = result.alternatives[0].transcript
                
                if last_interim_time is not None:
                    silence_detection_time = final_result_time - last_interim_time
                else:
                    # No interim results received, can't measure accurately
                    silence_detection_time = 0.0
                
                # If final transcript is empty but we had interim results, use the last interim
                if not transcript and last_interim_transcript:
                    transcript = last_interim_transcript

                break  # We got the final result
    
    except Exception as e:
        # If the stream ends or there's an error, return what we have
        # Use last interim result if available
        if not transcript and last_interim_transcript:
            transcript = last_interim_transcript
    
    audio_bytes = b''.join(collected_audio) if collected_audio else b''
    return transcript, silence_detection_time, audio_bytes


def compose_streaming_fallback_speech_to_text(audio_generator):
    """
    Performs streaming speech recognition with automatic fallback for empty results.
    
    Strategy:
    1. Try streaming STT with latest_long model (optimized for conversations)
    2. If result is empty, fallback to latest_short model (better for monosyllables)
    
    Args:
        audio_generator: Generator that yields audio chunks (bytes)
    
    Returns:
        tuple: (transcript, silence_detection_time) where:
            - transcript: The transcribed text
            - silence_detection_time: Total time including fallback if used
    """
    # Step 1: Try streaming STT
    transcript, silence_time, audio_bytes = streaming_speech_to_text(audio_generator)
    
    # Step 2: Fallback if result is empty
    if not transcript and audio_bytes:
        try:
            fallback_start = time.time()
            fallback_transcript = speech_to_text(audio_bytes)
            fallback_time = time.time() - fallback_start
            
            if fallback_transcript:
                transcript = fallback_transcript
                # Add fallback time to total time
                if silence_time is not None:
                    silence_time += fallback_time
                else:
                    silence_time = fallback_time
        except Exception:
            # Fallback failed, keep original transcript
            pass
    
    return transcript, silence_time


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