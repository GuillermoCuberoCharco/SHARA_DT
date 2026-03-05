/**
 * pcm-processor.js
 * AudioWorkletProcessor that captures raw PCM samples from the microphone
 * and converts them to LINEAR16 (16 bit signed integer at 16kHz) format.
 * 
 * Equivalen to PyAudio's stream.read() on the physical robot.
 * 
 * Loaded via: audioContext.audioWorklet.addModule('/pcm-processor.js')
 */

class PCMProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this._buffer = [];
        this._chunkSize = 1600;
    }

    /**
     * Called by the browser for every 128-sample render quantum.
     * We accumulate sampels and flush a chunk every _chunkSize samples.
     * 
     * @param {Float32Array[][]} inputs - [[left_channel_float32], ...]
     */
    process(inputs) {
        const input = inputs[0];
        if (!input || !input[0]) return true; // No input, keep processor alive

        const float32Samples = input[0]; // mono channel

        for (let i = 0; i < float32Samples.length; i++) {
            this._buffer.push(float32Samples[i]);

            if (this._buffer.length >= this._chunkSize) {
                this._flush();
            }
        }

        return true; // Keep processor alive
    }

    /**
     * Converts accumulate Float32 samples -> Int16 PCM and posts to main thread.
     */
    _flush() {
        const int16 = new Int16Array(this._buffer.length);
        for (let i = 0; i < this._buffer.length; i++) {
            const clamped = Math.max(-1, Math.min(1, this._buffer[i]));
            int16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7FFF;
        }
        // Transfer the underlying ArrayBuffer to avoid copying
        this.port.postMessage({ pcm: int16.buffer }, [int16.buffer]);
        this._buffer = [];
    }
}

registerProcessor('pcm-processor', PCMProcessor);