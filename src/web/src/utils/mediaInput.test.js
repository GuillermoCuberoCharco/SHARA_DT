import test from 'node:test';
import assert from 'node:assert/strict';
import { PcmEncoder } from './pcmEncoder.js';
import { openInput } from './mediaInput.js';

test('releases the camera before requesting a microphone and stops it on abort', async () => {
    const events = [];
    const request = async constraints => {
        const kind = constraints.video ? 'camera' : 'microphone';
        events.push('open ' + kind);
        return { getTracks: () => [{ stop: () => events.push('close ' + kind) }] };
    };
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: request } } });
    const camera = new AbortController();
    const mic = new AbortController();
    await openInput({ video: true }, camera.signal);
    await openInput({ audio: true }, mic.signal);
    camera.abort();
    mic.abort();
    assert.deepEqual(events, ['open camera', 'close camera', 'open microphone', 'close microphone']);
});

test('disposes permission granted after cancellation without touching the next device', async () => {
    const stopped = [];
    let resolveCamera;
    const stream = kind => ({ getTracks: () => [{ stop: () => stopped.push(kind) }] });
    navigator.mediaDevices.getUserMedia = constraints => constraints.video
        ? new Promise(resolve => { resolveCamera = resolve; }) : Promise.resolve(stream('mic'));
    const first = new AbortController();
    const next = new AbortController();
    const late = openInput({ video: true }, first.signal);
    first.abort();
    await openInput({ audio: true }, next.signal);
    resolveCamera(stream('camera'));
    await assert.rejects(late, { name: 'AbortError' });
    assert.deepEqual(stopped, ['camera']);
    next.abort();
    assert.deepEqual(stopped, ['camera', 'mic']);
});

for (const rate of [16000, 44100, 48000]) {
    test(`encodes one second at ${rate} Hz as ten 100 ms mono LINEAR16 frames`, () => {
        const frames = [];
        const encoder = new PcmEncoder(rate, 16000, 1600, b => frames.push(new Int16Array(b)));
        const input = new Float32Array(rate).fill(0.5);
        for (let i = 0; i < input.length; i += 128) encoder.write(input.subarray(i, i + 128));
        assert.equal(frames.length, 10);
        for (const frame of frames) {
            assert.equal(frame.length, 1600);
            assert.ok(frame.every(value => value === 16383));
        }
    });
}
