/**
 * RobotView
 *
 * The <canvas> is always in the DOM (never conditional) so useEyeRenderer
 * can start its rAF loop immediately. Position and pixel dimensions are
 * updated via useEffect whenever overlayRect changes.
 *
 * SCREEN constants match the physical robot screen area on the photo:
 *   top: 18%  left: 27.5%  width: 40%  height: 17%
 */

import PropTypes from 'prop-types';
import { useCallback, useEffect, useRef } from 'react';
import io from 'socket.io-client';
import { SERVER_URL } from '../config';
import { useEyeRenderer } from '../eyes/useEyeRenderer';

const SCREEN = { top: 0.175, left: 0.275, width: 0.40, height: 0.17 };

const RobotView = ({ robotState }) => {
    const imgRef = useRef(null);
    const canvasRef = useRef(null);

    const { setFace } = useEyeRenderer(canvasRef);

    // ── Sync canvas position + pixel dimensions ───────────────────────────────

    const computeOverlay = useCallback(() => {
        const img = imgRef.current;
        const canvas = canvasRef.current;
        if (!img || !canvas) return;

        const { width: rw, height: rh, left: rl, top: rt } = img.getBoundingClientRect();

        const top = rt + rh * SCREEN.top;
        const left = rl + rw * SCREEN.left;
        const width = rw * SCREEN.width;
        const height = rh * SCREEN.height;

        // CSS position (viewport-relative via position:fixed)
        canvas.style.top = `${top}px`;
        canvas.style.left = `${left}px`;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;

        // Pixel resolution — must match CSS size to avoid scaling artefacts
        const w = Math.round(width);
        const h = Math.round(height);
        if (canvas.width !== w || canvas.height !== h) {
            canvas.width = w;
            canvas.height = h;
        }
    }, []);

    useEffect(() => {
        const img = imgRef.current;
        if (!img) return;
        computeOverlay();
        const ro = new ResizeObserver(computeOverlay);
        ro.observe(img);
        window.addEventListener('resize', computeOverlay);
        return () => { ro.disconnect(); window.removeEventListener('resize', computeOverlay); };
    }, [computeOverlay]);

    // ── Socket /animation ─────────────────────────────────────────────────────

    useEffect(() => {
        const socket = io(`${SERVER_URL}/animation`, {
            transports: ['websocket', 'polling'],
            reconnectionAttempts: 10,
            reconnectionDelay: 1000,
            timeout: 20000,
        });

        socket.on('connect', () => {
            socket.emit('register_animation', { client: 'web' });
            socket.emit('get_current_face');
        });

        socket.on('set_face', ({ face }) => setFace(face));
        socket.on('connect_error', (err) =>
            console.error('[AnimationSocket]', err.message)
        );

        return () => { socket.removeAllListeners(); socket.disconnect(); };
    }, [setFace]);

    // ── robotState prop (from UI state machine) ───────────────────────────────

    useEffect(() => {
        if (robotState) setFace(robotState);
    }, [robotState, setFace]);

    // ── Render ────────────────────────────────────────────────────────────────

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
            {/* Canvas is always mounted — never conditional */}
            <canvas
                ref={canvasRef}
                style={styles.canvas}
            />
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