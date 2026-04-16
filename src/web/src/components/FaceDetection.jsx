import * as blazeface from '@tensorflow-models/blazeface';
import * as tf from '@tensorflow/tfjs';
import { useEffect, useRef, useState } from 'react';
import { DETECTION_INTERVAL_MS } from '../../src/config';
import { useWebSocketContext } from '../contexts/WebSocketContext';
import { buildSessionIdentity } from '../utils/sessionIdentity';

const FaceDetection = ({ onFaceDetected, onFaceLost, stream, sessionIdentity }) => {
    const videoRef = useRef(null);
    const modelRef = useRef(null);
    const detectionRef = useRef(null);
    const [isModelLoaded, setIsModelLoaded] = useState(false);
    const [isStreamReady, setIsStreamReady] = useState(false);
    const [isFaceDetected, setIsFaceDetected] = useState(false);

    const consecutiveDetectionsRef = useRef(0);
    const consecutiveLossesRef = useRef(0);
    const lastDetectionTimeRef = useRef(null);

    const { emit } = useWebSocketContext();

    const loadBlazeFaceModels = async () => {
        try {
            console.log('Initializing TensorFlow...');
            await tf.ready();
            await tf.setBackend('webgl');
            console.log('TensorFlow initialized with backend:', tf.getBackend());

            console.log('Loading BlazeFace model...');
            modelRef.current = await blazeface.load({
                maxFaces: 1,
                inputWidth: 128,
                inputHeight: 128,
                iouThreshold: 0.3,
                scoreThreshold: 0.75
            });

            console.log('BlazeFace model loaded successfully');
            setIsModelLoaded(true);
        } catch (error) {
            console.error('Error loading BlazeFace model:', error);
        }
    };

    const isGoodQuality = (face, video) => {
        const startX = face.topLeft[0];
        const startY = face.topLeft[1];
        const width = face.bottomRight[0] - startX;
        const height = face.bottomRight[1] - startY;

        if (width < 30 || height < 30) {
            console.log(`Face too small: ${width}x${height} (minimum 120x120)`);
            return false;
        }

        if (startX < 0 || startY < 0 || startX + width > video.videoWidth || startY + height > video.videoHeight) {
            return false;
        }

        const aspectRatio = width / height;
        return aspectRatio >= 0.6 && aspectRatio <= 1.6;
    };

    useEffect(() => {
        loadBlazeFaceModels();

        return () => {
            if (detectionRef.current) {
                clearInterval(detectionRef.current);
            }
        };
    }, []);

    useEffect(() => {
        if (!stream || !videoRef.current) {
            return;
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
            video.srcObject = null;
        };
    }, [stream]);

    useEffect(() => {
        if (!isModelLoaded || !isStreamReady || !videoRef.current) {
            return;
        }

        const detectFace = async () => {
            if (!videoRef.current || videoRef.current.readyState !== 4) {
                return;
            }

            try {
                const video = videoRef.current;
                if (video.paused || video.ended) {
                    return;
                }

                const predictions = await modelRef.current.estimateFaces(video, false);
                const now = Date.now();

                if (predictions && predictions.length > 0 && isGoodQuality(predictions[0], video)) {
                    consecutiveDetectionsRef.current++;
                    consecutiveLossesRef.current = 0;
                    lastDetectionTimeRef.current = now;

                    if (!isFaceDetected && consecutiveDetectionsRef.current >= 2) {
                        const currentSessionIdentity = buildSessionIdentity(sessionIdentity || {});
                        setIsFaceDetected(true);
                        emit('user_detected', currentSessionIdentity);
                        onFaceDetected();
                    }
                } else {
                    consecutiveDetectionsRef.current = 0;
                    consecutiveLossesRef.current++;
                    const timeSinceLastDetection = lastDetectionTimeRef.current ? now - lastDetectionTimeRef.current : Infinity;

                    if (isFaceDetected && consecutiveLossesRef.current >= 3 && timeSinceLastDetection > 10000) {
                        console.log('Face confirmed lost after', consecutiveLossesRef.current, 'losses and', timeSinceLastDetection, 'ms');
                        setIsFaceDetected(false);
                        onFaceLost();
                        emit('user_lost', {
                            sessionId: sessionIdentity?.sessionId,
                        });
                    }
                }
            } catch (error) {
                console.error('Detection error:', error);
                if (error.message.includes('backend') || error.message.includes('tensor')) {
                    clearInterval(detectionRef.current);
                }
            }
        };

        // Sample fast enough that 3/6 confirmation can complete in roughly
        // one or two short batches instead of several seconds of waiting.
        detectionRef.current = setInterval(detectFace, DETECTION_INTERVAL_MS);

        return () => {
            if (detectionRef.current) {
                clearInterval(detectionRef.current);
            }
        };
    }, [isModelLoaded, stream, onFaceDetected, onFaceLost, isStreamReady, isFaceDetected, emit, sessionIdentity]);

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
