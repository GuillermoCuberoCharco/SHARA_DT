/**
 * UI
 *
 * Text-only chat interface overlay.
 *
 * Props:
 *   onRobotStateChange - Callback(stateName: string) for robot emotional state
 */

import PropTypes from 'prop-types';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ANIMATION_MAPPINGS } from "../../config";
import { useWebSocketContext } from '../../contexts/WebSocketContext';
import '../../styles/InterfaceStyle.css';
import ChatWindow from './subcomponents/ChatWindow';
import StatusBar from './utils/StatusBar';

const UI = ({ onRobotStateChange }) => {
    const [messages, setMessages] = useState([]);
    const [newMessage, setNewMessage] = useState('');
    const [isChatVisible, setIsChatVisible] = useState(true);
    const [connectionError, setConnectionError] = useState(false);
    const [isWaitingResponse, setIsWaitingResponse] = useState(false);

    const { isConnected, isRegistered, emit, socket } = useWebSocketContext();
    const messagesContainerRef = useRef(null);

    const notifyRobotState = useCallback((state) => {
        if (!state) return;
        const knownState = ANIMATION_MAPPINGS[state] ? state : 'neutral';
        onRobotStateChange?.(knownState);
    }, [onRobotStateChange]);

    const handleRobotMessage = useCallback((message) => {
        if (message.state) {
            notifyRobotState(message.state);
        }
        if (message.text?.trim()) {
            setMessages((prev) => [...prev, { text: message.text, sender: 'robot' }]);
        }
        setIsWaitingResponse(false);
    }, [notifyRobotState]);

    const handleSendMessage = (text = null) => {
        const messageText = text || newMessage.trim();

        if (messageText && isConnected) {
            const messageObject = {
                type: 'client_message',
                text: messageText,
            };

            const success = emit('client_message', messageObject);

            if (success) {
                setIsWaitingResponse(true);
                setMessages((prev) => [...prev, { text: messageText, sender: 'client' }]);
                setNewMessage('');
                setTimeout(scrollToBottom, 100);
            } else {
                setMessages((prev) => [...prev, {
                    text: 'No se pudo enviar el mensaje. Comprueba tu conexión.',
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

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    useEffect(() => {
        setConnectionError(!isConnected);
    }, [isConnected]);

    useEffect(() => {
        if (!socket) return;

        socket.off('robot_message');
        socket.on('robot_message', handleRobotMessage);

        return () => {
            socket.off('robot_message');
        };
    }, [socket, handleRobotMessage]);

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
                    <StatusBar
                        isRegistered={isRegistered}
                        connectionError={connectionError}
                        isWaitingResponse={isWaitingResponse}
                    />
                </div>
            </ChatWindow>
        </div>
    );
};

UI.propTypes = {
    onRobotStateChange: PropTypes.func,
};

export default UI;
