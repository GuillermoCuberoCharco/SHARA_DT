import PropTypes from 'prop-types';

const AudioControls = ({
    isRecording,
    isSpeaking,
    isWaitingResponse,
    onStartRecording,
    onStopRecording
}) => (
    <div className="audio-controls">
        <button
            onClick={isRecording ? onStopRecording : onStartRecording}
            disabled={isSpeaking || isWaitingResponse}
            className={`record-button ${isRecording ? 'recording' : ''}`}
        >
            {isRecording ? "⏹ Detener grabación" : "⏺ Iniciar grabación"}
        </button>
    </div>
);

AudioControls.propTypes = {
    isRecording: PropTypes.bool.isRequired,
    isSpeaking: PropTypes.bool.isRequired,
    isWaitingResponse: PropTypes.bool.isRequired,
    onStartRecording: PropTypes.func.isRequired,
    onStopRecording: PropTypes.func.isRequired
};

export default AudioControls;