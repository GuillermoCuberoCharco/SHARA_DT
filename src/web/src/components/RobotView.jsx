/**
 * RobotView
 *
 * Renders the physical robot image fitting the full viewport height.
 * Connects independently to the /animation namespace to receive eye_frame events
 * emitted by the Python Eyes service.
 *
 * Screen area coordinates (as % of original image dimensions):
 *   top: 19%  left: 30%  width: 40%  height: 17%
 */

import PropTypes from 'prop-types';
import { useCallback, useEffect, useRef, useState } from 'react';
import io from 'socket.io-client';
import { SERVER_URL } from '../config';

const SCREEN = { top: 0.20, left: 0.275, width: 0.40, height: 0.17 };

const RobotView = ({ robotState }) => {
    const [eyeFrame, setEyeFrame] = useState(null);
    const [overlayRect, setOverlayRect] = useState(null);
    const imgRef = useRef(null);
    const socketRef = useRef(null);

    // Own socket connection to /animation namespace
    useEffect(() => {
        console.log('[AnimationSocket] Connecting to', SERVER_URL + '/animation');

        const socket = io(`${SERVER_URL}/animation`, {
            transports: ['websocket', 'polling'],
            reconnectionAttempts: 10,
            reconnectionDelay: 1000,
            timeout: 20000,
        });
        socketRef.current = socket;

        socket.on('connect', () => {
            console.log('[AnimationSocket] Connected:', socket.id);
            socket.emit('register_animation', { client: 'web' });
        });

        socket.on('eye_frame', (data) => {
            if (data?.frame) {
                setEyeFrame(`data:image/png;base64,${data.frame}`);
            }
        });

        socket.on('connect_error', (err) => {
            console.error('[AnimationSocket] Connection error:', err.message);
        });

        socket.on('disconnect', (reason) => {
            console.log('[AnimationSocket] Disconnected:', reason);
        });

        return () => {
            socket.removeAllListeners();
            socket.disconnect();
        };
    }, []);

    // Compute overlay position from rendered image
    const computeOverlay = useCallback(() => {
        const img = imgRef.current;
        if (!img) return;
        const { width: rw, height: rh, left: rl, top: rt } = img.getBoundingClientRect();
        setOverlayRect({
            top: rt + rh * SCREEN.top,
            left: rl + rw * SCREEN.left,
            width: rw * SCREEN.width,
            height: rh * SCREEN.height,
        });
    }, []);

    useEffect(() => {
        const img = imgRef.current;
        if (!img) return;
        computeOverlay();
        const ro = new ResizeObserver(computeOverlay);
        ro.observe(img);
        window.addEventListener('resize', computeOverlay);
        return () => {
            ro.disconnect();
            window.removeEventListener('resize', computeOverlay);
        };
    }, [computeOverlay]);

    return (
        <div style={styles.container}>
            <div style={styles.background} />

            <img
                ref={imgRef}
                src="/images/shara.png"
                alt="SHARA Robot"
                style={styles.robotImage}
                onLoad={computeOverlay}
                onError={(e) => { e.target.style.display = 'none'; }}
            />

            {overlayRect && (
                <div style={{
                    position: 'fixed',
                    top: overlayRect.top,
                    left: overlayRect.left,
                    width: overlayRect.width,
                    height: overlayRect.height,
                    zIndex: 2,
                    overflow: 'hidden',
                    borderRadius: '6px',
                    // outline: '2px dashed rgba(255,0,0,0.5)', // debug
                }}>
                    {eyeFrame ? (
                        <img
                            src={eyeFrame}
                            alt={`Robot eye state: ${robotState}`}
                            style={{ width: '100%', height: '100%', objectFit: 'fill' }}
                        />
                    ) : (
                        <div style={{ width: '100%', height: '100%' }} />
                    )}
                </div>
            )}
        </div>
    );
};

const styles = {
    container: {
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 0,
        overflow: 'hidden',
    },
    background: {
        position: 'absolute',
        inset: 0,
        backgroundColor: '#cce7ef',
        zIndex: 0,
    },
    robotImage: {
        position: 'relative',
        height: '100vh',
        width: 'auto',
        objectFit: 'contain',
        zIndex: 1,
    },
};

RobotView.propTypes = {
    robotState: PropTypes.string,
};

RobotView.defaultProps = {
    robotState: 'neutral',
};

export default RobotView;