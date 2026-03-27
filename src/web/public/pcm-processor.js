/**
 * AudioWorkletProcessor that converts microphone Float32 samples into
 * LINEAR16 PCM chunks for the backend STT pipeline.
 */

class PCMProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.buffer = [];
        this.chunkSize = 1600;
    }

    process(inputs) {
        const input = inputs[0];
        if (!input || !input[0]) {
            return true;
        }

        const samples = input[0];
        for (let index = 0; index < samples.length; index += 1) {
            this.buffer.push(samples[index]);

            if (this.buffer.length >= this.chunkSize) {
                this.flush();
            }
        }

        return true;
    }

    flush() {
        const int16 = new Int16Array(this.buffer.length);

        for (let index = 0; index < this.buffer.length; index += 1) {
            const clamped = Math.max(-1, Math.min(1, this.buffer[index]));
            int16[index] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
        }

        this.port.postMessage({ pcm: int16.buffer }, [int16.buffer]);
        this.buffer = [];
    }
}

registerProcessor('pcm-processor', PCMProcessor);
