/**
 * UI
 * 
 * Overlay component that handles:
 * - Chat window (messages, input)
 * - Audio recording and synthesis
 * - Face detection (wakeface)
 * - Status bar
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
import AudioControls from './subcomponents/AudioControls';
import ChatWindow from './subcomponents/ChatWindow';
import StatusBar from './utils/StatusBar';

const UI = ({ sharedStream, onRobotStateChange, sessionIdentity, onSessionIdentityChange }) => {
    // Main states
    const [messages, setMessages] = useState([]);
    const [newMessage, setNewMessage] = useState('');
    const [isChatVisible, setIsChatVisible] = useState(true);
    const [connectionError, setConnectionError] = useState(false);
    const [isWaitingResponse, setIsWaitingResponse] = useState(false);
    const [faceDetected, setFaceDetected] = useState(false);

    // Context and references
    const { isConnected, isRegistered, emit, socket } = useWebSocketContext();
    const messagesContainerRef = useRef(null);

    // Audio hooks
    const {
        isRecording,
        audioSrc,
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
            console.log("Received robot message:", message.text);
            setMessages((prev) => [...prev, { text: message.text, sender: 'robot' }]);
            await handleSynthesize(message.text, message.audio || null);
        }
        emit('tts_complete', {});
        setIsWaitingResponse(false);
    }, [notifyRobotState, handleSynthesize, emit]);

    const handleWizardMessage = useCallback(async (message) => {
        if (message.state) {
            notifyRobotState(message.state);
        }
        setMessages((prev) => [...prev, { text: message.text, sender: 'wizard' }]);
        await handleSynthesize(message.text);
        emit('tts_complete', {});
        setIsWaitingResponse(false);
    }, [notifyRobotState, handleSynthesize, emit]);

    const handleClientMessage = (message) => {
        if (message.text?.trim()) {
            setMessages((prev) => [...prev, { text: message.text, sender: 'client' }]);
            setIsWaitingResponse(true);
        }
    };

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

    const handleSendMessage = (text = null) => {
        const messageText = text || newMessage.trim();

        if (messageText && isConnected) {
            const messageObject = {
                type: "client_message",
                text: messageText,
                proactive_question: "Ninguna",
                username: sessionIdentity?.userName || "unknown"
            };

            const success = emit('client_message', messageObject);

            if (success) {
                setIsWaitingResponse(success);
                setMessages((prev) => [...prev, { text: messageText, sender: 'client' }]);
                setNewMessage('');
                setTimeout(scrollToBottom, 100);
            } else {
                setMessages((prev) => [...prev, {
                    text: "No se pudo enviar el mensaje. Comprueba tu conexión.",
                    sender: 'robot'
                }]);
            }
        }
    };

    const scrollToBottom = () => {
        if (messagesContainerRef.current) {
            messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
        }
    };

    // Scroll to bottom when messages update
    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    // Track connection status
    useEffect(() => {
        setConnectionError(!isConnected);
    }, [isConnected]);

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
    }, [socket, handleRobotMessage, handleWizardMessage, onSessionIdentityChange, sessionIdentity?.sessionId]);

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

    return (
        <div className="chat-wrapper">
            <button
                className="toggle-chat-button"
                onClick={() => setIsChatVisible(!isChatVisible)}
            >
                {isChatVisible ? '🗨️ Ocultar chat' : '🗨️ Mostrar chat'}
            </button>
            <ChatWindow
                messages={messages}
                newMessage={newMessage}
                messagesContainerRef={messagesContainerRef}
                isChatVisible={isChatVisible}
                onMessageSend={handleSendMessage}
                onInputChange={(e) => setNewMessage(e.target.value)}
            >
                <div className="chat-controls">
                    <AudioControls
                        isRecording={isRecording}
                        isSpeaking={isSpeaking}
                        isWaitingResponse={isWaitingResponse}
                        onStartRecording={startRecording}
                        onStopRecording={stopRecording}
                    />
                    <StatusBar
                        isRegistered={isRegistered}
                        connectionError={connectionError}
                        isSpeaking={isSpeaking}
                        isWaitingResponse={isWaitingResponse}
                        audioSrc={audioSrc}
                        faceDetected={faceDetected}
                    />
                    {sharedStream && (
                        <FaceDetection
                            onFaceDetected={handleFaceDetected}
                            onFaceLost={handleFaceLost}
                            stream={sharedStream}
                            sessionIdentity={sessionIdentity}
                        />
                    )}
                </div>
            </ChatWindow>
        </div>
    );
};

UI.propTypes = {
    sharedStream: PropTypes.instanceOf(MediaStream),
    onRobotStateChange: PropTypes.func,
    sessionIdentity: PropTypes.shape({
        sessionId: PropTypes.string,
        userName: PropTypes.string,
        isNewUser: PropTypes.bool,
        needsIdentification: PropTypes.bool,
        userStatus: PropTypes.string,
    }),
    onSessionIdentityChange: PropTypes.func,
};

export default UI;
