// Integrate samples over each 16 kHz output interval. Integer phase carries
// across callbacks, including at 44.1 kHz where the ratio is fractional.
export class PcmEncoder {
    constructor(inputRate, outputRate, frameSize, onFrame) {
        this.inputRate = inputRate;
        this.outputRate = outputRate;
        this.onFrame = onFrame;
        this.frame = new Int16Array(frameSize);
        this.offset = 0;
        this.phase = 0;
        this.sum = 0;
    }

    write(samples) {
        for (const sample of samples) {
            let remaining = this.outputRate;
            while (remaining > 0) {
                const weight = Math.min(remaining, this.inputRate - this.phase);
                this.sum += sample * weight;
                this.phase += weight;
                remaining -= weight;
                if (this.phase === this.inputRate) {
                    const value = Math.max(-1, Math.min(1, this.sum / this.inputRate));
                    this.frame[this.offset++] = value * (value < 0 ? 32768 : 32767);
                    this.phase = 0;
                    this.sum = 0;
                    if (this.offset === this.frame.length) {
                        this.onFrame(this.frame.buffer);
                        this.frame = new Int16Array(this.frame.length);
                        this.offset = 0;
                    }
                }
            }
        }
    }
}
