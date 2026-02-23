/**
 * WebSocketVideoComponent — updated for Flask-SocketIO namespace /video.
 *
 * Migration note:
 *   Before: io(SERVER_URL, { path: '/video-socket' })
 *   After:  io(SERVER_URL + '/video')
 */

import { useEffect, useRef, useState } from 'react';
import { io } from 'socket.io-client';
import { SERVER_URL } from '../config';

const WebSocketVideoComponent = ({ onStreamReady, onStreamError }) => {
    const videoRef = useRef(null);
    const canvasRef = useRef(null);
    const socketRef = useRef(null);
    const frameRequestRef = useRef(null);
    const stoppingRef = useRef(false);
    const lastFrameTimeRef = useRef(0);

    const [connectionStatus, setConnectionStatus] = useState('Connecting...');
    const [framesSent, setFramesSent] = useState(0);

    const TARGET_FPS = 15;
    const frameInterval = 1000 / TARGET_FPS;

    useEffect(() => {
        stoppingRef.current = false;
        initialize();

        return () => {
            stoppingRef.current = true;
            if (frameRequestRef.current) cancelAnimationFrame(frameRequestRef.current);
            if (socketRef.current) socketRef.current.disconnect();
        };
    }, []);

    const initialize = async () => {
        try {
            await setupSocketConnection();
            await setupVideoStream();
        } catch (error) {
            console.error('[VideoSocket] Initialization error:', error.message);
            onStreamError?.(error);
        }
    };

    const setupSocketConnection = () => {
        return new Promise((resolve, reject) => {
            console.log(`[VideoSocket] Connecting to ${SERVER_URL}/video`);

            socketRef.current = io(`${SERVER_URL}/video`, {
                transports: ['websocket', 'polling'],
                reconnectionAttempts: 5,
                reconnectionDelay: 1000,
                timeout: 10000,
            });

            const timeout = setTimeout(() => {
                reject(new Error('Socket.IO connection timeout'));
            }, 10000);

            socketRef.current.on('connect', () => {
                clearTimeout(timeout);
                console.log('[VideoSocket] Connected');
                socketRef.current.emit('register', { client: 'web' });
                setConnectionStatus('Connected');
                resolve();
            });

            socketRef.current.on('connect_error', (error) => {
                clearTimeout(timeout);
                setConnectionStatus('Error: ' + error.message);
                reject(error);
            });

            socketRef.current.on('disconnect', () => {
                setConnectionStatus('Disconnected');
            });
        });
    };

    const setupVideoStream = async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { width: 640, height: 480 },
                audio: false,
            });

            const video = videoRef.current;
            if (video) {
                video.srcObject = stream;
                video.onloadedmetadata = () => {
                    video.play();
                    onStreamReady?.(stream);
                    startSendingFrames(video, stream);
                };
            }
        } catch (error) {
            console.error('[VideoSocket] Camera error:', error.message);
            onStreamReady?.(null);
        }
    };

    const startSendingFrames = (video, stream) => {
        const canvas = canvasRef.current;
        const context = canvas.getContext('2d');

        const sendFrame = () => {
            if (stoppingRef.current) return;

            const now = Date.now();
            if (
                video.readyState === video.HAVE_ENOUGH_DATA &&
                now - lastFrameTimeRef.current >= frameInterval
            ) {
                canvas.width = video.videoWidth / 2;
                canvas.height = video.videoHeight / 2;
                context.drawImage(video, 0, 0, canvas.width, canvas.height);
                const frame = canvas.toDataURL('image/jpeg', 0.5);

                if (socketRef.current?.connected) {
                    socketRef.current.emit('video_frame', { type: 'video-frame', frame });
                    setFramesSent(prev => prev + 1);
                }
                lastFrameTimeRef.current = now;
            }

            frameRequestRef.current = requestAnimationFrame(sendFrame);
        };

        if (video.readyState >= 3) {
            sendFrame();
        } else {
            video.onloadedmetadata = () => sendFrame();
        }
    };

    return (
        <div style={{ position: 'absolute', opacity: 0.1, pointerEvents: 'none' }}>
            <video ref={videoRef} autoPlay playsInline muted width="320" height="240" />
            <canvas ref={canvasRef} width="320" height="240" />
        </div>
    );
};

export default WebSocketVideoComponent;