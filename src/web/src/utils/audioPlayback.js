const SILENT_WAV_DATA_URI = 'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQIAAAAAAA==';

let sharedAudioElement = null;
let currentObjectUrl = null;
let currentPlaybackCleanup = null;
let currentPlaybackResolve = null;
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

const revokeCurrentObjectUrl = () => {
    if (currentObjectUrl && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
        URL.revokeObjectURL(currentObjectUrl);
    }
    currentObjectUrl = null;
};

export const stopAudioPlayback = () => {
    const audio = getSharedAudioElement();
    if (!audio) {
        return;
    }

    if (currentPlaybackCleanup) {
        currentPlaybackCleanup();
        currentPlaybackCleanup = null;
    }
    if (currentPlaybackResolve) {
        currentPlaybackResolve(false);
        currentPlaybackResolve = null;
    }

    audio.pause();
    audio.removeAttribute('src');
    try {
        audio.currentTime = 0;
    } catch {
        // Some browsers reject currentTime changes before metadata exists.
    }
    audio.load();
    revokeCurrentObjectUrl();
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

    audio.muted = false;
    audio.src = SILENT_WAV_DATA_URI;
    audio.load();

    unlockPromise = audio.play()
        .then(() => {
            audio.pause();
            audio.removeAttribute('src');
            audio.load();
            isUnlocked = true;
            return true;
        })
        .catch((error) => {
            console.warn('[SHARA][audio] Playback unlock was blocked:', error);
            audio.removeAttribute('src');
            audio.load();
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

export const playAudioBase64 = async (audioB64, mimeType = 'audio/wav') => {
    const audio = getSharedAudioElement();
    if (!audio || !audioB64) {
        return false;
    }

    if (unlockPromise) {
        await unlockPromise;
    }

    stopAudioPlayback();

    const binary = window.atob(audioB64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
    }

    currentObjectUrl = URL.createObjectURL(new Blob([bytes], { type: mimeType }));

    return new Promise((resolve, reject) => {
        let settled = false;

        const cleanup = () => {
            audio.removeEventListener('ended', handleEnded);
            audio.removeEventListener('error', handleError);
        };

        const finish = (callback, value) => {
            if (settled) {
                return;
            }

            settled = true;
            cleanup();
            currentPlaybackCleanup = null;
            currentPlaybackResolve = null;
            revokeCurrentObjectUrl();
            callback(value);
        };

        const handleEnded = () => {
            finish(resolve, true);
        };

        const handleError = () => {
            const error = audio.error || new Error('Audio playback failed');
            finish(reject, error);
        };

        currentPlaybackCleanup = cleanup;
        currentPlaybackResolve = resolve;
        audio.addEventListener('ended', handleEnded);
        audio.addEventListener('error', handleError);
        audio.muted = false;
        audio.src = currentObjectUrl;
        audio.load();

        const playResult = audio.play();
        if (playResult && typeof playResult.then === 'function') {
            playResult.catch((error) => {
                finish(reject, error);
            });
        }
    });
};
