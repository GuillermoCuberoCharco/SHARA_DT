/**
 * config.js
 *
 * SERVER_URL resolution:
 *   - Production (Render): empty string — same origin, no host needed
 *   - Local development: http://localhost:8081
 *
 */
export const SERVER_URL = (import.meta.env.PROD ? '' : 'http://localhost:8081');

export const FACE_DETECTION_SETTINGS = Object.freeze({
    intervalMs: 250,
    modelScoreThreshold: 0.9,
    minProbability: 0.9,
    minFaceSizePx: 96,
    minFaceSizeRatio: 0.22,
    minAspectRatio: 0.65,
    maxAspectRatio: 1.5,
    minStableSamples: 6,
    minStableDurationMs: 1250,
    minBoxIou: 0.5,
    minConsecutiveLosses: 3,
    lossTimeoutMs: 10000,
});

// Kept as a named export for compatibility with older imports.
export const DETECTION_INTERVAL_MS = FACE_DETECTION_SETTINGS.intervalMs;
export const RECOGNITION_REQUEST_TIMEOUT_MS = 60000;

export const AUDIO_SETTINGS = {
    // PCM LINEAR16 via AudioWorklet — matches the physical robot's PyAudio config
    sampleRate: 16000,          // Hz — same as robot mic
    silenceThreshold: 30,       // Higher RMS threshold so low ambient noise still counts as silence
    silenceDuration: 1800,      // ms of silence before auto-stop
    maxRecordingTime: 50000,    // ms hard cap per utterance
    pcmChunkDurationMs: 100,    // 1600 samples at 16 kHz
    preSpeechBufferMs: 2500,    // Same idea as the physical robot prev_audio_size
    vadWarmupChunks: 3,         // Short ambient-noise calibration before opening the stream
    vadStartChunks: 2,          // Consecutive speech-like chunks required to open Google streaming
    vadSilenceChunks: 8,        // Consecutive non-speech chunks before closing the stream
    vadMinRms: 0.01,
    vadMinPeak: 0.035,
    vadNoiseMultiplier: 2.4,
    vadMinZcr: 0.005,
    vadMaxZcr: 0.32,
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
