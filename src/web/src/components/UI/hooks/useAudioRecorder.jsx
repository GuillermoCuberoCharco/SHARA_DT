import { useCallback, useEffect, useRef, useState } from 'react';
import { AUDIO_SETTINGS } from '../../../config';
import { useWebSocketContext } from '../../../contexts/WebSocketContext';

const arrayBufferToBase64 = (buffer) => {
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    let binary = '';

    for (let index = 0; index < bytes.length; index += chunkSize) {
        const slice = bytes.subarray(index, index + chunkSize);
        binary += String.fromCharCode(...slice);
    }

    return btoa(binary);
};

const useAudioRecorder = ({ isWaitingResponse, onAudioSubmitted, onAudioError }) => {
    const { emit } = useWebSocketContext();

    const [isRecording, setIsRecording] = useState(false);
    const [isSpeaking, setIsSpeaking] = useState(false);

    const audioContextRef = useRef(null);
    const analyserRef = useRef(null);
    const streamRef = useRef(null);
    const sourceNodeRef = useRef(null);
    const workletNodeRef = useRef(null);
    const mutedGainRef = useRef(null);
    const silenceFrameRef = useRef(null);
    const silenceStartedAtRef = useRef(null);
    const maxDurationTimeoutRef = useRef(null);
    const workletLoadedRef = useRef(false);
    const startInProgressRef = useRef(false);
    const isRecordingRef = useRef(false);
    const audioStreamStartedRef = useRef(false);
    const audioElementRef = useRef(null);

    const releaseRecordingResources = useCallback(() => {
        if (silenceFrameRef.current) {
            cancelAnimationFrame(silenceFrameRef.current);
            silenceFrameRef.current = null;
        }

        if (maxDurationTimeoutRef.current) {
            clearTimeout(maxDurationTimeoutRef.current);
            maxDurationTimeoutRef.current = null;
        }

        silenceStartedAtRef.current = null;

        if (workletNodeRef.current) {
            workletNodeRef.current.port.onmessage = null;
            workletNodeRef.current.disconnect();
            workletNodeRef.current = null;
        }

        if (mutedGainRef.current) {
            mutedGainRef.current.disconnect();
            mutedGainRef.current = null;
        }

        if (sourceNodeRef.current) {
            sourceNodeRef.current.disconnect();
            sourceNodeRef.current = null;
        }

        if (streamRef.current) {
            streamRef.current.getTracks().forEach((track) => track.stop());
            streamRef.current = null;
        }

        analyserRef.current = null;

        const hadActiveStream = audioStreamStartedRef.current;
        audioStreamStartedRef.current = false;
        return hadActiveStream;
    }, []);

    const stopPlayback = useCallback(() => {
        const audio = audioElementRef.current;
        if (audio) {
            audio.pause();
            audio.currentTime = 0;
            audio.onended = null;
            audio.onerror = null;
            audioElementRef.current = null;
        }
        setIsSpeaking(false);
    }, []);

    const stopRecording = useCallback(() => {
        if (!isRecordingRef.current && !audioStreamStartedRef.current) {
            return;
        }

        isRecordingRef.current = false;
        setIsRecording(false);

        const shouldSubmit = releaseRecordingResources();
        if (shouldSubmit) {
            const sent = emit('audio_stream_end', {});
            if (sent) {
                onAudioSubmitted?.();
            } else {
                onAudioError?.('No he podido enviar el audio al servidor.');
            }
        }
    }, [emit, onAudioError, onAudioSubmitted, releaseRecordingResources]);

    const playAudio = useCallback(async (audioB64) => {
        if (!audioB64) {
            return;
        }

        stopPlayback();

        const audio = new Audio(`data:audio/wav;base64,${audioB64}`);
        audioElementRef.current = audio;
        setIsSpeaking(true);

        const cleanup = () => {
            if (audioElementRef.current === audio) {
                audioElementRef.current = null;
            }
            setIsSpeaking(false);
        };

        audio.onended = cleanup;
        audio.onerror = cleanup;

        try {
            await audio.play();
        } catch (error) {
            console.error('Unable to play assistant audio:', error);
            cleanup();
        }
    }, [stopPlayback]);

    const detectSilence = useCallback(() => {
        if (!analyserRef.current) {
            return;
        }

        const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);

        const checkSilence = () => {
            if (!isRecordingRef.current || !analyserRef.current) {
                return;
            }

            analyserRef.current.getByteFrequencyData(dataArray);

            let sum = 0;
            for (let index = 0; index < dataArray.length; index += 1) {
                sum += dataArray[index];
            }

            const average = sum / dataArray.length;
            if (average < AUDIO_SETTINGS.silenceThreshold) {
                if (!silenceStartedAtRef.current) {
                    silenceStartedAtRef.current = Date.now();
                } else if (Date.now() - silenceStartedAtRef.current >= AUDIO_SETTINGS.silenceDuration) {
                    stopRecording();
                    return;
                }
            } else {
                silenceStartedAtRef.current = null;
            }

            silenceFrameRef.current = requestAnimationFrame(checkSilence);
        };

        silenceFrameRef.current = requestAnimationFrame(checkSilence);
    }, [stopRecording]);

    const startRecording = useCallback(async () => {
        if (startInProgressRef.current || isWaitingResponse || isRecordingRef.current) {
            return;
        }

        startInProgressRef.current = true;

        try {
            if (!navigator.mediaDevices?.getUserMedia) {
                throw new Error('Media devices unavailable');
            }

            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            if (!AudioContextClass || typeof AudioWorkletNode === 'undefined') {
                throw new Error('AudioWorklet unavailable');
            }

            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    sampleRate: AUDIO_SETTINGS.sampleRate,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            });

            streamRef.current = stream;

            if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
                audioContextRef.current = new AudioContextClass({
                    sampleRate: AUDIO_SETTINGS.sampleRate,
                });
            }

            if (audioContextRef.current.state === 'suspended') {
                await audioContextRef.current.resume();
            }

            if (!workletLoadedRef.current) {
                await audioContextRef.current.audioWorklet.addModule('/pcm-processor.js');
                workletLoadedRef.current = true;
            }

            const sourceNode = audioContextRef.current.createMediaStreamSource(stream);
            const analyserNode = audioContextRef.current.createAnalyser();
            analyserNode.fftSize = 256;
            sourceNode.connect(analyserNode);

            const workletNode = new AudioWorkletNode(audioContextRef.current, 'pcm-processor');
            const mutedGain = audioContextRef.current.createGain();
            mutedGain.gain.value = 0;

            sourceNode.connect(workletNode);
            workletNode.connect(mutedGain);
            mutedGain.connect(audioContextRef.current.destination);

            workletNode.port.onmessage = (event) => {
                if (!isRecordingRef.current) {
                    return;
                }

                const pcmBuffer = event.data?.pcm;
                if (!pcmBuffer) {
                    return;
                }

                emit('audio_chunk', { data: arrayBufferToBase64(pcmBuffer) });
            };

            sourceNodeRef.current = sourceNode;
            analyserRef.current = analyserNode;
            workletNodeRef.current = workletNode;
            mutedGainRef.current = mutedGain;

            const started = emit('audio_stream_start', {});
            if (!started) {
                throw new Error('Socket unavailable');
            }

            audioStreamStartedRef.current = true;
            isRecordingRef.current = true;
            setIsRecording(true);

            maxDurationTimeoutRef.current = window.setTimeout(() => {
                stopRecording();
            }, AUDIO_SETTINGS.maxRecordingTime);

            detectSilence();
        } catch (error) {
            console.error('Unable to start recording:', error);
            isRecordingRef.current = false;
            setIsRecording(false);
            releaseRecordingResources();

            const message = error?.name === 'NotAllowedError'
                ? 'No tengo permiso para usar el microfono en este navegador.'
                : 'No he podido iniciar la grabacion de audio.';
            onAudioError?.(message);
        } finally {
            startInProgressRef.current = false;
        }
    }, [detectSilence, emit, isWaitingResponse, onAudioError, releaseRecordingResources, stopRecording]);

    useEffect(() => {
        if (isWaitingResponse && isRecordingRef.current) {
            stopRecording();
        }
    }, [isWaitingResponse, stopRecording]);

    useEffect(() => () => {
        isRecordingRef.current = false;
        releaseRecordingResources();
        stopPlayback();

        if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
            audioContextRef.current.close().catch(() => {});
        }
    }, [releaseRecordingResources, stopPlayback]);

    return {
        isRecording,
        isSpeaking,
        startRecording,
        stopRecording,
        playAudio,
        stopPlayback,
    };
};

export default useAudioRecorder;
