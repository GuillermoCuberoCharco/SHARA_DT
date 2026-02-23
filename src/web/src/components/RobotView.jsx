/**
 * RobotView
 * 
 * Renders the physical robot image as a full-screen background.
 * A centered overlay zone receives eye animation frames (PNG base64)
 * streamed in real-time from the server via WebSocket event `eye_frame`.
 * 
 * Expected socket event payload:
 *   { frame: <base64 PNG string> }
 */

import PropTypes from 'prop-types';
import { useEffect, useRef, useState } from 'react';
import { useWebSocketContext } from '../contexts/WebSocketContext';

const RobotView = ({ robotState }) => {
    const { socket } = useWebSocketContext();
    const [eyeFrame, setEyeFrame] = useState(null);
    const imgRef = useRef(null);

    useEffect(() => {
        if (!socket) return;

        const handleEyeFrame = (data) => {
            if (data?.frame) {
                setEyeFrame(`data:image/png;base64,${data.frame}`);
            }
        };

        socket.on('eye_frame', handleEyeFrame);

        return () => {
            socket.off('eye_frame', handleEyeFrame);
        };
    }, [socket]);

    return (
        <div style={styles.container}>
            {/* Robot background image */}
            <img
                src="/images/shara.png"
                alt="SHARA Robot"
                style={styles.robotImage}
                onError={(e) => {
                    e.target.style.display = 'none';
                }}
            />

            {/* Fallback background when image is missing */}
            <div style={styles.fallbackBackground} />

            {/* Eye animation overlay - centered on the image */}
            <div style={styles.eyeOverlay}>
                {eyeFrame ? (
                    <img
                        ref={imgRef}
                        src={eyeFrame}
                        alt={`Robot eye state: ${robotState}`}
                        style={styles.eyeImage}
                    />
                ) : (
                    /* Placeholder shown until first eye frame arrives */
                    <div style={styles.eyePlaceholder}>
                        <span style={styles.eyePlaceholderText}>👀</span>
                    </div>
                )}
            </div>
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
        overflow: 'hidden',
        zIndex: 0,
    },
    robotImage: {
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        objectFit: 'cover',
        zIndex: 1,
    },
    fallbackBackground: {
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        backgroundColor: '#1a1a2e',
        zIndex: 0,
    },
    eyeOverlay: {
        position: 'absolute',
        // Centered in the image - adjust these values as needed to align with the robot's eyes
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: '300px',
        height: '150px',
        zIndex: 2,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        // Uncomment border below to visualize the overlay zone during development
        border: '2px dashed rgba(255, 255, 255, 0.5)',
        borderRadius: '8px',
    },
    eyeImage: {
        width: '100%',
        height: '100%',
        objectFit: 'contain',
    },
    eyePlaceholder: {
        width: '100%',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(255, 255, 255, 0.05)',
        borderRadius: '8px',
    },
    eyePlaceholderText: {
        fontSize: '48px',
        opacity: 0.4,
    },
};

RobotView.propTypes = {
    robotState: PropTypes.string,
};

RobotView.defaultProps = {
    robotState: 'neutral',
};

export default RobotView;