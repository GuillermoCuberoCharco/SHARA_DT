/**
 * useAudioRecorder.jsx
 *
 * Audio recording hook using AudioWorklet to capture raw PCM LINEAR16
 * and stream it to the server via WebSocket — identical to the physical
 * robot's PyAudio → queue → Google streaming STT pipeline.
 *
 * Flow:
 *   getUserMedia (mono, 16kHz)
 *     → AudioContext (16000 Hz, mono)
 *       → PCMProcessor (AudioWorklet) — 100ms chunks of Int16 PCM
 *         → socket.emit('audio_chunk', base64_pcm)   [while recording]
 *   stopRecording()
 *     → socket.emit('audio_stream_end')
 *     → server runs Google streaming_recognize → emits 'transcription_result'
 *     → state_machine processes LLM + TTS
 *
 * Silence detection is kept from the previous implementation using
 * a separate AnalyserNode on the same stream, so the UX auto-stops
 * recording when the user stops speaking.
 */

import axios from 'axios';
import { useCallback, useEffect, useRef, useState } from 'react';
import { SERVER_URL } from '../../../config';
import { useWebSocketContext } from '../../../contexts/WebSocketContext';

// ── Audio constants ────────────────────────────────────────────────────────
// Match the robot's PyAudio configuration
const SAMPLE_RATE = 16000;          // Hz — same as robot's mic
const SILENCE_THRESHOLD = 15;      // RMS amplitude (0-255 scale)
const SILENCE_DURATION_MS = 2000;  // ms of silence before auto-stop
const MAX_RECORDING_MS = 50000;    // hard cap

const useAudioRecorder = (onTranscriptionComplete, isWaitingResponse) => {
    const [isRecording, setIsRecording] = useState(false);
    const [audioSrc, setAudioSrc] = useState(null);
    const [isSpeaking, setIsSpeaking] = useState(false);
    const [transcribedText, setTranscribedText] = useState(null);

    // Refs — avoid stale closures in callbacks
    const audioContextRef = useRef(null);
    const workletNodeRef = useRef(null);
    const analyserRef = useRef(null);
    const streamRef = useRef(null);
    const silenceTimerRef = useRef(null);
    const silenceStartTimeRef = useRef(null);
    const maxRecordingTimerRef = useRef(null);
    const isRecordingRef = useRef(false);
    const isWaitingResponseRef = useRef(isWaitingResponse);
    const consecutiveSilenceFramesRef = useRef(0);

    const { socket, emit } = useWebSocketContext();

    // Keep isWaitingResponseRef in sync with prop
    useEffect(() => {
        isWaitingResponseRef.current = isWaitingResponse;
    }, [isWaitingResponse]);

    // ── Silence detection (runs on rAF while recording) ─────────────────────

    const detectSilence = useCallback((stream) => {
        if (!analyserRef.current) return;

        const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);

        const check = () => {
            if (!isRecordingRef.current) return;

            analyserRef.current.getByteFrequencyData(dataArray);
            const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;

            if (average < SILENCE_THRESHOLD) {
                consecutiveSilenceFramesRef.current++;
                if (!silenceStartTimeRef.current) {
                    silenceStartTimeRef.current = Date.now();
                }
                const silenceDuration = Date.now() - silenceStartTimeRef.current;
                if (silenceDuration >= SILENCE_DURATION_MS) {
                    console.log(`🤫 Silence detected (${silenceDuration}ms) — stopping`);
                    stopRecording();
                    return;
                }
            } else {
                consecutiveSilenceFramesRef.current = 0;
                silenceStartTimeRef.current = null;
            }

            silenceTimerRef.current = requestAnimationFrame(check);
        };

        silenceTimerRef.current = requestAnimationFrame(check);
    }, []);  // stopRecording added below via ref pattern

    // ── Stop recording ───────────────────────────────────────────────────────

    const stopRecording = useCallback(() => {
        if (!isRecordingRef.current) return;

        console.log('⏹ Stopping PCM stream recording');
        isRecordingRef.current = false;
        setIsRecording(false);

        // Cancel timers
        if (silenceTimerRef.current) {
            cancelAnimationFrame(silenceTimerRef.current);
            silenceTimerRef.current = null;
        }
        if (maxRecordingTimerRef.current) {
            clearTimeout(maxRecordingTimerRef.current);
            maxRecordingTimerRef.current = null;
        }

        // Disconnect worklet
        if (workletNodeRef.current) {
            workletNodeRef.current.port.onmessage = null;
            workletNodeRef.current.disconnect();
            workletNodeRef.current = null;
        }

        // Stop media tracks
        if (streamRef.current) {
            streamRef.current.getTracks().forEach(t => t.stop());
            streamRef.current = null;
        }

        // Signal end of stream to server → triggers Google streaming_recognize
        const sent = emit('audio_stream_end', {});
        if (sent) {
            console.log('audio_stream_end sent — server will run streaming STT');
        } else {
            console.error('❌ Could not send audio_stream_end — socket disconnected');
        }
    }, [emit]);

    // ── Start recording ──────────────────────────────────────────────────────

    const startRecording = useCallback(async () => {
        if (isWaitingResponseRef.current || isRecordingRef.current || isSpeaking) {
            console.log('❌ Recording blocked:', {
                isWaiting: isWaitingResponseRef.current,
                isRecording: isRecordingRef.current,
                isSpeaking,
            });
            return;
        }

        try {
            console.log('Starting PCM stream recording (LINEAR16, 16kHz)...');

            // Request mono microphone access
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    sampleRate: SAMPLE_RATE,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            });
            streamRef.current = stream;

            // Create AudioContext at exactly 16000 Hz to avoid resampling
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
                await audioContextRef.current.close();
            }
            audioContextRef.current = new AudioContext({ sampleRate: SAMPLE_RATE });

            // Analyser for silence detection
            analyserRef.current = audioContextRef.current.createAnalyser();
            analyserRef.current.fftSize = 256;

            // Load the PCM processor worklet (served from /public)
            await audioContextRef.current.audioWorklet.addModule('/pcm-processor.js');

            const source = audioContextRef.current.createMediaStreamSource(stream);
            const workletNode = new AudioWorkletNode(audioContextRef.current, 'pcm-processor');
            workletNodeRef.current = workletNode;

            // Connect: source → analyser (for silence detection)
            source.connect(analyserRef.current);
            // Connect: source → worklet (for PCM capture)
            source.connect(workletNode);
            // worklet output not needed for audio playback
            workletNode.connect(audioContextRef.current.destination);

            // Signal start to server
            emit('audio_stream_start', {});
            console.log('audio_stream_start sent');

            // Forward PCM chunks to server
            workletNode.port.onmessage = (event) => {
                if (!isRecordingRef.current) return;
                const pcmBuffer = event.data.pcm; // ArrayBuffer with Int16 PCM
                // Convert to base64 for socket transport
                const uint8 = new Uint8Array(pcmBuffer);
                let binary = '';
                for (let i = 0; i < uint8.length; i++) {
                    binary += String.fromCharCode(uint8[i]);
                }
                const base64Chunk = btoa(binary);
                emit('audio_chunk', { data: base64Chunk });
            };

            isRecordingRef.current = true;
            silenceStartTimeRef.current = null;
            consecutiveSilenceFramesRef.current = 0;
            setIsRecording(true);

            // Hard cap timer
            maxRecordingTimerRef.current = setTimeout(() => {
                if (isRecordingRef.current) {
                    console.log('Max recording time reached');
                    stopRecording();
                }
            }, MAX_RECORDING_MS);

            // Start silence detection
            detectSilence(stream);

            console.log('✅ PCM stream recording active');

        } catch (error) {
            console.error('❌ Error starting PCM recording:', error);
            isRecordingRef.current = false;
            setIsRecording(false);
        }
    }, [isSpeaking, emit, detectSilence, stopRecording]);

    // ── TTS playback ─────────────────────────────────────────────────────────

    const handleSynthesize = useCallback(async (text) => {
        if (!text) return;

        try {
            setIsSpeaking(true);
            console.log('🔊 Synthesizing speech...');

            const response = await axios.post(`${SERVER_URL}/api/synthesize`, { text });

            if (response.data?.audioContent) {
                const audioSrc = `data:audio/wav;base64,${response.data.audioContent}`;
                setAudioSrc(audioSrc);

                await new Promise((resolve, reject) => {
                    const audio = new Audio(audioSrc);
                    audio.onerror = reject;
                    audio.onended = () => {
                        console.log('✅ TTS playback finished');
                        resolve();
                    };
                    audio.play().catch(reject);
                });
            }
        } catch (error) {
            console.error('❌ Error synthesizing speech:', error);
        } finally {
            setIsSpeaking(false);
            setAudioSrc(null);
        }
    }, []);

    // ── Cleanup on unmount ───────────────────────────────────────────────────

    useEffect(() => {
        return () => {
            isRecordingRef.current = false;
            if (silenceTimerRef.current) cancelAnimationFrame(silenceTimerRef.current);
            if (maxRecordingTimerRef.current) clearTimeout(maxRecordingTimerRef.current);
            if (workletNodeRef.current) {
                workletNodeRef.current.port.onmessage = null;
                workletNodeRef.current.disconnect();
            }
            if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
            if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
                audioContextRef.current.close();
            }
        };
    }, []);

    return {
        isRecording,
        transcribedText,
        audioSrc,
        isSpeaking,
        startRecording,
        stopRecording,
        handleSynthesize,
    };
};

export default useAudioRecorder;