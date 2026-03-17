import * as blazeface from '@tensorflow-models/blazeface';
import * as tf from '@tensorflow/tfjs';
import axios from 'axios';
import { useEffect, useRef, useState } from 'react';
import { DETECTION_INTERVAL_MS, RECOGNITION_REQUEST_TIMEOUT_MS, SERVER_URL } from '../../src/config';
import { useWebSocketContext } from '../contexts/WebSocketContext';

const FACE_BATCH_SIZE = 3;
const UNKNOWN_RECOGNITION_THRESHOLD = 6;
const FACE_CROP_SIZE = 224;
const FACE_CROP_JPEG_QUALITY = 0.85;

const FaceDetection = ({ onFaceDetected, onFaceLost, stream, isRecognitionEnabled = true }) => {
    const videoRef = useRef(null);
    const modelRef = useRef(null);
    const detectionRef = useRef(null);
    const [isModelLoaded, setIsModelLoaded] = useState(false);
    const [isStreamReady, setIsStreamReady] = useState(false);
    const [isFaceDetected, setIsFaceDetected] = useState(false);

    const batchCollectionRef = useRef({
        frames: [],
        isCollecting: false,
        isCapturingFrame: false,
        sessionId: null
    });
    const canvasRef = useRef(document.createElement('canvas'));
    const lastRecognizedUserNameRef = useRef(null);
    const clientIdRef = useRef(`client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`);
    const recognitionSessionIdRef = useRef(null);

    const [detectionStatus, setDetectionStatus] = useState('idle');
    const [detectionProgress, setDetectionProgress] = useState({ current: 0, total: FACE_BATCH_SIZE });
    const [consensusInfo, setConsensusInfo] = useState(null);

    const consecutiveDetectionsRef = useRef(0);
    const consecutiveLossesRef = useRef(0);
    const lastDetectionTimeRef = useRef(null);

    const { emit } = useWebSocketContext();

    const getRecognitionSessionId = () => {
        if (!recognitionSessionIdRef.current) {
            recognitionSessionIdRef.current = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        }
        return recognitionSessionIdRef.current;
    };

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

    const startBatchCollection = (predictions) => {
        const batch = batchCollectionRef.current;
        if (batch.isCollecting) {
            return;
        }

        console.log('Starting batch collection for face recognition');
        batch.isCollecting = true;
        batch.isCapturingFrame = false;
        batch.frames = [];
        batch.sessionId = getRecognitionSessionId();

        setDetectionStatus('collecting');
        setDetectionProgress({ current: 0, total: FACE_BATCH_SIZE });

        addFrameToBatch(predictions[0]);
    };

    const addFrameToBatch = async (face) => {
        const batch = batchCollectionRef.current;
        if (!batch.isCollecting || batch.isCapturingFrame || batch.frames.length >= FACE_BATCH_SIZE) {
            return;
        }

        try {
            batch.isCapturingFrame = true;
            const video = videoRef.current;
            const canvas = canvasRef.current;
            const ctx = canvas.getContext('2d');

            const startX = face.topLeft[0];
            const startY = face.topLeft[1];
            const width = face.bottomRight[0] - startX;
            const height = face.bottomRight[1] - startY;

            const padding = Math.min(width, height) * 0.4;
            const cropStartX = Math.max(0, startX - padding);
            const cropStartY = Math.max(0, startY - padding);
            const cropWidth = Math.min(width + (padding * 2), video.videoWidth - cropStartX);
            const cropHeight = Math.min(height + (padding * 2), video.videoHeight - cropStartY);
            const scaleX = FACE_CROP_SIZE / cropWidth;
            const scaleY = FACE_CROP_SIZE / cropHeight;
            const faceBox = [
                Math.max(0, Math.min(FACE_CROP_SIZE - 1, Math.round((startY - cropStartY) * scaleY))),
                Math.max(0, Math.min(FACE_CROP_SIZE - 1, Math.round((startX + width - cropStartX) * scaleX))),
                Math.max(0, Math.min(FACE_CROP_SIZE - 1, Math.round((startY + height - cropStartY) * scaleY))),
                Math.max(0, Math.min(FACE_CROP_SIZE - 1, Math.round((startX - cropStartX) * scaleX)))
            ];

            if (faceBox[2] <= faceBox[0] || faceBox[1] <= faceBox[3]) {
                return;
            }

            canvas.width = FACE_CROP_SIZE;
            canvas.height = FACE_CROP_SIZE;
            ctx.fillStyle = '#FFFFFF';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(video, cropStartX, cropStartY, cropWidth, cropHeight, 0, 0, canvas.width, canvas.height);

            const blob = await new Promise((resolve) => {
                canvas.toBlob(resolve, 'image/jpeg', FACE_CROP_JPEG_QUALITY);
            });

            if (!blob || !batch.isCollecting || batch.frames.length >= FACE_BATCH_SIZE) {
                return;
            }

            const arrayBuffer = await blob.arrayBuffer();
            batch.frames.push({
                buffer: new Uint8Array(arrayBuffer),
                faceBox
            });

            const currentCount = batch.frames.length;
            console.log(`Frame added to batch: ${currentCount}/${FACE_BATCH_SIZE}`);
            setDetectionProgress({ current: currentCount, total: FACE_BATCH_SIZE });

            if (currentCount >= FACE_BATCH_SIZE) {
                await processBatch();
            }
        } catch (error) {
            console.error('Error adding frame to batch:', error);
        } finally {
            batch.isCapturingFrame = false;
        }
    };

    const processBatch = async () => {
        const batch = batchCollectionRef.current;
        if (!batch.isCollecting || batch.frames.length < FACE_BATCH_SIZE) {
            return;
        }
        if (!isRecognitionEnabled) {
            console.log('Skipping face recognition batch while waiting for server response or TTS playback');
            resetBatchCollection();
            setDetectionStatus('idle');
            return;
        }

        try {
            console.log(`Processing batch of ${FACE_BATCH_SIZE} frames...`);
            setDetectionStatus('processing');

            const formData = new FormData();
            const faceBoxes = [];

            batch.frames.forEach((frameEntry, index) => {
                const blob = new Blob([frameEntry.buffer], { type: 'image/jpeg' });
                formData.append('faces', blob, `face_${index}.jpg`);
                faceBoxes.push(frameEntry.faceBox);
            });

            formData.append('clientId', clientIdRef.current);
            formData.append('sessionId', batch.sessionId);
            formData.append('faceBoxes', JSON.stringify(faceBoxes));

            const response = await axios.post(`${SERVER_URL}/api/recognize-face`, formData, {
                headers: {
                    'X-Client-Id': clientIdRef.current
                },
                timeout: RECOGNITION_REQUEST_TIMEOUT_MS
            });

            if (response.data) {
                handleBatchRecognitionResponse(response.data);
            }
        } catch (error) {
            const backendError = error.response?.data?.error;
            const isTimeout = error.code === 'ECONNABORTED';
            const errorMessage = isTimeout
                ? `Recognition request timed out after ${RECOGNITION_REQUEST_TIMEOUT_MS} ms`
                : (backendError || error.message);
            console.error('Error processing batch:', errorMessage, error);
            resetBatchCollection();
            setDetectionStatus('idle');
        }
    };

    const handleBatchRecognitionResponse = (data) => {
        console.log('Batch recognition response:', data);

        if (data.isUncertain) {
            setDetectionStatus('uncertain');
            setConsensusInfo({
                message: `No clear consensus reached (${(data.consensusRatio * 100).toFixed(1)}% agreement)`,
                ratio: data.consensusRatio
            });
        } else if (data.pendingRecognition) {
            setDetectionStatus('idle');
            setDetectionProgress({
                current: data.historyCount || data.detectionProgress || 0,
                total: data.totalRequired || UNKNOWN_RECOGNITION_THRESHOLD
            });
            setConsensusInfo({
                message: `Recognition progress: ${data.historyCount || data.detectionProgress || 0}/${data.totalRequired || UNKNOWN_RECOGNITION_THRESHOLD}`,
                ratio: null
            });
        } else if (data.isConfirmed) {
            setDetectionStatus('confirmed');
            setConsensusInfo(null);

            const recognizedUserName = data.userName || 'unknown';
            const previousUserName = lastRecognizedUserNameRef.current;
            lastRecognizedUserNameRef.current = recognizedUserName;

            const userData = {
                sessionId: data.sessionId,
                userName: recognizedUserName,
                isNewUser: data.isNewUser,
                needsIdentification: data.needsIdentification,
                userStatus: data.userStatus || 'confirmed'
            };

            if (previousUserName !== recognizedUserName || data.needsIdentification) {
                console.log('New user recognized:', userData);
                emit('user_detected', {
                    sessionId: data.sessionId,
                    userName: recognizedUserName,
                    isNewUser: data.isNewUser,
                    needsIdentification: data.needsIdentification,
                    userStatus: data.userStatus || 'confirmed',
                    consensusRatio: data.consensusRatio
                });
            }

            console.log(
                data.isNewUser
                    ? `New user confirmed: ${recognizedUserName}`
                    : data.needsIdentification
                        ? `User needs identification: ${recognizedUserName}`
                        : `User confirmed: ${recognizedUserName}`
            );
        }

        resetBatchCollection();
    };

    const resetBatchCollection = () => {
        const batch = batchCollectionRef.current;
        batch.isCollecting = false;
        batch.isCapturingFrame = false;
        batch.frames = [];
        batch.sessionId = null;
    };

    const resetDetectionState = () => {
        setDetectionStatus('idle');
        setDetectionProgress({ current: 0, total: FACE_BATCH_SIZE });
        setConsensusInfo(null);
        recognitionSessionIdRef.current = null;
        lastRecognizedUserNameRef.current = null;
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
        if (isRecognitionEnabled) {
            return;
        }

        const batch = batchCollectionRef.current;
        if (batch.isCollecting || detectionStatus === 'processing') {
            console.log('Pausing face recognition while recording or waiting for response');
            resetBatchCollection();
            setDetectionStatus('idle');
        }
    }, [isRecognitionEnabled, detectionStatus]);

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
                        setIsFaceDetected(true);
                        onFaceDetected();
                    }

                    if (isFaceDetected && isRecognitionEnabled) {
                        const batch = batchCollectionRef.current;
                        if (!batch.isCollecting && detectionStatus === 'idle') {
                            startBatchCollection(predictions);
                        } else if (batch.isCollecting && !batch.isCapturingFrame && batch.frames.length < FACE_BATCH_SIZE) {
                            addFrameToBatch(predictions[0]);
                        }
                    }
                } else {
                    consecutiveDetectionsRef.current = 0;
                    consecutiveLossesRef.current++;
                    const timeSinceLastDetection = lastDetectionTimeRef.current ? now - lastDetectionTimeRef.current : Infinity;

                    if (isFaceDetected && consecutiveLossesRef.current >= 3 && timeSinceLastDetection > 10000) {
                        console.log('Face confirmed lost after', consecutiveLossesRef.current, 'losses and', timeSinceLastDetection, 'ms');
                        const lostSessionId = recognitionSessionIdRef.current;
                        setIsFaceDetected(false);
                        resetDetectionState();
                        onFaceLost();

                        setTimeout(() => {
                            if (!isFaceDetected) {
                                if (lostSessionId) {
                                    emit('user_lost', { sessionId: lostSessionId });
                                }
                                resetDetectionState();
                            }
                        }, 3000);
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
    }, [isModelLoaded, stream, onFaceDetected, onFaceLost, isStreamReady, isFaceDetected, emit, detectionStatus, isRecognitionEnabled]);

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
