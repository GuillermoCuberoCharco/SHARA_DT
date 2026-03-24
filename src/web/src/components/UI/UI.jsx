/**
 * UI
 *
 * Panel de chat lateral derecho para conversación de texto con SHARA.
 *
 * Props:
 *   onRobotStateChange - Callback(stateName: string) para el estado emocional del robot
 */

import PropTypes from 'prop-types';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ANIMATION_MAPPINGS } from "../../config";
import { useWebSocketContext } from '../../contexts/WebSocketContext';
import { useAuth } from '../../auth/useAuth';
import '../../styles/InterfaceStyle.css';
import ChatWindow from './subcomponents/ChatWindow';

const UI = ({ onRobotStateChange, onLogout }) => {
    const { getUserId } = useAuth();
    const username = getUserId();
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
        if (message.state) notifyRobotState(message.state);
        if (message.text?.trim()) {
            setMessages((prev) => [...prev, { text: message.text, sender: 'robot' }]);
        }
        setIsWaitingResponse(false);
    }, [notifyRobotState]);

    const scrollToBottom = () => {
        if (messagesContainerRef.current) {
            messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
        }
    };

    const handleSendMessage = (text = null) => {
        const messageText = text || newMessage.trim();
        if (!messageText || !isConnected) return;

        const success = emit('client_message', { type: 'client_message', text: messageText });

        if (success) {
            setIsWaitingResponse(true);
            setMessages((prev) => [...prev, { text: messageText, sender: 'client' }]);
            setNewMessage('');
            setTimeout(scrollToBottom, 100);
        } else {
            setMessages((prev) => [...prev, {
                text: 'No se pudo enviar el mensaje. Comprueba tu conexión.',
                sender: 'robot',
            }]);
        }
    };

    useEffect(() => { scrollToBottom(); }, [messages, isWaitingResponse]);

    useEffect(() => { setConnectionError(!isConnected); }, [isConnected]);

    useEffect(() => {
        if (!socket) return;
        socket.off('robot_message');
        socket.on('robot_message', handleRobotMessage);
        return () => { socket.off('robot_message'); };
    }, [socket, handleRobotMessage]);

    return (
        <>
            {!isChatVisible && (
                <button className="chat-tab" onClick={() => setIsChatVisible(true)}>
                    Chat
                </button>
            )}
            <ChatWindow
                messages={messages}
                newMessage={newMessage}
                messagesContainerRef={messagesContainerRef}
                isVisible={isChatVisible}
                onClose={() => setIsChatVisible(false)}
                onMessageSend={handleSendMessage}
                onInputChange={(e) => setNewMessage(e.target.value)}
                isWaitingResponse={isWaitingResponse}
                isRegistered={isRegistered}
                connectionError={connectionError}
                username={username}
                onLogout={onLogout}
            />
        </>
    );
};

UI.propTypes = {
    onRobotStateChange: PropTypes.func,
    onLogout: PropTypes.func,
};

export default UI;
