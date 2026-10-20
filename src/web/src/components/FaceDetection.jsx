import * as blazeface from '@tensorflow-models/blazeface';
import * as tf from '@tensorflow/tfjs';
import { useEffect, useRef, useState } from 'react';
import { FACE_DETECTION_SETTINGS } from '../../src/config';
import { useWebSocketContext } from '../contexts/WebSocketContext';
import { buildSessionIdentity } from '../utils/sessionIdentity';
import {
    getFaceObservation,
    getIntersectionOverUnion,
    validateFaceObservation,
} from './faceDetectionUtils';

const FaceDetection = ({ onFaceDetected, onFaceLost, stream, sessionIdentity }) => {
    const videoRef = useRef(null);
    const modelRef = useRef(null);
    const detectionRef = useRef(null);
    const inferenceTokenRef = useRef(null);
    const presenceActiveRef = useRef(false);
    const candidateStartedAtRef = useRef(null);
    const candidateBoxRef = useRef(null);
    const consecutiveDetectionsRef = useRef(0);
    const consecutiveLossesRef = useRef(0);
    const lastDetectionTimeRef = useRef(null);
    const sessionIdentityRef = useRef(sessionIdentity);
    const onFaceDetectedRef = useRef(onFaceDetected);
    const onFaceLostRef = useRef(onFaceLost);
    const [isModelLoaded, setIsModelLoaded] = useState(false);
    const [isStreamReady, setIsStreamReady] = useState(false);

    const { emit, isConnected, isRegistered } = useWebSocketContext();

    useEffect(() => {
        sessionIdentityRef.current = sessionIdentity;
        onFaceDetectedRef.current = onFaceDetected;
        onFaceLostRef.current = onFaceLost;
    }, [onFaceDetected, onFaceLost, sessionIdentity]);

    useEffect(() => {
        let cancelled = false;

        const loadBlazeFaceModel = async () => {
            try {
                console.log('Initializing TensorFlow...');
                await tf.ready();
                await tf.setBackend('webgl');
                console.log('TensorFlow initialized with backend:', tf.getBackend());

                console.log('Loading BlazeFace model...');
                const model = await blazeface.load({
                    maxFaces: 1,
                    inputWidth: 128,
                    inputHeight: 128,
                    iouThreshold: 0.3,
                    scoreThreshold: FACE_DETECTION_SETTINGS.modelScoreThreshold,
                });

                if (cancelled) {
                    model.dispose?.();
                    return;
                }

                modelRef.current = model;
                setIsModelLoaded(true);
                console.log('BlazeFace model loaded successfully');
            } catch (error) {
                if (!cancelled) {
                    console.error('Error loading BlazeFace model:', error);
                }
            }
        };

        loadBlazeFaceModel();

        return () => {
            cancelled = true;
            modelRef.current?.dispose?.();
            modelRef.current = null;
        };
    }, []);

    useEffect(() => {
        if (!stream || !videoRef.current) {
            return undefined;
        }

        console.log('Setting up video stream...');
        const video = videoRef.current;
        video.srcObject = stream;

        video.onloadedmetadata = () => {
            video.play()
                .then(() => {
                    console.log('Video playback started');
                    setIsStreamReady(true);
                })
                .catch((error) => console.error('Video playback error:', error));
        };

        return () => {
            setIsStreamReady(false);
            video.onloadedmetadata = null;
            video.srcObject = null;
        };
    }, [stream]);

    useEffect(() => {
        const sessionId = sessionIdentity?.sessionId;
        const canEmitPresence = isConnected && isRegistered && sessionId;

        if (!isModelLoaded || !isStreamReady || !videoRef.current || !canEmitPresence) {
            return undefined;
        }

        let active = true;

        const resetCandidate = () => {
            consecutiveDetectionsRef.current = 0;
            candidateStartedAtRef.current = null;
            candidateBoxRef.current = null;
        };

        const emitUserLost = (reason, lastSeenAgoMs = null) => {
            if (!presenceActiveRef.current) {
                resetCandidate();
                return;
            }

            presenceActiveRef.current = false;
            consecutiveLossesRef.current = 0;
            lastDetectionTimeRef.current = null;
            resetCandidate();
            onFaceLostRef.current?.();
            emit('user_lost', {
                sessionId,
                reason,
                lastSeenAgoMs,
            });
            console.info('[FaceDetection] Presence lost', { reason, lastSeenAgoMs });
        };

        const confirmPresence = (observation, now) => {
            const stableDurationMs = now - candidateStartedAtRef.current;
            const video = videoRef.current;
            const detectionDetails = {
                confidence: Number(observation.probability.toFixed(3)),
                left: Math.round(observation.left),
                top: Math.round(observation.top),
                width: Math.round(observation.width),
                height: Math.round(observation.height),
                videoWidth: video?.videoWidth || null,
                videoHeight: video?.videoHeight || null,
                stableSamples: consecutiveDetectionsRef.current,
                stableDurationMs,
            };

            presenceActiveRef.current = true;
            lastDetectionTimeRef.current = now;
            consecutiveLossesRef.current = 0;

            const currentSessionIdentity = buildSessionIdentity(
                sessionIdentityRef.current || {},
            );
            emit('user_detected', {
                ...currentSessionIdentity,
                presenceDetection: detectionDetails,
            });
            onFaceDetectedRef.current?.();
            console.info('[FaceDetection] Presence confirmed', detectionDetails);
        };

        const handleValidObservation = (observation, now) => {
            consecutiveLossesRef.current = 0;

            if (presenceActiveRef.current) {
                lastDetectionTimeRef.current = now;
                return;
            }

            const previousBox = candidateBoxRef.current;
            const isSameCandidate = !previousBox
                || getIntersectionOverUnion(previousBox, observation)
                    >= FACE_DETECTION_SETTINGS.minBoxIou;

            if (!isSameCandidate) {
                resetCandidate();
            }

            if (consecutiveDetectionsRef.current === 0) {
                candidateStartedAtRef.current = now;
            }

            candidateBoxRef.current = observation;
            consecutiveDetectionsRef.current += 1;

            const stableDurationMs = now - candidateStartedAtRef.current;
            if (
                consecutiveDetectionsRef.current
                    >= FACE_DETECTION_SETTINGS.minStableSamples
                && stableDurationMs
                    >= FACE_DETECTION_SETTINGS.minStableDurationMs
            ) {
                confirmPresence(observation, now);
            }
        };

        const handleMissingObservation = (now) => {
            if (!presenceActiveRef.current) {
                resetCandidate();
                return;
            }

            consecutiveLossesRef.current += 1;
            const lastDetectionTime = lastDetectionTimeRef.current;
            const timeSinceLastDetection = lastDetectionTime
                ? now - lastDetectionTime
                : Infinity;

            if (
                consecutiveLossesRef.current
                    >= FACE_DETECTION_SETTINGS.minConsecutiveLosses
                && timeSinceLastDetection
                    >= FACE_DETECTION_SETTINGS.lossTimeoutMs
            ) {
                emitUserLost('face_timeout', Math.round(timeSinceLastDetection));
            }
        };

        const detectFace = async () => {
            const video = videoRef.current;
            if (
                !active
                || document.hidden
                || inferenceTokenRef.current
                || !video
                || video.readyState !== 4
                || video.paused
                || video.ended
            ) {
                return;
            }

            const inferenceToken = {};
            inferenceTokenRef.current = inferenceToken;

            try {
                const predictions = await modelRef.current.estimateFaces(video, false);
                if (!active || inferenceTokenRef.current !== inferenceToken) {
                    return;
                }

                const now = Date.now();
                const observation = getFaceObservation(predictions?.[0]);
                const quality = validateFaceObservation(
                    observation,
                    video,
                    FACE_DETECTION_SETTINGS,
                );

                if (quality.valid) {
                    handleValidObservation(observation, now);
                } else {
                    handleMissingObservation(now);
                }
            } catch (error) {
                if (active) {
                    console.error('Detection error:', error);
                }
            } finally {
                if (inferenceTokenRef.current === inferenceToken) {
                    inferenceTokenRef.current = null;
                }
            }
        };

        const handleVisibilityChange = () => {
            resetCandidate();
            if (document.hidden) {
                emitUserLost('document_hidden');
            }
        };

        document.addEventListener('visibilitychange', handleVisibilityChange);
        detectionRef.current = setInterval(
            detectFace,
            FACE_DETECTION_SETTINGS.intervalMs,
        );
        detectFace();

        return () => {
            active = false;
            document.removeEventListener('visibilitychange', handleVisibilityChange);
            if (detectionRef.current) {
                clearInterval(detectionRef.current);
                detectionRef.current = null;
            }
            if (presenceActiveRef.current) {
                presenceActiveRef.current = false;
                onFaceLostRef.current?.();
            }
            consecutiveLossesRef.current = 0;
            lastDetectionTimeRef.current = null;
            resetCandidate();
        };
    }, [
        emit,
        isConnected,
        isModelLoaded,
        isRegistered,
        isStreamReady,
        sessionIdentity?.sessionId,
        stream,
    ]);

    return (
        <div style={{ position: 'absolute', opacity: 0, pointerEvents: 'none' }}>
            <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                width="640"
                height="480"
            />
        </div>
    );
};

export default FaceDetection;
