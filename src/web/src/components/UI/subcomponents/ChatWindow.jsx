import PropTypes from 'prop-types';
import { useEffect, useRef, useState } from 'react';

const RobotIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect x="5" y="8" width="14" height="11" rx="3" />
        <path d="M12 4v4" />
        <circle cx="9.5" cy="12.5" r="1" fill="currentColor" stroke="none" />
        <circle cx="14.5" cy="12.5" r="1" fill="currentColor" stroke="none" />
        <path d="M9 16h6" />
    </svg>
);

const BubbleIcon = () => (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5c-1.4 0-2.72-.34-3.88-.93L3 21l1.98-5.14A8.46 8.46 0 0 1 3.5 11.5 8.5 8.5 0 1 1 21 11.5Z" />
    </svg>
);

const LogoutIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
        <polyline points="16 17 21 12 16 7" />
        <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
);

const CloseIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
);

const SubjectIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5v13" />
        <path d="M12 8v6" />
        <path d="M9 11h6" />
    </svg>
);

const SendIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="22" y1="2" x2="11" y2="13" />
        <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
);

const MicIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
);

const StopIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
        <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
);

const SpeakerIcon = ({ muted }) => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
        {muted ? (
            <>
                <line x1="23" y1="9" x2="17" y2="15" />
                <line x1="17" y1="9" x2="23" y2="15" />
            </>
        ) : (
            <>
                <path d="M15.5 8.5a5 5 0 0 1 0 7" />
                <path d="M18.5 5.5a9 9 0 0 1 0 13" />
            </>
        )}
    </svg>
);

SpeakerIcon.propTypes = {
    muted: PropTypes.bool,
};

SpeakerIcon.defaultProps = {
    muted: false,
};

const ChatWindow = ({
    messages,
    newMessage,
    onMessageSend,
    onInputChange,
    messagesContainerRef,
    isVisible,
    onClose,
    isWaitingResponse,
    isRegistered,
    connectionError,
    username,
    onLogout,
    onStartRecording,
    onStopRecording,
    isRecording,
    isSpeaking,
    isTtsEnabled,
    onToggleTts,
    conversationState,
    subjectCode,
    subjectCodes,
    onAddSubjects,
    onSwitchSubject,
    isAddingSubjects,
    isSwitchingSubject,
    subjectFeedback,
    subjectFeedbackTone,
    userRole,
    onCreateSubject,
    isCreatingSubject,
}) => {
    const getStatusInfo = () => {
        if (connectionError) return { dot: 'error', label: 'Sin conexion' };
        if (!isRegistered) return { dot: 'connecting', label: 'Conectando...' };
        if (conversationState === 'recording' || isRecording) return { dot: 'recording', label: 'Grabando...' };
        if (isWaitingResponse) return { dot: 'processing', label: 'Procesando...' };
        if (isSpeaking && isTtsEnabled) return { dot: 'speaking', label: 'Hablando...' };
        return { dot: 'connected', label: 'Conectado' };
    };

    const { dot, label } = getStatusInfo();
    const textareaRef = useRef(null);
    const [isSubjectPanelOpen, setIsSubjectPanelOpen] = useState(false);
    const [subjectInput, setSubjectInput] = useState('');
    const [newSubjectInput, setNewSubjectInput] = useState('');
    const [maxStudentsInput, setMaxStudentsInput] = useState('');
    const [shouldRestoreTextareaFocus, setShouldRestoreTextareaFocus] = useState(false);
    const isTeacher = userRole === 'teacher';

    useEffect(() => {
        const element = textareaRef.current;
        if (!element) {
            return;
        }

        element.style.height = 'auto';
        element.style.height = `${element.scrollHeight}px`;
    }, [newMessage]);

    useEffect(() => {
        if (
            !shouldRestoreTextareaFocus
            || !isVisible
            || !isRegistered
            || isWaitingResponse
            || isRecording
        ) {
            return;
        }

        textareaRef.current?.focus({ preventScroll: true });
        setShouldRestoreTextareaFocus(false);
    }, [isRecording, isRegistered, isVisible, isWaitingResponse, shouldRestoreTextareaFocus]);

    const handleSubjectSubmit = async (event) => {
        event.preventDefault();

        if (!onAddSubjects || !subjectInput.trim() || isAddingSubjects || isCreatingSubject) {
            return;
        }

        try {
            await onAddSubjects(subjectInput);
            setSubjectInput('');
        } catch {
            // The parent already exposes the error message in the panel.
        }
    };

    const handleCreateSubjectSubmit = async (event) => {
        event.preventDefault();

        if (!onCreateSubject || !newSubjectInput.trim() || isCreatingSubject || isAddingSubjects) {
            return;
        }

        try {
            const data = await onCreateSubject(newSubjectInput, maxStudentsInput);
            if (data) {
                setNewSubjectInput('');
                setMaxStudentsInput('');
            }
        } catch {
            // The parent already exposes the error message in the panel.
        }
    };

    const handleSend = () => {
        setShouldRestoreTextareaFocus(true);
        onMessageSend();
    };

    return (
        <div className={`chat-panel ${isVisible ? '' : 'hidden'}`}>
            <div className="chat-header">
                <div className="chat-header-brand">
                    <div className="chat-header-avatar">
                        <RobotIcon />
                    </div>
                    <button
                        className={`tts-toggle ${isTtsEnabled ? 'enabled' : 'muted'}`}
                        onClick={onToggleTts}
                        title={isTtsEnabled ? 'Silenciar voz' : 'Activar voz'}
                        type="button"
                    >
                        <SpeakerIcon muted={!isTtsEnabled} />
                    </button>
                </div>
                <div className="chat-header-info">
                    <h3>SHARA</h3>
                    <div className="chat-header-status">
                        <span className={`status-dot ${dot}`} />
                        <span className="status-label">{label}</span>
                    </div>
                </div>
                <div className="chat-header-actions">
                    {username && (
                        <span className="chat-username" title={`Conectado como ${username}`}>
                            {username}
                        </span>
                    )}
                    {onAddSubjects && (
                        <button
                            className={`subject-manager-toggle ${isSubjectPanelOpen ? 'active' : ''}`}
                            onClick={() => setIsSubjectPanelOpen((prev) => !prev)}
                            title="Gestionar asignaturas"
                            type="button"
                        >
                            <SubjectIcon />
                        </button>
                    )}
                    {onLogout && (
                        <button className="chat-logout-btn" onClick={onLogout} title="Cerrar sesion" type="button">
                            <LogoutIcon />
                        </button>
                    )}
                    <button className="chat-close-btn" onClick={onClose} title="Cerrar chat" type="button">
                        <CloseIcon />
                    </button>
                </div>
            </div>

            {onAddSubjects && isSubjectPanelOpen && (
                <div className="subject-manager-panel">
                    <div className="subject-manager-header">
                        <div>
                            <p className="subject-manager-title">Asignaturas vinculadas</p>
                            <p className="subject-manager-note">
                                Activa ahora: <span>{subjectCode || 'sin asignatura'}</span>
                            </p>
                        </div>
                        <div className="subject-chip-list">
                            {subjectCodes.map((code) => (
                                <button
                                    key={code}
                                    type="button"
                                    className={`subject-chip ${code === subjectCode ? 'active' : ''}`}
                                    onClick={() => onSwitchSubject?.(code)}
                                    disabled={
                                        !onSwitchSubject
                                        || code === subjectCode
                                        || isSwitchingSubject
                                        || isAddingSubjects
                                        || isCreatingSubject
                                        || !isRegistered
                                        || isWaitingResponse
                                        || isRecording
                                    }
                                >
                                    {code}
                                </button>
                            ))}
                        </div>
                    </div>

                    <form className="subject-manager-form" onSubmit={handleSubjectSubmit}>
                        <input
                            type="text"
                            value={subjectInput}
                            onChange={(event) => setSubjectInput(event.target.value)}
                            placeholder="codigo existente"
                            autoComplete="off"
                            disabled={isAddingSubjects || isCreatingSubject || isSwitchingSubject}
                        />
                        <button
                            type="submit"
                            disabled={!subjectInput.trim() || isAddingSubjects || isCreatingSubject || isSwitchingSubject}
                        >
                            {isAddingSubjects ? 'Vinculando...' : 'Vincular'}
                        </button>
                    </form>

                    {isTeacher && onCreateSubject && (
                        <form className="subject-manager-form subject-create-form" onSubmit={handleCreateSubjectSubmit}>
                            <input
                                type="text"
                                value={newSubjectInput}
                                onChange={(event) => setNewSubjectInput(event.target.value)}
                                placeholder="nueva asignatura"
                                autoComplete="off"
                                disabled={isAddingSubjects || isCreatingSubject || isSwitchingSubject}
                            />
                            <input
                                type="number"
                                min="1"
                                step="1"
                                value={maxStudentsInput}
                                onChange={(event) => setMaxStudentsInput(event.target.value)}
                                placeholder="limite"
                                autoComplete="off"
                                disabled={isAddingSubjects || isCreatingSubject || isSwitchingSubject}
                            />
                            <button
                                type="submit"
                                disabled={!newSubjectInput.trim() || isAddingSubjects || isCreatingSubject || isSwitchingSubject}
                            >
                                {isCreatingSubject ? 'Creando...' : 'Crear'}
                            </button>
                        </form>
                    )}

                    <p className={`subject-manager-help ${subjectFeedbackTone}`}>
                        {subjectFeedback || 'Pulsa una asignatura para cambiar de contexto o vincula un codigo existente.'}
                    </p>
                </div>
            )}

            <div className="messages-container" ref={messagesContainerRef}>
                {messages.length === 0 && (
                    <div className="chat-empty">
                        <span className="chat-empty-icon">
                            <BubbleIcon />
                        </span>
                        <p>Hola, soy SHARA.<br />En que puedo ayudarte hoy?</p>
                    </div>
                )}

                {messages.map((message, index) => (
                    <div key={index} className={`message-row ${message.sender}`}>
                        {message.sender === 'robot' && (
                            <div className="message-avatar">
                                <RobotIcon />
                            </div>
                        )}
                        <div className="message-bubble">{message.text}</div>
                    </div>
                ))}

                {isWaitingResponse && !isRecording && (
                    <div className="typing-row">
                        <div className="message-avatar">
                            <RobotIcon />
                        </div>
                        <div className="typing-bubble">
                            <span className="typing-dot" />
                            <span className="typing-dot" />
                            <span className="typing-dot" />
                        </div>
                    </div>
                )}
            </div>

            <div className="input-area">
                <button
                    className={`audio-btn ${isRecording ? 'recording' : ''}`}
                    onClick={isRecording ? onStopRecording : onStartRecording}
                    disabled={!isRegistered || isWaitingResponse}
                    title={isRecording ? 'Detener grabacion' : 'Grabar audio'}
                    type="button"
                >
                    {isRecording ? <StopIcon /> : <MicIcon />}
                </button>
                <textarea
                    value={newMessage}
                    onChange={onInputChange}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' && !event.shiftKey) {
                            event.preventDefault();
                            handleSend();
                        }
                    }}
                    ref={textareaRef}
                    placeholder={isRecording ? 'Grabando audio...' : 'Escribe un mensaje...'}
                    rows={1}
                    disabled={!isRegistered || isWaitingResponse || isRecording}
                />
                <button
                    className="send-btn"
                    onClick={handleSend}
                    disabled={!newMessage.trim() || !isRegistered || isWaitingResponse || isRecording}
                    title="Enviar"
                    type="button"
                >
                    <SendIcon />
                </button>
            </div>
            <div className="input-hint">
                {isRecording
                    ? 'Pulsa otra vez para detener la grabacion o espera al silencio.'
                    : 'Intro para enviar - Mayus+Intro para nueva linea'}
            </div>
        </div>
    );
};

ChatWindow.propTypes = {
    messages: PropTypes.arrayOf(PropTypes.shape({
        text: PropTypes.string,
        sender: PropTypes.string,
    })).isRequired,
    newMessage: PropTypes.string.isRequired,
    onMessageSend: PropTypes.func.isRequired,
    onInputChange: PropTypes.func.isRequired,
    messagesContainerRef: PropTypes.object,
    isVisible: PropTypes.bool,
    onClose: PropTypes.func,
    isWaitingResponse: PropTypes.bool,
    isRegistered: PropTypes.bool,
    connectionError: PropTypes.bool,
    username: PropTypes.string,
    onLogout: PropTypes.func,
    onStartRecording: PropTypes.func.isRequired,
    onStopRecording: PropTypes.func.isRequired,
    isRecording: PropTypes.bool,
    isSpeaking: PropTypes.bool,
    isTtsEnabled: PropTypes.bool,
    onToggleTts: PropTypes.func.isRequired,
    conversationState: PropTypes.string,
    subjectCode: PropTypes.string,
    subjectCodes: PropTypes.arrayOf(PropTypes.string),
    userRole: PropTypes.string,
    onAddSubjects: PropTypes.func,
    onCreateSubject: PropTypes.func,
    onSwitchSubject: PropTypes.func,
    isAddingSubjects: PropTypes.bool,
    isCreatingSubject: PropTypes.bool,
    isSwitchingSubject: PropTypes.bool,
    subjectFeedback: PropTypes.string,
    subjectFeedbackTone: PropTypes.string,
};

ChatWindow.defaultProps = {
    messagesContainerRef: null,
    isVisible: true,
    onClose: null,
    isWaitingResponse: false,
    isRegistered: false,
    connectionError: false,
    username: '',
    onLogout: null,
    isRecording: false,
    isSpeaking: false,
    isTtsEnabled: true,
    conversationState: 'idle',
    subjectCode: '',
    subjectCodes: [],
    userRole: 'student',
    onAddSubjects: null,
    onCreateSubject: null,
    onSwitchSubject: null,
    isAddingSubjects: false,
    isCreatingSubject: false,
    isSwitchingSubject: false,
    subjectFeedback: '',
    subjectFeedbackTone: 'info',
};

export default ChatWindow;
