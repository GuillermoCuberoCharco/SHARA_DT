const SILENT_WAV_DATA_URI = 'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQIAAAAAAA==';

let sharedAudioElement = null;
let sharedAudioContext = null;
let currentWebAudioSource = null;
let isUnlocked = false;
let unlockPromise = null;
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
            setAudioUnlocked(sharedAudioContext?.state === 'running');
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

const unlockWebAudio = async () => {
    const audioContext = getSharedAudioContext();
    if (!audioContext) {
        return false;
    }

    if (audioContext.state === 'suspended') {
        await audioContext.resume();
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

    await audio.play();
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
            const hasWebAudio = Boolean(getBrowserAudioContext());
            const unlocked = webAudioUnlocked || (!hasWebAudio && htmlAudioUnlocked);

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

const playBytesWithWebAudio = async (audioBytes, mimeType) => {
    const audioContext = getSharedAudioContext();
    if (!audioContext) {
        throw new Error('Web Audio API is not available');
    }

    if (unlockPromise) {
        await unlockPromise;
    }

    if (audioContext.state === 'suspended') {
        await audioContext.resume();
    }

    if (audioContext.state !== 'running') {
        throw new Error(`AudioContext is ${audioContext.state}`);
    }

    const audioBuffer = await decodeAudioData(
        audioContext,
        audioBytes.buffer.slice(audioBytes.byteOffset, audioBytes.byteOffset + audioBytes.byteLength),
    );

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

    return new Promise((resolve) => {
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

        source.start(0);
        setAudioUnlocked(true);
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

export const playAudioUrl = async (audioUrl) => {
    const audio = getSharedAudioElement();
    if (!audio || !audioUrl) {
        return false;
    }

    if (unlockPromise) {
        await unlockPromise;
    }

    resetAudioElement(audio);

    let cleanup = () => {};
    const playbackFinished = new Promise((resolve, reject) => {
        const handleEnded = () => {
            cleanup();
            resolve(true);
        };

        const handleError = () => {
            cleanup();
            reject(audio.error || new Error('Audio playback failed'));
        };

        cleanup = () => {
            audio.removeEventListener('ended', handleEnded);
            audio.removeEventListener('error', handleError);
        };

        audio.addEventListener('ended', handleEnded);
        audio.addEventListener('error', handleError);
    });

    audio.muted = false;
    audio.src = audioUrl;
    audio.load();

    try {
        const playResult = audio.play();
        if (playResult && typeof playResult.then === 'function') {
            await playResult;
        }

        setAudioUnlocked(true);
        return await playbackFinished;
    } catch (error) {
        cleanup();
        throw error;
    }
};

export const playAudioBase64 = async (audioB64, mimeType = 'audio/mpeg') => {
    if (!audioB64) {
        return false;
    }

    const audioBytes = base64ToUint8Array(audioB64);

    try {
        return await playBytesWithWebAudio(audioBytes, mimeType);
    } catch (webAudioError) {
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

    const audioUrl = URL.createObjectURL(new Blob([audioBytes], { type: mimeType }));

    try {
        publishAudioDiagnostic({
            event: 'play_start',
            route: 'html_audio',
            mimeType,
            bytes: audioBytes.byteLength,
        });
        return await playAudioUrl(audioUrl);
    } finally {
        revokeAudioObjectUrl(audioUrl);
    }
};
