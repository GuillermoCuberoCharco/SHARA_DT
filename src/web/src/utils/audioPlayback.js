const SILENT_WAV_DATA_URI = 'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQIAAAAAAA==';
const AUDIO_UNLOCK_TIMEOUT_MS = 3500;
const AUDIO_DECODE_TIMEOUT_MS = 8000;
const HTML_AUDIO_PLAY_TIMEOUT_MS = 45000;
const WEB_AUDIO_END_GRACE_MS = 2500;
const WEB_AUDIO_MIN_TIMEOUT_MS = 5000;

let sharedAudioElement = null;
let sharedAudioContext = null;
let currentWebAudioSource = null;
let isUnlocked = false;
let unlockPromise = null;
let playbackGeneration = 0;
const unlockListeners = new Set();

const getBrowserAudioContext = () => {
    if (typeof window === 'undefined') {
        return null;
    }

    return window.AudioContext || window.webkitAudioContext || null;
};

const publishAudioDiagnostic = (diagnostic) => {
    const nextDiagnostic = {
        at: new Date().toISOString(),
        ...diagnostic,
    };

    if (typeof window !== 'undefined') {
        window.__SHARA_AUDIO_LAST__ = nextDiagnostic;
    }

    console.log('[SHARA][audio]', nextDiagnostic);
};

const createTimeoutError = (message) => {
    const error = new Error(message);
    error.name = 'TimeoutError';
    return error;
};

const createAbortError = (message) => {
    const error = new Error(message);
    error.name = 'AbortError';
    return error;
};

const isCurrentPlayback = (playbackId) => playbackId === playbackGeneration;

const withTimeout = (promise, timeoutMs, message, onTimeout) => new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
        if (settled) {
            return;
        }

        settled = true;
        onTimeout?.();
        reject(createTimeoutError(message));
    }, timeoutMs);

    Promise.resolve(promise).then(
        (value) => {
            if (settled) {
                return;
            }

            settled = true;
            clearTimeout(timer);
            resolve(value);
        },
        (error) => {
            if (settled) {
                return;
            }

            settled = true;
            clearTimeout(timer);
            reject(error);
        },
    );
});

const setAudioUnlocked = (nextUnlocked) => {
    if (isUnlocked === nextUnlocked) {
        return;
    }

    isUnlocked = nextUnlocked;
    unlockListeners.forEach((listener) => {
        listener(isUnlocked);
    });
};

export const isAudioPlaybackUnlocked = () => isUnlocked;

export const subscribeAudioPlaybackUnlock = (listener) => {
    unlockListeners.add(listener);

    return () => {
        unlockListeners.delete(listener);
    };
};

const getSharedAudioContext = () => {
    const AudioContext = getBrowserAudioContext();
    if (!AudioContext) {
        return null;
    }

    if (!sharedAudioContext || sharedAudioContext.state === 'closed') {
        sharedAudioContext = new AudioContext();
        sharedAudioContext.onstatechange = () => {
            if (sharedAudioContext?.state === 'running') {
                setAudioUnlocked(true);
            }
        };
    }

    return sharedAudioContext;
};

const getSharedAudioElement = () => {
    if (typeof Audio === 'undefined') {
        return null;
    }

    if (!sharedAudioElement) {
        sharedAudioElement = new Audio();
        sharedAudioElement.preload = 'auto';
        sharedAudioElement.playsInline = true;
    }

    return sharedAudioElement;
};

const resetAudioElement = (audio) => {
    audio.pause();

    try {
        audio.currentTime = 0;
    } catch {
        // Some mobile browsers reject currentTime before metadata is loaded.
    }
};

const stopCurrentPlayback = () => {
    if (currentWebAudioSource) {
        const source = currentWebAudioSource;
        currentWebAudioSource = null;
        source.onended = null;

        try {
            source.stop();
        } catch {
            // The source may not have started or may already be stopped.
        }

        try {
            source.disconnect();
        } catch {
            // Some browsers throw if the node is already disconnected.
        }
    }

    if (sharedAudioElement) {
        resetAudioElement(sharedAudioElement);
        sharedAudioElement.removeAttribute('src');

        try {
            sharedAudioElement.load();
        } catch {
            // Mobile browsers may reject load() during teardown.
        }
    }
};

export const cancelAudioPlayback = (reason = 'cancelled') => {
    playbackGeneration += 1;
    stopCurrentPlayback();
    publishAudioDiagnostic({
        event: 'play_cancel',
        reason,
    });
};

const beginPlayback = () => {
    playbackGeneration += 1;
    stopCurrentPlayback();
    return playbackGeneration;
};

const unlockWebAudio = async () => {
    const audioContext = getSharedAudioContext();
    if (!audioContext) {
        return false;
    }

    if (audioContext.state === 'suspended') {
        await withTimeout(
            audioContext.resume(),
            AUDIO_UNLOCK_TIMEOUT_MS,
            'AudioContext resume timed out',
        );
    }

    if (audioContext.state !== 'running') {
        return false;
    }

    const silentBuffer = audioContext.createBuffer(1, 1, audioContext.sampleRate);
    const source = audioContext.createBufferSource();
    const gain = audioContext.createGain();
    gain.gain.value = 0;
    source.buffer = silentBuffer;
    source.connect(gain).connect(audioContext.destination);
    source.start(0);

    setAudioUnlocked(true);
    return true;
};

const unlockHtmlAudio = async () => {
    const audio = getSharedAudioElement();
    if (!audio) {
        return false;
    }

    resetAudioElement(audio);
    audio.muted = false;
    audio.src = SILENT_WAV_DATA_URI;
    audio.load();

    await withTimeout(
        audio.play(),
        AUDIO_UNLOCK_TIMEOUT_MS,
        'HTML audio unlock timed out',
    );
    resetAudioElement(audio);
    audio.removeAttribute('src');
    audio.load();

    return true;
};

export const unlockAudioPlayback = () => {
    if (isUnlocked) {
        return Promise.resolve(true);
    }

    if (unlockPromise) {
        return unlockPromise;
    }

    unlockPromise = Promise.allSettled([
        unlockWebAudio(),
        unlockHtmlAudio(),
    ])
        .then((results) => {
            const webAudioUnlocked = results[0].status === 'fulfilled' && results[0].value;
            const htmlAudioUnlocked = results[1].status === 'fulfilled' && results[1].value;
            const unlocked = webAudioUnlocked || htmlAudioUnlocked;

            setAudioUnlocked(unlocked);
            publishAudioDiagnostic({
                event: 'unlock',
                webAudioUnlocked,
                htmlAudioUnlocked,
                audioContextState: sharedAudioContext?.state || null,
            });
            return unlocked;
        })
        .catch((error) => {
            console.warn('[SHARA][audio] Playback unlock was blocked:', error);
            publishAudioDiagnostic({
                event: 'unlock_error',
                errorName: error?.name || null,
                errorMessage: error?.message || String(error),
            });
            return false;
        })
        .finally(() => {
            unlockPromise = null;
        });

    return unlockPromise;
};

const base64ToUint8Array = (audioB64) => {
    const binary = window.atob(audioB64);
    const bytes = new Uint8Array(binary.length);

    for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
    }

    return bytes;
};

const decodeAudioData = (audioContext, arrayBuffer) => new Promise((resolve, reject) => {
    let settled = false;

    const finish = (callback) => (value) => {
        if (settled) {
            return;
        }

        settled = true;
        callback(value);
    };

    const decodeResult = audioContext.decodeAudioData(
        arrayBuffer,
        finish(resolve),
        finish(reject),
    );

    if (decodeResult && typeof decodeResult.then === 'function') {
        decodeResult.then(finish(resolve), finish(reject));
    }
});

const shouldPreferHtmlAudio = () => {
    if (typeof navigator === 'undefined') {
        return false;
    }

    const userAgent = navigator.userAgent || '';
    const isIOS = /iPad|iPhone|iPod/.test(userAgent)
        || (userAgent.includes('Macintosh') && navigator.maxTouchPoints > 1);
    const isAndroidMobile = /Android/.test(userAgent) && /Mobile/.test(userAgent);

    return isIOS || isAndroidMobile;
};

const playBytesWithWebAudio = async (audioBytes, mimeType, options = {}) => {
    const playbackId = options.playbackId;
    const audioContext = getSharedAudioContext();
    if (!audioContext) {
        throw new Error('Web Audio API is not available');
    }

    if (unlockPromise) {
        await unlockPromise;
    }

    if (audioContext.state === 'suspended') {
        await withTimeout(
            audioContext.resume(),
            AUDIO_UNLOCK_TIMEOUT_MS,
            'AudioContext resume timed out before playback',
        );
    }

    if (audioContext.state !== 'running') {
        throw new Error(`AudioContext is ${audioContext.state}`);
    }

    if (!isCurrentPlayback(playbackId)) {
        throw createAbortError('Web Audio playback was cancelled before decode');
    }

    const audioBuffer = await withTimeout(
        decodeAudioData(
            audioContext,
            audioBytes.buffer.slice(audioBytes.byteOffset, audioBytes.byteOffset + audioBytes.byteLength),
        ),
        AUDIO_DECODE_TIMEOUT_MS,
        'Audio decode timed out',
    );

    if (!isCurrentPlayback(playbackId)) {
        throw createAbortError('Web Audio playback was cancelled after decode');
    }

    if (currentWebAudioSource) {
        try {
            currentWebAudioSource.stop();
        } catch {
            // The source may have already ended.
        }
    }

    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);
    currentWebAudioSource = source;

    publishAudioDiagnostic({
        event: 'play_start',
        route: 'web_audio',
        mimeType,
        bytes: audioBytes.byteLength,
        duration: audioBuffer.duration,
        audioContextState: audioContext.state,
    });

    const playbackTimeoutMs = Math.max(
        WEB_AUDIO_MIN_TIMEOUT_MS,
        Math.ceil(audioBuffer.duration * 1000) + WEB_AUDIO_END_GRACE_MS,
    );
    const timeoutMs = options.timeoutMs
        ? Math.max(playbackTimeoutMs, options.timeoutMs)
        : playbackTimeoutMs;

    return withTimeout(new Promise((resolve, reject) => {
        source.onended = () => {
            if (currentWebAudioSource === source) {
                currentWebAudioSource = null;
            }

            publishAudioDiagnostic({
                event: 'play_end',
                route: 'web_audio',
                mimeType,
                bytes: audioBytes.byteLength,
            });
            resolve(true);
        };

        try {
            if (!isCurrentPlayback(playbackId)) {
                reject(createAbortError('Web Audio playback was cancelled before start'));
                return;
            }

            source.start(0);
            setAudioUnlocked(true);
        } catch (error) {
            reject(error);
        }
    }), timeoutMs, 'Web Audio playback timed out', () => {
        source.onended = null;
        if (currentWebAudioSource === source) {
            currentWebAudioSource = null;
        }

        try {
            source.stop();
        } catch {
            // The source may not have started or may already be stopped.
        }

        publishAudioDiagnostic({
            event: 'play_timeout',
            route: 'web_audio',
            mimeType,
            bytes: audioBytes.byteLength,
            timeoutMs,
        });
    });
};

export const installAudioUnlockListeners = () => {
    if (typeof window === 'undefined') {
        return () => {};
    }

    let isDisposed = false;

    const removeListeners = () => {
        window.removeEventListener('pointerdown', handleUserActivation, true);
        window.removeEventListener('touchend', handleUserActivation, true);
        window.removeEventListener('keydown', handleUserActivation, true);
    };

    const handleUserActivation = () => {
        unlockAudioPlayback().then((unlocked) => {
            if (unlocked && !isDisposed) {
                removeListeners();
            }
        });
    };

    window.addEventListener('pointerdown', handleUserActivation, true);
    window.addEventListener('touchend', handleUserActivation, true);
    window.addEventListener('keydown', handleUserActivation, true);

    return () => {
        isDisposed = true;
        removeListeners();
    };
};

export const createAudioObjectUrl = (audioB64, mimeType = 'audio/mpeg') => {
    if (
        typeof window === 'undefined'
        || typeof window.atob !== 'function'
        || typeof URL === 'undefined'
        || typeof URL.createObjectURL !== 'function'
    ) {
        return `data:${mimeType};base64,${audioB64}`;
    }

    const binary = window.atob(audioB64);
    const bytes = new Uint8Array(binary.length);

    for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
    }

    return URL.createObjectURL(new Blob([bytes], { type: mimeType }));
};

export const revokeAudioObjectUrl = (audioUrl) => {
    if (
        audioUrl?.startsWith('blob:')
        && typeof URL !== 'undefined'
        && typeof URL.revokeObjectURL === 'function'
    ) {
        URL.revokeObjectURL(audioUrl);
    }
};

export const playAudioUrl = async (audioUrl, options = {}) => {
    const playbackId = options.playbackId ?? beginPlayback();
    const audio = getSharedAudioElement();
    if (!audio || !audioUrl) {
        return false;
    }

    if (unlockPromise) {
        await unlockPromise;
    }

    resetAudioElement(audio);
    if (!isCurrentPlayback(playbackId)) {
        throw createAbortError('HTML audio playback was cancelled before load');
    }

    let cleanup = () => {};
    let playbackStarted = false;
    const playbackFinished = new Promise((resolve, reject) => {
        const handleEnded = () => {
            if (!isCurrentPlayback(playbackId)) {
                return;
            }

            cleanup();
            resolve(true);
        };

        const handleError = () => {
            if (!isCurrentPlayback(playbackId)) {
                return;
            }

            cleanup();
            reject(audio.error || new Error('Audio playback failed'));
        };

        const handleAbort = () => {
            if (!playbackStarted) {
                return;
            }

            if (!isCurrentPlayback(playbackId)) {
                return;
            }

            cleanup();
            reject(new Error('Audio playback aborted'));
        };

        const handleStalled = () => {
            if (!playbackStarted) {
                return;
            }

            if (!isCurrentPlayback(playbackId)) {
                return;
            }

            cleanup();
            reject(new Error('Audio playback stalled'));
        };

        const handleEmptied = () => {
            if (!playbackStarted) {
                return;
            }

            if (!isCurrentPlayback(playbackId)) {
                return;
            }

            cleanup();
            reject(new Error('Audio source emptied during playback'));
        };

        cleanup = () => {
            audio.removeEventListener('ended', handleEnded);
            audio.removeEventListener('error', handleError);
            audio.removeEventListener('abort', handleAbort);
            audio.removeEventListener('stalled', handleStalled);
            audio.removeEventListener('emptied', handleEmptied);
        };

        audio.addEventListener('ended', handleEnded);
        audio.addEventListener('error', handleError);
        audio.addEventListener('abort', handleAbort);
        audio.addEventListener('stalled', handleStalled);
        audio.addEventListener('emptied', handleEmptied);
    });

    audio.muted = false;
    audio.src = audioUrl;
    audio.load();

    try {
        const playResult = audio.play();
        if (playResult && typeof playResult.then === 'function') {
            await withTimeout(
                playResult,
                AUDIO_UNLOCK_TIMEOUT_MS,
                'HTML audio play() timed out',
            );
        }

        if (!isCurrentPlayback(playbackId)) {
            throw createAbortError('HTML audio playback was cancelled after play()');
        }

        setAudioUnlocked(true);
        playbackStarted = true;
        const timeoutMs = options.timeoutMs || HTML_AUDIO_PLAY_TIMEOUT_MS;
        return await withTimeout(
            playbackFinished,
            timeoutMs,
            'HTML audio playback timed out',
            () => {
                if (isCurrentPlayback(playbackId)) {
                    resetAudioElement(audio);
                    audio.removeAttribute('src');
                    try {
                        audio.load();
                    } catch {
                        // Mobile browsers may reject load() during teardown.
                    }
                }
                publishAudioDiagnostic({
                    event: 'play_timeout',
                    route: 'html_audio',
                    timeoutMs,
                });
            },
        );
    } catch (error) {
        cleanup();
        if (isCurrentPlayback(playbackId)) {
            resetAudioElement(audio);
            audio.removeAttribute('src');
            try {
                audio.load();
            } catch {
                // Mobile browsers may reject load() during teardown.
            }
        }
        throw error;
    }
};

const playBytesWithHtmlAudio = async (audioBytes, mimeType, options = {}) => {
    const audioUrl = URL.createObjectURL(new Blob([audioBytes], { type: mimeType }));

    try {
        publishAudioDiagnostic({
            event: 'play_start',
            route: 'html_audio',
            mimeType,
            bytes: audioBytes.byteLength,
        });
        return await playAudioUrl(audioUrl, options);
    } finally {
        revokeAudioObjectUrl(audioUrl);
    }
};

export const playAudioBase64 = async (audioB64, mimeType = 'audio/mpeg', options = {}) => {
    if (!audioB64) {
        return false;
    }

    const audioBytes = base64ToUint8Array(audioB64);
    const playbackId = beginPlayback();
    const playbackOptions = { ...options, playbackId };
    const preferHtmlAudio = shouldPreferHtmlAudio();
    let htmlAudioFailed = false;

    if (preferHtmlAudio) {
        try {
            return await playBytesWithHtmlAudio(audioBytes, mimeType, playbackOptions);
        } catch (htmlAudioError) {
            if (!isCurrentPlayback(playbackId)) {
                throw htmlAudioError;
            }

            htmlAudioFailed = true;
            console.warn('[SHARA][audio] HTMLAudioElement playback failed, falling back to Web Audio:', htmlAudioError);
            publishAudioDiagnostic({
                event: 'html_audio_error',
                mimeType,
                bytes: audioBytes.byteLength,
                errorName: htmlAudioError?.name || null,
                errorMessage: htmlAudioError?.message || String(htmlAudioError),
            });
        }
    }

    try {
        return await playBytesWithWebAudio(audioBytes, mimeType, playbackOptions);
    } catch (webAudioError) {
        if (!isCurrentPlayback(playbackId)) {
            throw webAudioError;
        }

        console.warn('[SHARA][audio] Web Audio playback failed, falling back to HTMLAudioElement:', webAudioError);
        publishAudioDiagnostic({
            event: 'web_audio_error',
            mimeType,
            bytes: audioBytes.byteLength,
            errorName: webAudioError?.name || null,
            errorMessage: webAudioError?.message || String(webAudioError),
            audioContextState: sharedAudioContext?.state || null,
        });
    }

    if (htmlAudioFailed) {
        throw new Error('HTMLAudioElement and Web Audio playback both failed');
    }

    return await playBytesWithHtmlAudio(audioBytes, mimeType, playbackOptions);
};
