/**
 * RobotView
 *
 * Renders the robot image and overlays the eye canvas.
 * Listens for set_face events on the existing /message socket
 * via WebSocketContext - no separate socket connection needed.
 */

import PropTypes from 'prop-types';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useWebSocketContext } from '../contexts/WebSocketContext';
import { EYE_COORDINATE_ASPECT_RATIO } from '../eyes/drawFace';
import { useEyeRenderer } from '../eyes/useEyeRenderer';
import LedCircle from './LedCircle';

// Inner white display bounds measured from shara.png.
const SCREEN = { top: 0.180283, left: 0.270822, width: 0.423782, height: 0.186567 };

// Position of the LED ring relative to the robot image bounds.
// Adjust top/left to match the physical LED ring location on shara.png.
const LED_RING = { top: 0.65, left: 0.48, size: 0.236 };

const getContainedImageRect = (img) => {
    const box = img.getBoundingClientRect();
    const naturalWidth = img.naturalWidth || box.width;
    const naturalHeight = img.naturalHeight || box.height;

    if (!naturalWidth || !naturalHeight || !box.width || !box.height) {
        return box;
    }

    const imageAspect = naturalWidth / naturalHeight;
    const boxAspect = box.width / box.height;

    if (boxAspect > imageAspect) {
        const height = box.height;
        const width = height * imageAspect;

        return {
            top: box.top,
            left: box.left + (box.width - width) / 2,
            width,
            height,
        };
    }

    const width = box.width;
    const height = width / imageAspect;

    return {
        top: box.top + (box.height - height) / 2,
        left: box.left,
        width,
        height,
    };
};

const RobotView = ({ robotState }) => {
    const containerRef = useRef(null);
    const imgRef = useRef(null);
    const canvasRef = useRef(null);
    const overlayFrameRef = useRef(null);

    const { socket } = useWebSocketContext();
    const { setFace, refresh } = useEyeRenderer(canvasRef);

    const [operationalState, setOperationalState] = useState('idle');
    const [ledPos, setLedPos] = useState(null);

    const computeOverlay = useCallback(() => {
        const img = imgRef.current;
        const canvas = canvasRef.current;
        if (!img || !canvas) return;

        const { width: rw, height: rh, left: rl, top: rt } = getContainedImageRect(img);

        const screenTop = rt + rh * SCREEN.top;
        const screenLeft = rl + rw * SCREEN.left;
        const maxWidth = rw * SCREEN.width;
        const maxHeight = rh * SCREEN.height;

        let width = maxWidth;
        let height = width / EYE_COORDINATE_ASPECT_RATIO;

        if (height > maxHeight) {
            height = maxHeight;
            width = height * EYE_COORDINATE_ASPECT_RATIO;
        }

        const top = screenTop + (maxHeight - height) / 2;
        const left = screenLeft + (maxWidth - width) / 2;

        canvas.style.top = `${top}px`;
        canvas.style.left = `${left}px`;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;

        const dpr = window.devicePixelRatio || 1;
        const w = Math.max(1, Math.round(width * dpr));
        const h = Math.max(1, Math.round(height * dpr));
        if (canvas.width !== w || canvas.height !== h) {
            canvas.width = w;
            canvas.height = h;
        }
        refresh();

        setLedPos({
            top: rt + rh * LED_RING.top,
            left: rl + rw * LED_RING.left,
            size: Math.round(rw * LED_RING.size),
        });
    }, [refresh]);

    const scheduleOverlay = useCallback(() => {
        if (overlayFrameRef.current) {
            cancelAnimationFrame(overlayFrameRef.current);
        }

        overlayFrameRef.current = requestAnimationFrame(() => {
            overlayFrameRef.current = null;
            computeOverlay();
        });
    }, [computeOverlay]);

    useEffect(() => {
        const img = imgRef.current;
        if (!img) return;
        const container = containerRef.current;
        const viewport = window.visualViewport;

        scheduleOverlay();

        const ro = new ResizeObserver(scheduleOverlay);
        ro.observe(img);
        if (container) {
            ro.observe(container);
        }

        window.addEventListener('resize', scheduleOverlay);
        window.addEventListener('orientationchange', scheduleOverlay);
        viewport?.addEventListener('resize', scheduleOverlay);
        viewport?.addEventListener('scroll', scheduleOverlay);

        const settleTimer = setTimeout(scheduleOverlay, 250);

        return () => {
            ro.disconnect();
            clearTimeout(settleTimer);
            if (overlayFrameRef.current) {
                cancelAnimationFrame(overlayFrameRef.current);
            }
            window.removeEventListener('resize', scheduleOverlay);
            window.removeEventListener('orientationchange', scheduleOverlay);
            viewport?.removeEventListener('resize', scheduleOverlay);
            viewport?.removeEventListener('scroll', scheduleOverlay);
        };
    }, [scheduleOverlay]);

    useEffect(() => {
        if (!socket) return;
        const handler = ({ face }) => setFace(face);
        socket.on('set_face', handler);
        return () => socket.off('set_face', handler);
    }, [socket, setFace]);

    useEffect(() => {
        if (!socket) return;
        const handler = ({ state }) => setOperationalState(state);
        socket.on('state_update', handler);
        return () => socket.off('state_update', handler);
    }, [socket]);

    useEffect(() => {
        if (robotState) setFace(robotState);
    }, [robotState, setFace]);

    return (
        <div ref={containerRef} style={styles.container}>
            <div style={styles.background} />
            <img
                ref={imgRef}
                src="/images/shara.png"
                alt="SHARA Robot"
                style={styles.robotImage}
                onLoad={scheduleOverlay}
                onError={(e) => { e.target.style.display = 'none'; }}
            />
            <canvas ref={canvasRef} style={styles.canvas} />
            {ledPos && (
                <LedCircle
                    top={ledPos.top}
                    left={ledPos.left}
                    size={ledPos.size}
                    robotState={operationalState}
                />
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
        backgroundColor: '#91f2e5',
        zIndex: 0,
    },
    robotImage: {
        position: 'relative',
        height: '100vh',
        width: 'auto',
        maxWidth: '100%',
        maxHeight: '100vh',
        objectFit: 'contain',
        zIndex: 1,
    },
    canvas: {
        position: 'fixed',
        zIndex: 2,
        borderRadius: '6px',
        // Dimensions and position set imperatively in computeOverlay
        // to avoid React re-renders on every resize
    },
};

RobotView.propTypes = { robotState: PropTypes.string };
RobotView.defaultProps = { robotState: 'neutral' };

export default RobotView;
