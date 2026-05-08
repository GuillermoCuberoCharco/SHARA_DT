const SILENT_WAV_DATA_URI = 'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQIAAAAAAA==';

let sharedAudioElement = null;
let isUnlocked = false;
let unlockPromise = null;

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

export const unlockAudioPlayback = () => {
    if (isUnlocked) {
        return Promise.resolve(true);
    }

    if (unlockPromise) {
        return unlockPromise;
    }

    const audio = getSharedAudioElement();
    if (!audio) {
        return Promise.resolve(false);
    }

    resetAudioElement(audio);
    audio.muted = false;
    audio.src = SILENT_WAV_DATA_URI;
    audio.load();

    unlockPromise = audio.play()
        .then(() => {
            isUnlocked = true;
            resetAudioElement(audio);
            audio.removeAttribute('src');
            audio.load();
            return true;
        })
        .catch((error) => {
            console.warn('[SHARA][audio] Playback unlock was blocked:', error);
            return false;
        })
        .finally(() => {
            unlockPromise = null;
        });

    return unlockPromise;
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

export const createAudioObjectUrl = (audioB64, mimeType = 'audio/wav') => {
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

        isUnlocked = true;
        return await playbackFinished;
    } catch (error) {
        cleanup();
        throw error;
    }
};
