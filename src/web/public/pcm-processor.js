// Transfer mono frames at the device's native sample rate. Both capture paths
// use the same continuous 16 kHz encoder before VAD and Socket.IO.
class PCMProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.samples = new Float32Array(Math.round(sampleRate / 10));
        this.offset = 0;
    }

    process(inputs) {
        const input = inputs[0]?.[0];
        if (input) {
            for (const sample of input) {
                this.samples[this.offset++] = sample;
                if (this.offset === this.samples.length) {
                    this.port.postMessage(this.samples, [this.samples.buffer]);
                    this.samples = new Float32Array(Math.round(sampleRate / 10));
                    this.offset = 0;
                }
            }
        }
        return true;
    }
}
registerProcessor('pcm-processor', PCMProcessor);
