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
 *   onRobotStateChange - Callback(stateName: string) notifying the current robot emotional state
 */

import PropTypes from 'prop-types';
import { useCallback, useEffect, useRef, useState } from 'react';
import { SERVER_URL } from '../../config';
import { cancelAudioPlayback, playAudioBase64 } from '../../utils/audioPlayback';
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

const UI = ({ sessionIdentity, onSessionIdentityChange, onRobotStateChange, onLogout, isLoggingOut }) => {
    const { socket, isRegistered, connectionError, emit } = useWebSocketContext();
    const sessionId = sessionIdentity.sessionId;
    const [turn, setTurn] = useState(null);
    const live = useRef(null);
    const playback = useRef(null);
    const [visible, setVisible] = useState(!document.hidden);
    const [cameraError, setCameraError] = useState('');
    const [retry, setRetry] = useState(0);
    const [notice, setNotice] = useState('');
    const [logoutError, setLogoutError] = useState('');
    const [isLedLegendOpen, setIsLedLegendOpen] = useState(() => !window.matchMedia('(max-width: 640px)').matches);
    const active = visible && isRegistered && !!turn && !isLoggingOut;
    const capturing = turn?.state === 'listening' || turn?.state === 'recording';
    const microphoneError = useCallback(() => setNotice('Comprueba el permiso del micrófono.'), []);
    useAudioRecorder(active && capturing, sessionId, turn?.turnId, emit, microphoneError);

    const stopPlayback = useCallback(() => {
        if (playback.current) {
            playback.current.abort();
            playback.current = null;
            cancelAudioPlayback('turn_ended');
        }
    }, []);

    useEffect(() => {
        const visibility = () => {
            setVisible(!document.hidden);
            if (document.hidden) {
                stopPlayback();
                emit('user_lost', { sessionId, reason: 'document_hidden' });
            }
        };
        document.addEventListener('visibilitychange', visibility);
        return () => document.removeEventListener('visibilitychange', visibility);
    }, [emit, sessionId, stopPlayback]);

    useEffect(() => {
        if (!socket || !isRegistered) return;
        const state = next => {
            if (next.sessionId !== sessionId) return;
            if (next.messageId !== live.current?.messageId || next.state !== 'speaking') stopPlayback();
            live.current = next;
            setTurn(next);
            if (next.state === 'listening' || next.state === 'processing_query') setNotice('');
            if (next.state === 'idle') onRobotStateChange('neutral');
        };
        const identity = payload => {
            if (payload.sessionId === sessionId) onSessionIdentityChange(old => ({ ...old, ...payload }));
        };
        const error = payload => {
            if (payload.sessionId === sessionId && payload.turnId === live.current?.turnId) setNotice(payload.text);
        };
        const speak = async message => {
            if (document.hidden || message.sessionId !== sessionId || !message.messageId ||
                message.messageId !== live.current?.messageId || live.current.state !== 'speaking' ||
                playback.current) return;
            const controller = new AbortController();
            playback.current = controller;
            const timeout = setTimeout(() => {
                controller.abort();
                cancelAudioPlayback('playback_timeout');
                if (playback.current === controller) {
                    playback.current = null;
                    emit('tts_complete', { sessionId, turnId: message.turnId, messageId: message.messageId, status: 'timeout' });
                }
            }, message.ttsTimeoutMs);
            let status = 'failed';
            try {
                let audio = message.audio;
                let mime = message.audioMimeType || 'audio/mpeg';
                if (!audio && message.text) {
                    const res = await fetch(`${SERVER_URL}/api/synthesize`, {
                        method: 'POST', credentials: 'include', signal: controller.signal,
                        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: message.text }),
                    });
                    if (!res.ok) throw new Error('Error de síntesis');
                    const result = await res.json();
                    audio = result.audioContent;
                    mime = result.audioMimeType || mime;
                }
                if (!controller.signal.aborted && await playAudioBase64(audio, mime, { timeoutMs: message.ttsTimeoutMs })) {
                    status = 'played';
                }
            } catch (err) {
                if (!controller.signal.aborted) console.warn('Error de reproducción', err);
            } finally {
                clearTimeout(timeout);
                if (playback.current === controller) {
                    playback.current = null;
                    emit('tts_complete', { sessionId, turnId: message.turnId, messageId: message.messageId, status });
                }
            }
        };
        socket.on('state_update', state);
        socket.on('robot_message', speak);
        socket.on('session_identity_updated', identity);
        socket.on('interaction_error', error);
        emit('set_login_identity', { sessionId, protocolVersion: 2 });
        return () => {
            socket.off('state_update', state);
            socket.off('robot_message', speak);
            socket.off('session_identity_updated', identity);
            socket.off('interaction_error', error);
            live.current = null;
            setTurn(null);
            stopPlayback();
        };
    }, [socket, isRegistered, emit, sessionId, onSessionIdentityChange, onRobotStateChange, stopPlayback]);

    const cameraFailed = text => {
        setCameraError(text);
        if (live.current) emit('device_error', { ...live.current, device: 'camera' });
    };
    const presence = (present, observed) => {
        if (document.hidden || observed.turnId !== live.current?.turnId) return;
        emit(present ? 'user_detected' : 'user_lost', {
            sessionId, turnId: observed.turnId, presenceCheck: observed.presenceCheck, reason: 'face_timeout',
        });
    };
    const handleLogoutClick = async () => {
        setLogoutError('');
        stopPlayback();
        try { await onLogout(); } catch (err) { setLogoutError(err.message); }
    };
    const sessionDisplayName = getSessionDisplayName(sessionIdentity);
    return (
        <div className="ui-overlay">
            <div className="interaction-controls" aria-live="polite">
                {!isRegistered && (connectionError
                    ? <><p>Se perdió la conexión con SHARA.</p><button onClick={() => window.location.reload()}>Volver a conectar</button></>
                    : <p>Conectando con SHARA…</p>)}
                {cameraError && <><p>{cameraError}</p><button onClick={() => {
                    setCameraError(''); setRetry(n => n + 1);
                }}>Reintentar cámara</button></>}
                {notice && <p>{notice}</p>}
                {active && turn.state === 'idle_presence' && !turn.presenceCheck && !cameraError &&
                    <button onClick={() => emit('resume_listening', { sessionId, turnId: turn.turnId })}>Retomar conversación</button>}
                {active && turn.state === 'listening' && !turn.microphoneReady && <p>Activando micrófono…</p>}
                {active && turn.presenceCheck && <p>Comprobando presencia…</p>}
            </div>
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

            {!cameraError && <FaceDetection key={retry} active={active && !capturing}
                turn={turn} onPresence={presence} onError={cameraFailed} />}
        </div>
    );
};

UI.propTypes = {
    sessionIdentity: PropTypes.object.isRequired,
    onSessionIdentityChange: PropTypes.func.isRequired,
    onRobotStateChange: PropTypes.func.isRequired,
    onLogout: PropTypes.func.isRequired,
    isLoggingOut: PropTypes.bool,
};
export default UI;
