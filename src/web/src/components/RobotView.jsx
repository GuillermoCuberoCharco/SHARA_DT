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
import { useEyeRenderer } from '../eyes/useEyeRenderer';

const SCREEN = { top: 0.18, left: 0.275, width: 0.40, height: 0.17 };

const RobotView = ({ robotState }) => {
    const [overlayRect, setOverlayRect] = useState(null);
    const imgRef = useRef(null);
    const canvasRef = useRef(null);

    // Eye renderer hook — owns the rAF loop and face transitions
    const { setFace } = useEyeRenderer(canvasRef);

    // ── Canvas resolution ────────────────────────────────────────────────────
    // Keep canvas pixel dimensions in sync with its CSS display size

    const syncCanvasSize = useCallback(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const { width, height } = canvas.getBoundingClientRect();
        if (canvas.width !== Math.round(width) || canvas.height !== Math.round(height)) {
            canvas.width = Math.round(width);
            canvas.height = Math.round(height);
        }
    }, []);

    // ── Overlay position (follows rendered image size) ────────────────────────

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
        syncCanvasSize();
    }, [syncCanvasSize]);

    useEffect(() => {
        const img = imgRef.current;
        if (!img) return;
        computeOverlay();
        const ro = new ResizeObserver(computeOverlay);
        ro.observe(img);
        window.addEventListener('resize', computeOverlay);
        return () => { ro.disconnect(); window.removeEventListener('resize', computeOverlay); };
    }, [computeOverlay]);

    // ── Socket: /animation — receives only { face: name } ────────────────────

    useEffect(() => {
        const socket = io(`${SERVER_URL}/animation`, {
            transports: ['websocket', 'polling'],
            reconnectionAttempts: 10,
            reconnectionDelay: 1000,
            timeout: 20000,
        });

        socket.on('connect', () => {
            console.log('[AnimationSocket] Connected:', socket.id);
            socket.emit('register_animation', { client: 'web' });
            // Request current face on reconnect
            socket.emit('get_current_face');
        });

        socket.on('set_face', ({ face }) => {
            console.log('[AnimationSocket] set_face:', face);
            setFace(face);
        });

        socket.on('connect_error', (err) =>
            console.error('[AnimationSocket] Error:', err.message)
        );

        return () => { socket.removeAllListeners(); socket.disconnect(); };
    }, [setFace]);

    // ── Also sync face when robotState prop changes (from UI/state machine) ──
    useEffect(() => {
        if (robotState) setFace(robotState);
    }, [robotState, setFace]);

    // ── Render ───────────────────────────────────────────────────────────────

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
                <canvas
                    ref={canvasRef}
                    style={{
                        position: 'fixed',
                        top: overlayRect.top,
                        left: overlayRect.left,
                        width: overlayRect.width,
                        height: overlayRect.height,
                        zIndex: 2,
                        borderRadius: '6px',
                        // outline: '2px dashed red', // debug
                    }}
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
        backgroundColor: '#84dcff',
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

RobotView.propTypes = { robotState: PropTypes.string };
RobotView.defaultProps = { robotState: 'neutral' };

export default RobotView;