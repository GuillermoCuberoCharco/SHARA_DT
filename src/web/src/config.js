/**
 * config.js
 *
 * SERVER_URL resolution:
 *   - Production (Render): empty string — same origin, no host needed
 *   - Local development: http://localhost:8081
 *
 */
export const SERVER_URL = (import.meta.env.PROD ? '' : 'http://localhost:8081');

export const AUDIO_SETTINGS = {
    mimeType: 'audio/webm;codecs=opus',
    bufferSize: 2048,
    sampleRate: 44100,
    silenceThreshold: 60,
    silenceDuration: 3000,
    maxRecordingTime: 50000,
    audioBitsPerSecond: 16000
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