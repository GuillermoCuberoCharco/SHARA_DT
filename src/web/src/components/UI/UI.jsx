import PropTypes from 'prop-types';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ANIMATION_MAPPINGS } from '../../config';
import { useAuth } from '../../auth/useAuth';
import { useWebSocketContext } from '../../contexts/WebSocketContext';
import '../../styles/InterfaceStyle.css';
import useAudioRecorder from './hooks/useAudioRecorder';
import ChatWindow from './subcomponents/ChatWindow';

const TTS_PREFERENCE_KEY = 'shara_tts_enabled';

const UI = ({ onRobotStateChange, onLogout }) => {
    const { getUserId, getSubjectCode, getSubjectCodes, addSubjects, switchSubject } = useAuth();
    const username = getUserId();
    const subjectCode = getSubjectCode();
    const displayUsername = username
        ? (subjectCode ? `${username} - ${subjectCode}` : username)
        : '';

    const [messages, setMessages] = useState([]);
    const [newMessage, setNewMessage] = useState('');
    const [isChatVisible, setIsChatVisible] = useState(true);
    const [connectionError, setConnectionError] = useState(false);
    const [isWaitingResponse, setIsWaitingResponse] = useState(false);
    const [conversationState, setConversationState] = useState('idle');
    const [subjectCodes, setSubjectCodes] = useState(() => getSubjectCodes());
    const [isAddingSubjects, setIsAddingSubjects] = useState(false);
    const [isSwitchingSubject, setIsSwitchingSubject] = useState(false);
    const [subjectFeedback, setSubjectFeedback] = useState('');
    const [subjectFeedbackTone, setSubjectFeedbackTone] = useState('info');
    const [isTtsEnabled, setIsTtsEnabled] = useState(() => {
        const stored = localStorage.getItem(TTS_PREFERENCE_KEY);
        return stored === null ? true : stored === 'true';
    });

    const { isConnected, isRegistered, emit, refreshConnection, socket } = useWebSocketContext();
    const messagesContainerRef = useRef(null);

    const appendMessage = useCallback((message) => {
        if (!message?.text?.trim()) {
            return;
        }

        setMessages((prev) => [...prev, message]);
    }, []);

    const notifyRobotState = useCallback((state) => {
        if (!state) {
            return;
        }

        const knownState = ANIMATION_MAPPINGS[state] ? state : 'neutral';
        onRobotStateChange?.(knownState);
    }, [onRobotStateChange]);

    const {
        isRecording,
        isSpeaking,
        startRecording,
        stopRecording,
        playAudio,
        stopPlayback,
    } = useAudioRecorder({
        isWaitingResponse,
        onAudioSubmitted: () => {
            setIsWaitingResponse(true);
            setConversationState('processing_query');
        },
        onAudioError: (text) => appendMessage({ text, sender: 'robot' }),
    });

    const scrollToBottom = useCallback(() => {
        if (messagesContainerRef.current) {
            messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
        }
    }, []);

    const handleRobotMessage = useCallback((message) => {
        if (message.state) {
            notifyRobotState(message.state);
        }

        if (message.text?.trim()) {
            appendMessage({ text: message.text, sender: 'robot' });
        }

        setIsWaitingResponse(false);
        setConversationState('idle');

        if (message.audio && isTtsEnabled) {
            playAudio(message.audio);
        }
    }, [appendMessage, isTtsEnabled, notifyRobotState, playAudio]);

    const handleConversationHistory = useCallback((payload) => {
        const historyMessages = Array.isArray(payload?.messages) ? payload.messages : [];
        const normalizedHistory = historyMessages.filter(
            (item) => item?.text?.trim() && (item.sender === 'client' || item.sender === 'robot'),
        );

        setMessages((prev) => (prev.length > 0 ? prev : normalizedHistory));
        setIsWaitingResponse(false);
        setConversationState('idle');
    }, []);

    const handleTranscriptionResult = useCallback((payload) => {
        const text = payload?.text?.trim();
        if (!text) {
            return;
        }

        appendMessage({ text, sender: 'client' });
    }, [appendMessage]);

    const handleStateUpdate = useCallback((payload) => {
        const nextState = payload?.state || 'idle';
        setConversationState(nextState);

        if (nextState === 'processing_query') {
            setIsWaitingResponse(true);
        } else if (nextState === 'idle') {
            setIsWaitingResponse(false);
        }
    }, []);

    const handleSendMessage = useCallback((text = null) => {
        const messageText = (text ?? newMessage).trim();
        if (!messageText || !isConnected || !isRegistered || isSwitchingSubject) {
            return;
        }

        stopPlayback();

        const success = emit('client_message', {
            type: 'client_message',
            text: messageText,
        });

        if (success) {
            setIsWaitingResponse(true);
            setConversationState('processing_query');
            appendMessage({ text: messageText, sender: 'client' });
            setNewMessage('');
            setTimeout(scrollToBottom, 100);
        } else {
            appendMessage({
                text: 'No se pudo enviar el mensaje. Comprueba tu conexion.',
                sender: 'robot',
            });
        }
    }, [appendMessage, emit, isConnected, isRegistered, isSwitchingSubject, newMessage, scrollToBottom, stopPlayback]);

    const handleStartRecording = useCallback(() => {
        stopPlayback();
        startRecording();
    }, [startRecording, stopPlayback]);

    const handleToggleTts = useCallback(() => {
        setIsTtsEnabled((prev) => !prev);
    }, []);

    const handleAddSubjects = useCallback(async (subjectCodesInput) => {
        const normalizedInput = subjectCodesInput.trim();
        if (!normalizedInput || isAddingSubjects || isSwitchingSubject) {
            return null;
        }

        setIsAddingSubjects(true);
        setSubjectFeedback('');
        setSubjectFeedbackTone('info');

        try {
            const data = await addSubjects(normalizedInput);
            const updatedSubjectCodes = Array.isArray(data?.subject_codes) ? data.subject_codes : [];
            const addedSubjectCodes = Array.isArray(data?.added_subject_codes) ? data.added_subject_codes : [];

            setSubjectCodes(updatedSubjectCodes);

            if (addedSubjectCodes.length > 0) {
                setSubjectFeedback(
                    `Asignaturas anadidas: ${addedSubjectCodes.join(', ')}. `
                    + 'Ya puedes pulsarlas para cambiar de contexto.',
                );
                setSubjectFeedbackTone('success');
            } else {
                setSubjectFeedback('Esas asignaturas ya estaban vinculadas a tu cuenta.');
                setSubjectFeedbackTone('info');
            }

            return data;
        } catch (error) {
            setSubjectFeedback(error.message || 'No se pudieron anadir las asignaturas.');
            setSubjectFeedbackTone('error');
            throw error;
        } finally {
            setIsAddingSubjects(false);
        }
    }, [addSubjects, isAddingSubjects, isSwitchingSubject]);

    const handleSwitchSubject = useCallback(async (nextSubjectCode) => {
        const normalizedSubjectCode = nextSubjectCode.trim().toLowerCase();
        if (
            !normalizedSubjectCode
            || normalizedSubjectCode === subjectCode
            || isSwitchingSubject
            || isAddingSubjects
            || isWaitingResponse
            || isRecording
        ) {
            return null;
        }

        setIsSwitchingSubject(true);
        setSubjectFeedback(`Cambiando a ${normalizedSubjectCode}...`);
        setSubjectFeedbackTone('info');
        stopPlayback();
        setNewMessage('');
        setMessages([]);
        setIsWaitingResponse(false);
        setConversationState('idle');

        try {
            const data = await switchSubject(normalizedSubjectCode);
            const updatedSubjectCodes = Array.isArray(data?.subject_codes) ? data.subject_codes : [];
            setSubjectCodes(updatedSubjectCodes);
            await refreshConnection();
            setSubjectFeedback(`Asignatura activa cambiada a ${normalizedSubjectCode}.`);
            setSubjectFeedbackTone('success');
            return data;
        } catch (error) {
            setSubjectFeedback(error.message || 'No se pudo cambiar de asignatura.');
            setSubjectFeedbackTone('error');
            throw error;
        } finally {
            setIsSwitchingSubject(false);
        }
    }, [
        isAddingSubjects,
        isRecording,
        isSwitchingSubject,
        isWaitingResponse,
        refreshConnection,
        stopPlayback,
        subjectCode,
        switchSubject,
    ]);

    useEffect(() => {
        scrollToBottom();
    }, [conversationState, isWaitingResponse, messages, scrollToBottom]);

    useEffect(() => {
        setConnectionError(!isConnected);
    }, [isConnected]);

    useEffect(() => {
        localStorage.setItem(TTS_PREFERENCE_KEY, String(isTtsEnabled));

        if (!isTtsEnabled) {
            stopPlayback();
        }

        if (isConnected && isRegistered) {
            emit('tts_preference', { enabled: isTtsEnabled });
        }
    }, [emit, isConnected, isRegistered, isTtsEnabled, stopPlayback]);

    useEffect(() => {
        if (!socket) {
            return undefined;
        }

        socket.off('robot_message');
        socket.on('robot_message', handleRobotMessage);
        socket.off('conversation_history');
        socket.on('conversation_history', handleConversationHistory);
        socket.off('transcription_result');
        socket.on('transcription_result', handleTranscriptionResult);
        socket.off('state_update');
        socket.on('state_update', handleStateUpdate);

        return () => {
            socket.off('robot_message');
            socket.off('conversation_history');
            socket.off('transcription_result');
            socket.off('state_update');
        };
    }, [
        handleConversationHistory,
        handleRobotMessage,
        handleStateUpdate,
        handleTranscriptionResult,
        socket,
    ]);

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
                onInputChange={(event) => setNewMessage(event.target.value)}
                isWaitingResponse={isWaitingResponse}
                isRegistered={isRegistered}
                connectionError={connectionError}
                username={displayUsername}
                onLogout={onLogout}
                onStartRecording={handleStartRecording}
                onStopRecording={stopRecording}
                isRecording={isRecording}
                isSpeaking={isSpeaking}
                isTtsEnabled={isTtsEnabled}
                onToggleTts={handleToggleTts}
                conversationState={conversationState}
                subjectCode={subjectCode}
                subjectCodes={subjectCodes}
                onAddSubjects={handleAddSubjects}
                onSwitchSubject={handleSwitchSubject}
                isAddingSubjects={isAddingSubjects}
                isSwitchingSubject={isSwitchingSubject}
                subjectFeedback={subjectFeedback}
                subjectFeedbackTone={subjectFeedbackTone}
            />
        </>
    );
};

UI.propTypes = {
    onRobotStateChange: PropTypes.func,
    onLogout: PropTypes.func,
};

export default UI;
