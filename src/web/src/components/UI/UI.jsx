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
        description: 'Presencia detectada. Shara está atenta.',
    },
    {
        id: 'listening',
        chipClass: 'led-legend-chip-listening',
        title: 'Azul girando',
        description: 'Shara está escuchando.',
    },
    {
        id: 'recording',
        chipClass: 'led-legend-chip-recording',
        title: 'Blanco girando',
        description: 'Audio en grabación.',
    },
    {
        id: 'speaking',
        chipClass: 'led-legend-chip-speaking',
        title: 'Azul respirando',
        description: 'Shara está hablando.',
    },
    {
        id: 'off',
        chipClass: 'led-legend-chip-off',
        title: 'Apagado tenue',
        description: 'Sin interacción activa o procesando.',
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
    if (!isRegistered) {
        return 'connecting';
    }

    if (connectionError) {
        return 'connection_error';
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

const isForCurrentSession = (payload, sessionIdentity) => {
    if (!payload?.sessionId || !sessionIdentity?.sessionId) {
        return true;
    }

    return payload.sessionId === sessionIdentity.sessionId;
};

const SERVER_RECORDING_READY_STATE = 'listening';
const CLIENT_TTS_MIN_TIMEOUT_MS = 8000;
const CLIENT_TTS_MAX_TIMEOUT_MS = 50000;
const CLIENT_TTS_MS_PER_CHAR = 90;
const CLIENT_TTS_TIMEOUT_GRACE_MS = 4500;

const createTimeoutError = (message) => {
    const error = new Error(message);
    error.name = 'TimeoutError';
    return error;
};

const withTimeout = (promise, timeoutMs, message) => new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
        if (settled) {
            return;
        }

        settled = true;
        reject(createTimeoutError(message));
    }, timeoutMs);

    Promise.resolve(promise).then(
        (value) => {
            if (settled) {
                return;
            }

            settled = true;
            clearTimeout(timer);
            resolve(value);
        },
        (error) => {
            if (settled) {
                return;
            }

            settled = true;
            clearTimeout(timer);
            reject(error);
        },
    );
});

const estimateTtsTimeoutMs = (text) => {
    const textLength = String(text || '').trim().length;
    const estimate = (textLength * CLIENT_TTS_MS_PER_CHAR) + CLIENT_TTS_TIMEOUT_GRACE_MS;

    return Math.max(
        CLIENT_TTS_MIN_TIMEOUT_MS,
        Math.min(CLIENT_TTS_MAX_TIMEOUT_MS, estimate),
    );
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
    const [serverConversationState, setServerConversationState] = useState('idle');
    const [isLedLegendOpen, setIsLedLegendOpen] = useState(() => {
        if (typeof window === 'undefined') {
            return true;
        }

        return !window.matchMedia('(max-width: 640px)').matches;
    });
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

    const completeTtsForMessage = useCallback(async (message, source) => {
        if (!isForCurrentSession(message, sessionIdentity)) {
            return;
        }

        const messageId = message.messageId || null;
        const timeoutMs = Number(message.ttsTimeoutMs) > 0
            ? Number(message.ttsTimeoutMs)
            : estimateTtsTimeoutMs(message.text);
        let status = message.text?.trim() || message.audio ? 'played' : 'skipped_empty';

        try {
            if (message.text?.trim() || message.audio) {
                console.log(`[SHARA][${source}]`, message.text || '[audio]');
                await withTimeout(
                    handleSynthesize(
                        message.text,
                        message.audio || null,
                        message.audioMimeType || 'audio/mpeg',
                        { timeoutMs },
                    ),
                    timeoutMs + 1500,
                    'TTS playback timed out',
                );
            }
        } catch (error) {
            status = error?.name === 'TimeoutError' ? 'timeout' : 'failed';
            handleSynthesize.cancel?.();
            console.error(`[SHARA][${source}] TTS ${status}:`, error);
        } finally {
            emit('tts_complete', {
                sessionId: sessionIdentity?.sessionId || null,
                messageId,
                status,
            });
            setIsWaitingResponse(false);
        }
    }, [emit, handleSynthesize, sessionIdentity]);

    const handleRobotMessage = useCallback(async (message) => {
        if (!isForCurrentSession(message, sessionIdentity)) {
            return;
        }

        if (message.state) {
            notifyRobotState(message.state);
        }

        await completeTtsForMessage(message, 'robot');
    }, [notifyRobotState, completeTtsForMessage, sessionIdentity]);

    const handleWizardMessage = useCallback(async (message) => {
        if (!isForCurrentSession(message, sessionIdentity)) {
            return;
        }

        if (message.state) {
            notifyRobotState(message.state);
        }

        await completeTtsForMessage(message, 'wizard');
    }, [notifyRobotState, completeTtsForMessage, sessionIdentity]);

    const handleClientMessage = useCallback((message) => {
        if (!isForCurrentSession(message, sessionIdentity)) {
            return;
        }

        if (message.text?.trim()) {
            console.log('[SHARA][client]', message.text);
            setIsWaitingResponse(true);
        }
    }, [sessionIdentity]);

    const canStartRecording = serverConversationState === SERVER_RECORDING_READY_STATE;

    const handleFaceDetected = useCallback(() => {
        setFaceDetected(true);
    }, []);

    const handleFaceLost = useCallback(() => {
        setFaceDetected(false);
        if (isRecording) {
            stopRecording();
        }
    }, [isRecording, stopRecording]);

    const handleLogoutClick = useCallback(async () => {
        if (!onLogout) {
            return;
        }

        setLogoutError('');

        try {
            await onLogout();
        } catch (error) {
            setLogoutError(error?.message || 'No se pudo cerrar la sesión');
        }
    }, [onLogout]);

    // Track connection status
    useEffect(() => {
        setConnectionError(!isConnected);
    }, [isConnected]);

    useEffect(() => {
        setServerConversationState('idle');
        setIsWaitingResponse(false);
    }, [sessionIdentity?.sessionId]);

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

        const handleStateUpdate = (payload) => {
            if (!isForCurrentSession(payload, sessionIdentity)) {
                return;
            }

            const nextState = payload?.state || 'idle';
            setServerConversationState(nextState);

            if (nextState === 'processing_query') {
                setIsWaitingResponse(true);
            } else if (nextState === 'idle' || nextState === 'idle_presence' || nextState === 'listening') {
                setIsWaitingResponse(false);
            }
        };

        socket.on('robot_message', handleRobotMessage);
        socket.on('wizard_message', handleWizardMessage);
        socket.on('client_message', handleClientMessage);
        socket.on('transcription_result', handleClientMessage);
        socket.on('session_identity_updated', handleSessionIdentityUpdated);
        socket.on('state_update', handleStateUpdate);
        const handleAudioEmpty = (payload) => {
            if (!isForCurrentSession(payload, sessionIdentity)) {
                return;
            }

            setIsWaitingResponse(false);
        };

        socket.on('audio_empty', handleAudioEmpty);

        return () => {
            socket.off('robot_message');
            socket.off('wizard_message');
            socket.off('client_message');
            socket.off('transcription_result');
            socket.off('session_identity_updated', handleSessionIdentityUpdated);
            socket.off('state_update', handleStateUpdate);
            socket.off('audio_empty', handleAudioEmpty);
        };
    }, [socket, handleClientMessage, handleRobotMessage, handleWizardMessage, onSessionIdentityChange, sessionIdentity]);

    useEffect(() => {
        if (!isRegistered || !sessionIdentity?.sessionId) {
            return;
        }

        emit('set_login_identity', sessionIdentity);
    }, [emit, isRegistered, sessionIdentity]);

    // Auto-restart recording only when the backend state machine is listening.
    useEffect(() => {
        if (canStartRecording && !isWaitingResponse && !isRecording && !isSpeaking && faceDetected) {
            const timer = setTimeout(() => {
                startRecording();
            }, 150);
            return () => clearTimeout(timer);
        }
    }, [canStartRecording, isWaitingResponse, isRecording, isSpeaking, faceDetected, startRecording]);

    const sessionDisplayName = getSessionDisplayName(sessionIdentity);

    return (
        <div className="ui-overlay">
            <aside
                className={`led-legend-panel${isLedLegendOpen ? '' : ' led-legend-panel-collapsed'}`}
                aria-label="Leyenda LED de SHARA"
            >
                {!isLedLegendOpen ? (
                    <button
                        className="led-legend-collapsed-button"
                        type="button"
                        onClick={() => { setIsLedLegendOpen(true); }}
                        aria-expanded="false"
                        aria-controls="led-legend-content"
                        aria-label="Mostrar leyenda de colores LED"
                        title="Mostrar leyenda LED"
                    >
                        <span className="led-legend-collapsed-dot" aria-hidden="true" />
                        <span className="led-legend-collapsed-label">LED</span>
                    </button>
                ) : (
                    <>
                        <div className="led-legend-session-bar">
                            <div className="led-legend-session-copy">
                                <p className="led-legend-kicker">SESIÓN ACTIVA</p>
                                <p className="led-legend-session-user">{sessionDisplayName}</p>
                            </div>

                            <button
                                className="session-logout-button"
                                type="button"
                                onClick={handleLogoutClick}
                                disabled={isLoggingOut}
                            >
                                {isLoggingOut ? 'Cerrando...' : 'Cerrar sesión'}
                            </button>
                        </div>

                        {logoutError && (
                            <p className="session-logout-error">{logoutError}</p>
                        )}

                        <div className="led-legend-header">
                            <div className="led-legend-header-copy">
                                <p className="led-legend-section-label">ESTADOS LED</p>
                                <h2 className="led-legend-title">Significado de colores</h2>
                            </div>

                            <button
                                className="led-legend-toggle"
                                type="button"
                                onClick={() => { setIsLedLegendOpen(false); }}
                                aria-expanded="true"
                                aria-controls="led-legend-content"
                            >
                                <span>Ocultar</span>
                                <span className="led-legend-toggle-icon" aria-hidden="true" />
                            </button>
                        </div>

                        <div
                            id="led-legend-content"
                            className="led-legend-content"
                        >
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
                        </div>
                    </>
                )}
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
        sharaName: PropTypes.string,
        isNewUser: PropTypes.bool,
        needsIdentification: PropTypes.bool,
        userStatus: PropTypes.string,
    }),
    onSessionIdentityChange: PropTypes.func,
    onLogout: PropTypes.func,
    isLoggingOut: PropTypes.bool,
};

export default UI;
