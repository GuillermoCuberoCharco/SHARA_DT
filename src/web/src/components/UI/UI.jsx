/**
 * UI
 * 
 * Overlay component that handles:
 * - Audio recording and synthesis
 * - Face detection (wakeface)
 * - LED color legend
 * 
 * When a robot message arrives with an emotional state,
 * onRobotStateChange is called so RobotView can update the eye animation.
 * 
 * Props:
 *   sharedStream       - MediaStream from the user's camera (may be null)
 *   onRobotStateChange - Callback(stateName: string) notifying the current robot emotional state
 */

import PropTypes from 'prop-types';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ANIMATION_MAPPINGS } from "../../config";
import { useWebSocketContext } from '../../contexts/WebSocketContext';
import '../../styles/InterfaceStyle.css';
import FaceDetection from '../FaceDetection';
import useAudioRecorder from './hooks/useAudioRecorder';

const LED_LEGEND_ITEMS = [
    {
        id: 'presence',
        chipClass: 'led-legend-chip-presence',
        title: 'Morado fijo',
        description: 'Presencia detectada. Shara esta atenta.',
    },
    {
        id: 'listening',
        chipClass: 'led-legend-chip-listening',
        title: 'Azul girando',
        description: 'Shara esta escuchando.',
    },
    {
        id: 'recording',
        chipClass: 'led-legend-chip-recording',
        title: 'Blanco girando',
        description: 'Audio en grabacion.',
    },
    {
        id: 'speaking',
        chipClass: 'led-legend-chip-speaking',
        title: 'Azul respirando',
        description: 'Shara esta hablando.',
    },
    {
        id: 'off',
        chipClass: 'led-legend-chip-off',
        title: 'Apagado tenue',
        description: 'Sin interaccion activa o procesando.',
    },
];

const UI_STATUS_MESSAGES = {
    connection_error: 'Connection error',
    connecting: 'Connecting to server',
    recording: 'Recording audio',
    waiting_response: 'Waiting for response',
    speaking: 'Playing robot audio',
    face_not_detected: 'Face not detected',
    ready: 'Ready',
};

const getUiConsoleStatus = ({
    connectionError,
    isRegistered,
    isRecording,
    isWaitingResponse,
    isSpeaking,
    faceDetected,
}) => {
    if (connectionError) {
        return 'connection_error';
    }

    if (!isRegistered) {
        return 'connecting';
    }

    if (isRecording) {
        return 'recording';
    }

    if (isWaitingResponse) {
        return 'waiting_response';
    }

    if (isSpeaking) {
        return 'speaking';
    }

    if (!faceDetected) {
        return 'face_not_detected';
    }

    return 'ready';
};

const getSessionDisplayName = (sessionIdentity) => {
    const knownUserName = typeof sessionIdentity?.userName === 'string'
        ? sessionIdentity.userName.trim()
        : '';

    if (knownUserName && knownUserName.toLowerCase() !== 'unknown') {
        return knownUserName;
    }

    const loginName = typeof sessionIdentity?.loginName === 'string'
        ? sessionIdentity.loginName.trim()
        : '';

    return loginName || 'Usuario';
};

const UI = ({
    sharedStream,
    onRobotStateChange,
    sessionIdentity,
    onSessionIdentityChange,
    onLogout,
    isLoggingOut,
}) => {
    // Main states
    const [connectionError, setConnectionError] = useState(false);
    const [isWaitingResponse, setIsWaitingResponse] = useState(false);
    const [faceDetected, setFaceDetected] = useState(false);
    const [logoutError, setLogoutError] = useState('');
    const lastUiStatusRef = useRef(null);

    // Context and references
    const { isConnected, isRegistered, emit, socket } = useWebSocketContext();

    // Audio hooks
    const {
        isRecording,
        isSpeaking,
        startRecording,
        stopRecording,
        handleSynthesize
    } = useAudioRecorder(
        () => { setIsWaitingResponse(false); },
        isWaitingResponse,
        () => { setIsWaitingResponse(true); }
    );

    /**
     * Extracts the state name from the message and notifies RobotView.
     * ANIMATION_MAPPINGS maps server state keys (e.g. 'joy') to display names,
     * but for the eye service we pass the raw key directly.
     */
    const notifyRobotState = useCallback((state) => {
        if (!state) return;
        // Validate against known states; fall back to neutral
        const knownState = ANIMATION_MAPPINGS[state] ? state : 'neutral';
        onRobotStateChange?.(knownState);
    }, [onRobotStateChange]);

    const handleRobotMessage = useCallback(async (message) => {
        if (message.state) {
            notifyRobotState(message.state);
        }

        if (message.text?.trim()) {
            console.log('[SHARA][robot]', message.text);
            await handleSynthesize(message.text, message.audio || null);
        }
        emit('tts_complete', {});
        setIsWaitingResponse(false);
    }, [notifyRobotState, handleSynthesize, emit]);

    const handleWizardMessage = useCallback(async (message) => {
        if (message.state) {
            notifyRobotState(message.state);
        }

        if (message.text?.trim()) {
            console.log('[SHARA][wizard]', message.text);
        }

        await handleSynthesize(message.text);
        emit('tts_complete', {});
        setIsWaitingResponse(false);
    }, [notifyRobotState, handleSynthesize, emit]);

    const handleClientMessage = useCallback((message) => {
        if (message.text?.trim()) {
            console.log('[SHARA][client]', message.text);
            setIsWaitingResponse(true);
        }
    }, []);

    const handleFaceDetected = () => {
        setFaceDetected(true);
        if (!isRecording && !isWaitingResponse && !isSpeaking) {
            startRecording();
        }
    };

    const handleFaceLost = () => {
        setFaceDetected(false);
        if (isRecording) {
            stopRecording();
        }
    };

    const handleLogoutClick = useCallback(async () => {
        if (!onLogout) {
            return;
        }

        setLogoutError('');

        try {
            await onLogout();
        } catch (error) {
            setLogoutError(error?.message || 'No se pudo cerrar la sesion');
        }
    }, [onLogout]);

    // Track connection status
    useEffect(() => {
        setConnectionError(!isConnected);
    }, [isConnected]);

    useEffect(() => {
        const nextStatus = getUiConsoleStatus({
            connectionError,
            isRegistered,
            isRecording,
            isWaitingResponse,
            isSpeaking,
            faceDetected,
        });

        if (lastUiStatusRef.current === nextStatus) {
            return;
        }

        lastUiStatusRef.current = nextStatus;
        console.log(`[SHARA][ui-status] ${UI_STATUS_MESSAGES[nextStatus]} (${nextStatus})`);
    }, [connectionError, isRegistered, isRecording, isWaitingResponse, isSpeaking, faceDetected]);

    // Register socket event listeners
    useEffect(() => {
        if (!socket) return;

        socket.off('robot_message');
        socket.off('wizard_message');
        socket.off('client_message');
        socket.off('transcription_result');
        socket.off('session_identity_updated');

        const handleSessionIdentityUpdated = (nextSessionIdentity) => {
            if (!nextSessionIdentity?.sessionId || nextSessionIdentity.sessionId !== sessionIdentity?.sessionId) {
                return;
            }

            onSessionIdentityChange?.((currentIdentity) => ({
                ...(currentIdentity || {}),
                ...nextSessionIdentity,
            }));
        };

        socket.on('robot_message', handleRobotMessage);
        socket.on('wizard_message', handleWizardMessage);
        socket.on('client_message', handleClientMessage);
        socket.on('transcription_result', handleClientMessage);
        socket.on('session_identity_updated', handleSessionIdentityUpdated);
        socket.on('audio_empty', () => { setIsWaitingResponse(false); });

        return () => {
            socket.off('robot_message');
            socket.off('wizard_message');
            socket.off('client_message');
            socket.off('transcription_result');
            socket.off('session_identity_updated', handleSessionIdentityUpdated);
            socket.off('audio_empty');
        };
    }, [socket, handleClientMessage, handleRobotMessage, handleWizardMessage, onSessionIdentityChange, sessionIdentity?.sessionId]);

    useEffect(() => {
        if (!isRegistered || !sessionIdentity?.sessionId) {
            return;
        }

        emit('set_login_identity', sessionIdentity);
    }, [emit, isRegistered, sessionIdentity]);

    // Auto-restart recording when face is present and system is idle
    useEffect(() => {
        if (!isWaitingResponse && !isRecording && !isSpeaking && faceDetected) {
            const timer = setTimeout(() => {
                startRecording();
            }, 1000);
            return () => clearTimeout(timer);
        }
    }, [isWaitingResponse, isRecording, isSpeaking, faceDetected, startRecording]);

    const sessionDisplayName = getSessionDisplayName(sessionIdentity);

    return (
        <div className="ui-overlay">
            <aside className="led-legend-panel" aria-label="Leyenda LED de SHARA">
                <div className="led-legend-session-bar">
                    <div className="led-legend-session-copy">
                        <p className="led-legend-kicker">SESION ACTIVA</p>
                        <p className="led-legend-session-user">{sessionDisplayName}</p>
                    </div>

                    <button
                        className="session-logout-button"
                        type="button"
                        onClick={handleLogoutClick}
                        disabled={isLoggingOut}
                    >
                        {isLoggingOut ? 'Cerrando...' : 'Cerrar sesion'}
                    </button>
                </div>

                {logoutError && (
                    <p className="session-logout-error">{logoutError}</p>
                )}

                <p className="led-legend-section-label">ESTADOS LED</p>
                <h2 className="led-legend-title">Significado de colores</h2>
                <ul className="led-legend-list">
                    {LED_LEGEND_ITEMS.map((item) => (
                        <li key={item.id} className="led-legend-item">
                            <span className={`led-legend-chip ${item.chipClass}`} />
                            <div className="led-legend-copy">
                                <span className="led-legend-item-title">{item.title}</span>
                                <span className="led-legend-item-description">{item.description}</span>
                            </div>
                        </li>
                    ))}
                </ul>
            </aside>

            {sharedStream && (
                <FaceDetection
                    onFaceDetected={handleFaceDetected}
                    onFaceLost={handleFaceLost}
                    stream={sharedStream}
                    sessionIdentity={sessionIdentity}
                />
            )}
        </div>
    );
};

UI.propTypes = {
    sharedStream: PropTypes.instanceOf(MediaStream),
    onRobotStateChange: PropTypes.func,
    sessionIdentity: PropTypes.shape({
        sessionId: PropTypes.string,
        loginName: PropTypes.string,
        userName: PropTypes.string,
        isNewUser: PropTypes.bool,
        needsIdentification: PropTypes.bool,
        userStatus: PropTypes.string,
    }),
    onSessionIdentityChange: PropTypes.func,
    onLogout: PropTypes.func,
    isLoggingOut: PropTypes.bool,
};

export default UI;
