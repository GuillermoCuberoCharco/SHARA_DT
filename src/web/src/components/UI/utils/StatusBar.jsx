import React from "react";
import '../../../styles/StatusBar.css';

const StatusBar = ({ connectionError, isRegistered, isWaitingResponse }) => {
    const getStatusMessage = () => {
        if (connectionError) {
            return { message: "Error de conexión", icon: "⚠️", bgColor: "status-bar-error" };
        }
        if (!isRegistered) {
            return { message: "Conectando al servidor...", icon: "🔄", bgColor: "status-bar-connecting" };
        }
        if (isWaitingResponse) {
            return { message: "Esperando respuesta...", icon: "⏳", bgColor: "status-bar-waiting" };
        }
        return { message: "Listo", icon: "✅", bgColor: "status-bar-ready" };
    };

    const status = getStatusMessage();

    return (
        <div className={`status-bar ${status.bgColor}`}>
            <span className="status-bar-icon">{status.icon}</span>
            <span className="status-bar-message">{status.message}</span>
        </div>
    );
};

export default StatusBar;
