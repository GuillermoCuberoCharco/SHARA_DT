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

const RobotView = ({ robotState }) => {
    const imgRef = useRef(null);
    const canvasRef = useRef(null);

    const { socket } = useWebSocketContext();
    const { setFace, refresh } = useEyeRenderer(canvasRef);

    const [operationalState, setOperationalState] = useState('idle');
    const [ledPos, setLedPos] = useState(null);
    const [isNarrowViewport, setIsNarrowViewport] = useState(
        typeof window !== 'undefined' ? window.innerWidth <= 960 : false
    );
    const styles = getStyles(isNarrowViewport);

    const computeOverlay = useCallback(() => {
        const img = imgRef.current;
        const canvas = canvasRef.current;
        if (!img || !canvas) return;

        const { width: rw, height: rh, left: rl, top: rt } = img.getBoundingClientRect();

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

    useEffect(() => {
        const handleResize = () => setIsNarrowViewport(window.innerWidth <= 960);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

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

const getStyles = (isNarrowViewport) => ({
    container: {
        position: 'fixed',
        top: 0,
        left: 0,
        width: isNarrowViewport ? '100vw' : '50vw',
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
        width: 'auto',
        height: isNarrowViewport ? '100vh' : '88vh',
        maxWidth: isNarrowViewport ? '100%' : '82%',
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
});

RobotView.propTypes = { robotState: PropTypes.string };
RobotView.defaultProps = { robotState: 'neutral' };

export default RobotView;
