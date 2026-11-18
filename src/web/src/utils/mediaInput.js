// A permission request can finish after its turn was cancelled. Install ownership
// before requesting access and dispose a late stream before exposing it to callers.
let owner = null;

export async function openInput(constraints, signal) {
    if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('El navegador no permite acceder a los dispositivos.');
    }
    owner?.();
    let stream;
    let released = false;
    const release = () => {
        released = true;
        stream?.getTracks().forEach(track => track.stop());
        if (owner === release) owner = null;
        signal.removeEventListener('abort', release);
    };
    owner = release;
    signal.addEventListener('abort', release, { once: true });
    try {
        if (signal.aborted) throw new DOMException('Cancelado', 'AbortError');
        stream = await navigator.mediaDevices.getUserMedia(constraints);
        if (released || signal.aborted) throw new DOMException('Cancelado', 'AbortError');
        return stream;
    } catch (error) {
        release();
        throw error;
    }
}
