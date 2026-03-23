import PropTypes from 'prop-types';

const SendIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="22" y1="2" x2="11" y2="13" />
        <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
);

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
}) => {
    const getStatusInfo = () => {
        if (connectionError)    return { dot: 'error',      label: 'Sin conexión' };
        if (!isRegistered)      return { dot: 'connecting', label: 'Conectando...' };
        if (isWaitingResponse)  return { dot: 'processing', label: 'Procesando...' };
        return                         { dot: 'connected',  label: 'Conectado' };
    };

    const { dot, label } = getStatusInfo();

    return (
        <div className={`chat-panel ${isVisible ? '' : 'hidden'}`}>

            {/* Header */}
            <div className="chat-header">
                <div className="chat-header-avatar">🤖</div>
                <div className="chat-header-info">
                    <h3>SHARA</h3>
                    <div className="chat-header-status">
                        <span className={`status-dot ${dot}`} />
                        <span className="status-label">{label}</span>
                    </div>
                </div>
                <button className="chat-close-btn" onClick={onClose} title="Cerrar chat">✕</button>
            </div>

            {/* Mensajes */}
            <div className="messages-container" ref={messagesContainerRef}>
                {messages.length === 0 && (
                    <div className="chat-empty">
                        <span className="chat-empty-icon">💬</span>
                        <p>Hola, soy SHARA.<br />¿En qué puedo ayudarte hoy?</p>
                    </div>
                )}

                {messages.map((message, index) => (
                    <div key={index} className={`message-row ${message.sender}`}>
                        {message.sender === 'robot' && (
                            <div className="message-avatar">🤖</div>
                        )}
                        <div className="message-bubble">{message.text}</div>
                    </div>
                ))}

                {isWaitingResponse && (
                    <div className="typing-row">
                        <div className="message-avatar">🤖</div>
                        <div className="typing-bubble">
                            <span className="typing-dot" />
                            <span className="typing-dot" />
                            <span className="typing-dot" />
                        </div>
                    </div>
                )}
            </div>

            {/* Input */}
            <div className="input-area">
                <textarea
                    value={newMessage}
                    onChange={onInputChange}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            onMessageSend();
                        }
                    }}
                    placeholder="Escribe un mensaje..."
                    rows={1}
                    disabled={!isRegistered || isWaitingResponse}
                />
                <button
                    className="send-btn"
                    onClick={onMessageSend}
                    disabled={!newMessage.trim() || !isRegistered || isWaitingResponse}
                    title="Enviar (Enter)"
                >
                    <SendIcon />
                </button>
            </div>
            <div className="input-hint">Intro para enviar · Mayús+Intro para nueva línea</div>
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
};

export default ChatWindow;
