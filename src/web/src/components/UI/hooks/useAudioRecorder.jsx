import axios from 'axios';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AUDIO_SETTINGS, SERVER_URL } from '../../../config';
import { useWebSocketContext } from '../../../contexts/WebSocketContext';
import { playAudioBase64 } from '../../../utils/audioPlayback';

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

const useAudioRecorder = (onTranscriptionComplete, isWaitingResponse, onAudioSubmitted) => {
    const [isRecording, setIsRecording] = useState(false);
    const [audioSrc, setAudioSrc] = useState(null);
    const [isSpeaking, setIsSpeaking] = useState(false);
    const [transcribedText, setTranscribedText] = useState(null);

    const mediaRecorderRef = useRef(null);
    const audioChunksRef = useRef([]);
    const audioContextRef = useRef(null);
    const analyserRef = useRef(null);
    const silenceTimerRef = useRef(null);
    const silenceStartTimeRef = useRef(null);
    const silenceThreshold = useRef(AUDIO_SETTINGS.silenceThreshold);
    const silenceDurationRef = useRef(AUDIO_SETTINGS.silenceDuration);
    const isRecordingRef = useRef(false);
    const isWaitingResponseRef = useRef(isWaitingResponse);

    const lastAverageRef = useRef(0);
    const consecutiveSilenceFramesRef = useRef(0);
    const consecutiveAudioFramesRef = useRef(0);

    const workletNodeRef = useRef(null);
    const startInProgressRef = useRef(false);
    const audioStreamStartedRef = useRef(false);
    const pendingPcmChunksRef = useRef([]);
    const observedChunksRef = useRef(0);
    const speechRunChunksRef = useRef(0);
    const silenceRunChunksRef = useRef(0);
    const hasSpeechRef = useRef(false);
    const noiseFloorRef = useRef(0.006);

    const { socket, emit } = useWebSocketContext();

    const resetStreamingVadState = useCallback(() => {
        audioStreamStartedRef.current = false;
        pendingPcmChunksRef.current = [];
        observedChunksRef.current = 0;
        speechRunChunksRef.current = 0;
        silenceRunChunksRef.current = 0;
        hasSpeechRef.current = false;
        noiseFloorRef.current = 0.006;
    }, []);

    const initializeAudioContext = useCallback(() => {
        if (!audioContextRef.current) {
            try {
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                audioContextRef.current = new AudioContext({ sampleRate: AUDIO_SETTINGS.sampleRate });

                if (audioContextRef.current.state === 'suspended') {
                    audioContextRef.current.resume();
                }

                analyserRef.current = audioContextRef.current.createAnalyser();
                analyserRef.current.fftSize = 256;
                console.log(`AudioContext initialized successfully at ${audioContextRef.current.sampleRate} Hz`);
                return true;
            } catch (error) {
                console.error('Error initializing audio context:', error);
                return false;
            }
        }
        return true;
    }, []);

    useEffect(() => {
        isWaitingResponseRef.current = isWaitingResponse;

        if (isWaitingResponseRef.current && isRecordingRef.current) {
            console.log('Waiting for response, stopping recording...');
            stopRecording();
        }
    }, [isWaitingResponse])

    const stopRecording = useCallback(() => {
        const recorder = mediaRecorderRef.current;
        if (recorder && (isRecordingRef.current || recorder.state === 'recording')) {
            console.log('🛑 Stopping recording...');
            const shouldSubmitToServer = audioStreamStartedRef.current;
            isRecordingRef.current = false;
            if (recorder.state !== 'inactive') {
                recorder.stop();
            }
            setIsRecording(false);

            if (silenceTimerRef.current) {
                cancelAnimationFrame(silenceTimerRef.current);
                silenceTimerRef.current = null;
            }

            silenceStartTimeRef.current = null;
            consecutiveSilenceFramesRef.current = 0;
            consecutiveAudioFramesRef.current = 0;

            if (workletNodeRef.current) {
                workletNodeRef.current.port.onmessage = null;
                workletNodeRef.current.disconnect();
                workletNodeRef.current = null;
            }
            if (shouldSubmitToServer) {
                emit('audio_stream_end', {});
                isWaitingResponseRef.current = true;
                if (onAudioSubmitted) onAudioSubmitted();
                console.log('audio_stream_end sent');
            } else {
                console.log('Recording stopped before speech; server stream was not opened');
                isWaitingResponseRef.current = false;
                onTranscriptionComplete?.();
            }

            resetStreamingVadState();
        }
    }, [emit, onAudioSubmitted, onTranscriptionComplete, resetStreamingVadState]);

    const updateNoiseFloor = useCallback((rms) => {
        noiseFloorRef.current = clampNoiseFloor((noiseFloorRef.current * 0.94) + (rms * 0.06));
    }, []);

    const isSpeechLikeChunk = useCallback((metrics) => {
        const dynamicThreshold = Math.max(
            AUDIO_SETTINGS.vadMinRms,
            noiseFloorRef.current * AUDIO_SETTINGS.vadNoiseMultiplier,
        );
        const zcrInVoiceRange = (
            metrics.zcr >= AUDIO_SETTINGS.vadMinZcr
            && metrics.zcr <= AUDIO_SETTINGS.vadMaxZcr
        );

        return (
            metrics.rms >= dynamicThreshold
            && metrics.peak >= AUDIO_SETTINGS.vadMinPeak
            && zcrInVoiceRange
        );
    }, []);

    const handlePcmChunk = useCallback((pcmBuffer) => {
        if (!isRecordingRef.current || isWaitingResponseRef.current) {
            return;
        }

        const pcmChunk = encodePcmBase64(pcmBuffer);
        const metrics = analyzePcmBuffer(pcmBuffer);
        const isSpeechLike = isSpeechLikeChunk(metrics);
        observedChunksRef.current += 1;
        const maxPreSpeechChunks = Math.max(
            1,
            Math.ceil(AUDIO_SETTINGS.preSpeechBufferMs / AUDIO_SETTINGS.pcmChunkDurationMs),
        );

        if (!audioStreamStartedRef.current) {
            pendingPcmChunksRef.current.push(pcmChunk);
            if (pendingPcmChunksRef.current.length > maxPreSpeechChunks) {
                pendingPcmChunksRef.current.shift();
            }

            if (observedChunksRef.current <= AUDIO_SETTINGS.vadWarmupChunks) {
                if (!isSpeechLike) {
                    updateNoiseFloor(metrics.rms);
                }
                return;
            }

            if (isSpeechLike) {
                speechRunChunksRef.current += 1;
            } else {
                speechRunChunksRef.current = 0;
                updateNoiseFloor(metrics.rms);
            }

            if (speechRunChunksRef.current < AUDIO_SETTINGS.vadStartChunks) {
                return;
            }

            const started = emit('audio_stream_start', {});
            if (!started) {
                console.error('Unable to start server audio stream');
                resetStreamingVadState();
                return;
            }

            audioStreamStartedRef.current = true;
            hasSpeechRef.current = true;
            silenceRunChunksRef.current = 0;

            for (const bufferedChunk of pendingPcmChunksRef.current) {
                emit('audio_chunk', { data: bufferedChunk });
            }
            pendingPcmChunksRef.current = [];

            console.log(
                `[SHARA][vad] voice start rms=${metrics.rms.toFixed(4)} peak=${metrics.peak.toFixed(3)} zcr=${metrics.zcr.toFixed(3)} noise=${noiseFloorRef.current.toFixed(4)}`,
            );
            return;
        }

        emit('audio_chunk', { data: pcmChunk });

        if (isSpeechLike) {
            hasSpeechRef.current = true;
            silenceRunChunksRef.current = 0;
            speechRunChunksRef.current += 1;
            return;
        }

        silenceRunChunksRef.current += 1;
        updateNoiseFloor(metrics.rms);

        if (
            hasSpeechRef.current
            && silenceRunChunksRef.current >= AUDIO_SETTINGS.vadSilenceChunks
        ) {
            console.log(
                `[SHARA][vad] voice end after ${silenceRunChunksRef.current * AUDIO_SETTINGS.pcmChunkDurationMs}ms silence`,
            );
            stopRecording();
        }
    }, [emit, isSpeechLikeChunk, resetStreamingVadState, stopRecording, updateNoiseFloor]);

    const detectSilence = useCallback((stream) => {

        if (!initializeAudioContext()) {
            console.error('Failed to initialize audio context');
            return;
        }

        if (!audioContextRef.current || !analyserRef.current || isWaitingResponseRef.current) return;

        const source = audioContextRef.current.createMediaStreamSource(stream);
        source.connect(analyserRef.current);
        const bufferLength = analyserRef.current.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        const checkSilence = () => {
            if (!isRecordingRef.current || isWaitingResponseRef.current) {
                console.log('Recording stopped, stopping silence detection...');
                cancelAnimationFrame(silenceTimerRef.current);
                silenceTimerRef.current = null;
                return;
            }

            analyserRef.current.getByteFrequencyData(dataArray);

            let sum = 0;
            for (let i = 0; i < bufferLength; i++) {
                sum += dataArray[i];
            }
            const average = sum / bufferLength;

            if (average < silenceThreshold.current) {

                consecutiveSilenceFramesRef.current++;
                consecutiveAudioFramesRef.current = 0;

                if (!silenceStartTimeRef.current) {
                    silenceStartTimeRef.current = Date.now();
                    console.log(`🔇 SILENCE DETECTED - Timer init (avg: ${average.toFixed(2)}, threshold: ${silenceThreshold.current})`);
                } else {
                    const silenceDuration = Date.now() - silenceStartTimeRef.current;
                    const remainingTime = silenceDurationRef.current - silenceDuration;

                    if (consecutiveSilenceFramesRef.current % 60 === 0) {
                        console.log(`⏱️  Silence: ${(silenceDuration / 1000).toFixed(1)}s / ${(silenceDurationRef.current / 1000).toFixed(1)}s ( ${(remainingTime / 1000).toFixed(1)}s remaining)`);
                    }

                    if (silenceDuration >= silenceDurationRef.current) {
                        console.log(`✅ SILENCE THRESHOLD REACHED - Stopping recording (${(silenceDuration / 1000).toFixed(1)}s of silence)`);
                        stopRecording();
                        return;
                    }
                }
            } else {
                consecutiveAudioFramesRef.current++;

                if (silenceStartTimeRef.current !== null) {
                    const interruptedAfter = Date.now() - silenceStartTimeRef.current;
                    console.log(`🔊 AUDIO DETECTED - Silence timer RESET after ${(interruptedAfter / 1000).toFixed(1)}s (avg: ${average.toFixed(2)})`);
                    silenceStartTimeRef.current = null;
                    consecutiveSilenceFramesRef.current = 0;
                }

                if (consecutiveAudioFramesRef.current % 180 === 0) {
                    console.log(`🎤 Audio detected, continuing recording... (avg: ${average.toFixed(2)})`)
                }
            }
            silenceTimerRef.current = requestAnimationFrame(checkSilence);
        };

        console.log('Starting silence detection...');
        silenceTimerRef.current = requestAnimationFrame(checkSilence);
    }, [stopRecording, initializeAudioContext]);

    const startRecording = useCallback(async () => {
        if (startInProgressRef.current || isWaitingResponseRef.current || isRecordingRef.current || isSpeaking) {
            console.log('❌ Recording unable to start:', {
                startInProgress: startInProgressRef.current,
                isWaiting: isWaitingResponseRef.current,
                isRecording: isRecordingRef.current,
                isSpeaking
            });
            return;
        }

        try {
            startInProgressRef.current = true;

            if (mediaRecorderRef.current?.state === 'recording') {
                console.log('⚠️ MediaRecorder is already recording, skipping duplicate start');
                isRecordingRef.current = true;
                setIsRecording(true);
                return;
            }

            console.log('🎤 Starting recording...');
            audioChunksRef.current = [];
            resetStreamingVadState();
            silenceStartTimeRef.current = null;
            consecutiveSilenceFramesRef.current = 0;
            consecutiveAudioFramesRef.current = 0;

            if (!navigator.mediaDevices || !window.MediaRecorder) {
                console.error('❌ MediaDevices or MediaRecorder not supported');
                return;
            }

            const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, sampleRate: AUDIO_SETTINGS.sampleRate } });

            mediaRecorderRef.current = new MediaRecorder(stream, {
                mimeType: AUDIO_SETTINGS.mimeType,
                audioBitsPerSecond: AUDIO_SETTINGS.audioBitsPerSecond
            });
            mediaRecorderRef.current.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunksRef.current.push(event.data);
                }
            };

            const maxRecordingTime = setTimeout(() => {
                if (isRecordingRef.current) {
                    console.log(`Max recording time reached`);
                    stopRecording();
                }
            }, AUDIO_SETTINGS.maxRecordingTime);

            mediaRecorderRef.current.onstop = async () => {
                clearTimeout(maxRecordingTime);
                const audioBlob = new Blob(audioChunksRef.current, { type: AUDIO_SETTINGS.mimeType });

                console.log(`📦 Recording stopped - Size: ${(audioBlob.size / 1024).toFixed(2)} KB, Chunks: ${audioChunksRef.current.length}`);

                stream.getTracks().forEach(track => track.stop());
                mediaRecorderRef.current = null;
            };

            try {
                if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
                    const AudioContext = window.AudioContext || window.webkitAudioContext;
                    audioContextRef.current = new AudioContext({ sampleRate: AUDIO_SETTINGS.sampleRate });
                    analyserRef.current = audioContextRef.current.createAnalyser();
                    analyserRef.current.fftSize = 256;
                    console.log(`AudioContext initialized at ${audioContextRef.current.sampleRate} Hz`);
                }
                if (audioContextRef.current.state === 'suspended') {
                    await audioContextRef.current.resume();
                }

                await audioContextRef.current.audioWorklet.addModule('/pcm-processor.js');

                const workletSource = audioContextRef.current.createMediaStreamSource(stream);
                const workletNode = new AudioWorkletNode(audioContextRef.current, 'pcm-processor');
                workletNodeRef.current = workletNode;
                workletSource.connect(workletNode);

                workletNode.port.onmessage = (event) => {
                    if (!isRecordingRef.current) return;
                    handlePcmChunk(event.data.pcm);
                };
            } catch (workletError) {
                console.warn('⚠️ AudioWorklet unavailable, falling back to blob STT:', workletError);
                // Fallback: on stop, send the entire recording as a blob for transcription
                mediaRecorderRef.current.onstop = async () => {
                    clearTimeout(maxRecordingTime);
                    const audioBlob = new Blob(audioChunksRef.current, { type: AUDIO_SETTINGS.mimeType });
                    console.log(`📦 FALLBACK Recording stopped - Size: ${(audioBlob.size / 1024).toFixed(2)} KB, Chunks: ${audioChunksRef.current.length}`);
                    if (audioChunksRef.current.length > 0) {
                        await handleTranscribe(audioBlob);
                    }
                    stream.getTracks().forEach(track => track.stop());
                };
                detectSilence(stream);
            }

            isRecordingRef.current = true;
            mediaRecorderRef.current.start(100);
            setIsRecording(true);

            console.log('✅ Successfully started recording');

        } catch (error) {
            console.error('❌ Error starting recording:', error);
            return;
        } finally {
            startInProgressRef.current = false;
        }
    }, [detectSilence, handlePcmChunk, resetStreamingVadState, stopRecording, isSpeaking]);

    useEffect(() => {
        return () => {
            if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
                audioContextRef.current.close();
            }
        };
    }, []);

    const handleTranscribe = async (audioBlob) => {
        if (isWaitingResponseRef.current) {
            console.log('⏸️  Waiting for response, canceling transcription');
            return;
        }

        if (!audioBlob || audioBlob.size === 0) {
            console.log('⚠️ No audio blob to transcribe');
            return;
        }

        isWaitingResponseRef.current = true;

        const actualBlob = audioBlob.blob || audioBlob;
        console.log(`🔄 Transcribing audio blob of size: ${(actualBlob.size / 1024).toFixed(2)} KB`);

        try {
            // Wrap FileReader in a Promise so the await below actually waits
            // for onloadend before continuing — the old pattern used readAsDataURL
            // (non-blocking) inside try/finally, so finally ran synchronously
            // BEFORE onloadend fired, resetting isWaitingResponseRef too early.
            await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onerror = reject;
                reader.onloadend = () => {
                    try {
                        const base64Audio = reader.result.split(',')[1];
                        const messageObject = {
                            type: 'audio',
                            data: base64Audio,
                            socketId: socket?.id,
                        };
                        // emit() uses socketRef.current internally — always fresh,
                        // avoids the stale-closure problem with the `socket` value.
                        const sent = emit('client_message', messageObject);
                        if (sent) {
                            console.log('📤 Audio sent via socket for transcription and processing');
                            isWaitingResponseRef.current = false;
                        } else {
                            console.error('❌ Socket not connected, cannot send audio');
                            isWaitingResponseRef.current = false;
                        }
                    } catch (err) {
                        reject(err);
                        return;
                    }
                    resolve();
                };
                reader.readAsDataURL(actualBlob);
            });
        } catch (error) {
            console.error('Error transcribing audio:', error);
            isWaitingResponseRef.current = false;
        }
        // On success, isWaitingResponseRef.current stays true.
        // It is released when the server responds: robot_message →
        // handleRobotMessage in UI.jsx → setIsWaitingResponse(false) →
        // useEffect syncs isWaitingResponseRef.current = false.
    };

    const handleSynthesize = async (
        text,
        audioB64 = null,
        audioMimeType = 'audio/mpeg',
        options = {},
    ) => {
        if (!text && !audioB64) return;

        let audioPayload = audioB64;
        let resolvedAudioMimeType = audioMimeType || 'audio/mpeg';
        const playbackTimeoutMs = options.timeoutMs || 45000;

        try {
            setIsSpeaking(true);
            console.log('🔊 Synthesizing speech...');

            if (!audioPayload && text) {
                // Fallback: request TTS synthesis via HTTP (only when no audio in message)
                const response = await axios.post(
                    `${SERVER_URL}/api/synthesize`,
                    { text },
                    { timeout: Math.max(10000, playbackTimeoutMs) },
                );
                if (response.data?.audioContent) {
                    resolvedAudioMimeType = response.data.audioMimeType || 'audio/mpeg';
                    audioPayload = response.data.audioContent;
                }
            }

            if (audioPayload) {
                setAudioSrc(`audio:${resolvedAudioMimeType}`);
                await playAudioBase64(audioPayload, resolvedAudioMimeType, {
                    timeoutMs: playbackTimeoutMs,
                });
                console.log('[SHARA][audio] Audio playback finished');
            }
        } catch (error) {
            if (error?.name === 'NotAllowedError') {
                console.warn('[SHARA][audio] Browser blocked playback until a user gesture unlocks audio.');
            }
            console.error('❌ Error synthesizing speech:', error);
            throw error;
        } finally {
            setIsSpeaking(false);
            setAudioSrc(null);
        }
    };

    handleSynthesize.cancel = () => {
        setIsSpeaking(false);
        setAudioSrc(null);
    };

    const onStop = () => {
        setIsSpeaking(false);
    };



    return {
        isRecording,
        transcribedText,
        audioSrc,
        isSpeaking,
        startRecording,
        stopRecording,
        handleTranscribe,
        handleSynthesize,
        onStop
    };
};

export default useAudioRecorder;
