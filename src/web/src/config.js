/**
 * config.js
 *
 * SERVER_URL resolution:
 *   - Production (Render): empty string — same origin, no host needed
 *   - Local development: http://localhost:8081
 *
 */
export const SERVER_URL = (import.meta.env.PROD ? '' : 'http://localhost:8081');

export const DETECTION_INTERVAL_MS = 250;
export const RECOGNITION_REQUEST_TIMEOUT_MS = 60000;

export const AUDIO_SETTINGS = {
    // PCM LINEAR16 via AudioWorklet — matches the physical robot's PyAudio config
    sampleRate: 16000,          // Hz — same as robot mic
    silenceThreshold: 30,       // Higher RMS threshold so low ambient noise still counts as silence
    silenceDuration: 2000,      // ms of silence before auto-stop
    maxRecordingTime: 50000,    // ms hard cap per utterance
};

export const ANIMATION_MAPPINGS = {
    joy: 'joy',
    joy_blush: 'joy_blush',
    neutral: 'neutral',
    sad: 'sad',
    silly: 'silly',
    surprise: 'surprise',
    angry: 'angry',
};
