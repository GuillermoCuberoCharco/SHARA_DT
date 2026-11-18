import { useEffect } from 'react';
import { AUDIO_SETTINGS as settings } from '../../../config';
import { openInput } from '../../../utils/mediaInput';
import { PcmEncoder } from '../../../utils/pcmEncoder';

const encodePcmBase64 = (pcmBuffer) => {
    const uint8 = new Uint8Array(pcmBuffer);
    let binary = '';
    for (let i = 0; i < uint8.length; i++) {
        binary += String.fromCharCode(uint8[i]);
    }
    return btoa(binary);
};

const clampNoiseFloor = (value) => Math.max(0.0008, Math.min(value, 0.05));

const analyzePcmBuffer = (pcmBuffer) => {
    const samples = new Int16Array(pcmBuffer);
    if (!samples.length) {
        return { rms: 0, peak: 0, zcr: 0 };
    }

    let sumSquares = 0;
    let peak = 0;
    let zeroCrossings = 0;
    let previousSign = 0;

    for (let i = 0; i < samples.length; i++) {
        const sample = samples[i] / 32768;
        const abs = Math.abs(sample);
        sumSquares += sample * sample;
        if (abs > peak) peak = abs;

        const sign = sample >= 0 ? 1 : -1;
        if (i > 0 && previousSign !== sign) {
            zeroCrossings++;
        }
        previousSign = sign;
    }

    return {
        rms: Math.sqrt(sumSquares / samples.length),
        peak,
        zcr: zeroCrossings / Math.max(1, samples.length - 1),
    };
};

// Keep the same capture across listening -> recording. Leaving the turn revokes
// the permission request, every track and every pending callback owned by it.
export default function useAudioRecorder(active, sessionId, turnId, emit, onError) {
    useEffect(() => {
        if (!active) return;
        const controller = new AbortController();
        const { signal } = controller;
        const identity = { sessionId, turnId };
        let context, node, source, timer, gain;
        let speaking = false;
        let ready = false;
        let noise = 0.006;
        let consecutive = 0;
        let silent = 0;
        const buffered = [];
        function release() {
            controller.abort();
            clearTimeout(timer);
            if (node?.port) node.port.onmessage = null;
            if (node && 'onaudioprocess' in node) node.onaudioprocess = null;
            node?.disconnect();
            gain?.disconnect();
            source?.disconnect();
            if (context && context.state !== 'closed') context.close().catch(() => {});
        }
        function finish() {
            if (signal.aborted) return;
            release();
            emit('audio_stream_end', speaking ? identity : { ...identity, reason: 'silence' });
        }
        function fail() {
            if (signal.aborted) return;
            release();
            onError();
            emit('device_error', { ...identity, device: 'microphone' });
        }
        function send(buffer) {
            emit('audio_chunk', { ...identity, data: encodePcmBase64(buffer) });
        }
        function chunk(buffer) {
            if (signal.aborted) return;
            if (!ready) {
                ready = true;
                emit('microphone_ready', identity);
                timer = setTimeout(finish, settings.maxRecordingTime);
            }
            const { rms, peak, zcr } = analyzePcmBuffer(buffer);
            const voice = rms >= Math.max(settings.vadMinRms, noise * settings.vadNoiseMultiplier)
                && peak >= settings.vadMinPeak && zcr >= settings.vadMinZcr && zcr <= settings.vadMaxZcr;
            if (!voice) noise = clampNoiseFloor(noise * 0.94 + rms * 0.06);
            if (!speaking) {
                buffered.push(buffer);
                if (buffered.length > Math.ceil(settings.preSpeechBufferMs / settings.pcmChunkDurationMs)) buffered.shift();
                consecutive = voice ? consecutive + 1 : 0;
                if (consecutive < settings.vadStartChunks) return;
                if (!emit('audio_stream_start', identity)) return fail();
                speaking = true;
                buffered.forEach(send);
                buffered.length = 0;
            } else {
                send(buffer);
                silent = voice ? 0 : silent + 1;
                if (silent * settings.pcmChunkDurationMs >= settings.silenceDuration) finish();
            }
        }
        async function start() {
            const stream = await openInput({ audio: { channelCount: 1, sampleRate: settings.sampleRate } }, signal);
            if (signal.aborted) return;
            stream.getAudioTracks()[0].onended = fail;
            const Audio = window.AudioContext || window.webkitAudioContext;
            context = new Audio();
            const encoder = new PcmEncoder(context.sampleRate, settings.sampleRate,
                settings.sampleRate * settings.pcmChunkDurationMs / 1000, chunk);
            await context.resume();
            if (signal.aborted) return;
            source = context.createMediaStreamSource(stream);
            gain = context.createGain();
            gain.gain.value = 0;
            gain.connect(context.destination);
            try {
                await context.audioWorklet.addModule('/pcm-processor.js');
                if (signal.aborted) return;
                node = new AudioWorkletNode(context, 'pcm-processor');
                node.port.onmessage = event => encoder.write(event.data);
                node.onprocessorerror = fail;
            } catch (error) {
                if (signal.aborted) return;
                // Browsers without AudioWorklet still send identical mono PCM.
                node = context.createScriptProcessor(2048, 1, 1);
                node.onaudioprocess = event => encoder.write(event.inputBuffer.getChannelData(0));
            }
            source.connect(node);
            node.connect(gain);
        }
        start().catch(fail);
        return release;
    }, [active, sessionId, turnId, emit, onError]);
}
