/**
 * RobotView
 *
 * Renders the physical robot image fitting the full viewport height.
 * The eye animation overlay is positioned dynamically over the robot's
 * white screen area using a ResizeObserver on the rendered image.
 *
 * Screen area coordinates (as % of original image dimensions):
 *   top:    22%   left:  25%
 *   height: 27%   width: 49%
 */

import PropTypes from 'prop-types';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useWebSocketContext } from '../contexts/WebSocketContext';

// Position of the robot's white screen relative to the full image
const SCREEN = { top: 0.19, left: 0.15, width: 0.70, height: 0.30 };

const RobotView = ({ robotState }) => {
    const { socket } = useWebSocketContext();
    const [eyeFrame, setEyeFrame] = useState(null);
    const [overlayRect, setOverlayRect] = useState(null);
    const imgRef = useRef(null);

    // Receive eye frames from the server via /message socket
    useEffect(() => {
        if (!socket) return;
        const handle = (data) => {
            if (data?.frame) setEyeFrame(`data:image/png;base64,${data.frame}`);
        };
        socket.on('eye_frame', handle);
        return () => socket.off('eye_frame', handle);
    }, [socket]);

    // Compute overlay position from the rendered image dimensions
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

    // Recompute whenever the image resizes
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
                <div
                    style={{
                        position: 'fixed',
                        top: overlayRect.top,
                        left: overlayRect.left,
                        width: overlayRect.width,
                        height: overlayRect.height,
                        zIndex: 2,
                        overflow: 'hidden',
                        borderRadius: '6px',
                        // Descomment for debugging overlay position:
                        outline: '2px dashed rgba(255,0,0,0.5)',
                    }}
                >
                    {eyeFrame ? (
                        <img
                            src={eyeFrame}
                            alt={`Robot eye state: ${robotState}`}
                            style={{ width: '100%', height: '100%', objectFit: 'fill' }}
                        />
                    ) : (
                        <div style={styles.eyePlaceholder} />
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
        backgroundColor: '#000',
        zIndex: 0,
    },
    robotImage: {
        position: 'relative',
        height: '100vh',
        width: 'auto',
        objectFit: 'contain',
        zIndex: 1,
    },
    eyePlaceholder: {
        width: '100%',
        height: '100%',
        backgroundColor: 'rgba(255,255,255,0.0)',
    },
};

RobotView.propTypes = {
    robotState: PropTypes.string,
};

RobotView.defaultProps = {
    robotState: 'neutral',
};

export default RobotView;