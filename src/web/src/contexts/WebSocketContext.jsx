/**
 * WebSocketContext
 *
 * Connects to the Flask-SocketIO server /message namespace.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { io } from "socket.io-client";
import { SERVER_URL } from "../config";

const WebSocketContext = createContext(null);

export const useWebSocketContext = () => {
    const context = useContext(WebSocketContext);
    if (!context) {
        throw new Error("useWebSocketContext must be used within a WebSocketProvider");
    }
    return context;
};

export const WebSocketProvider = ({ children, handlers, sessionId }) => {
    const [isConnected, setIsConnected] = useState(false);
    const [isRegistered, setIsRegistered] = useState(false);
    const [connectionError, setConnectionError] = useState(false);
    const socketRef = useRef(null);
    const handlersRef = useRef(handlers);

    useEffect(() => {
        handlersRef.current = handlers;
    }, [handlers]);

    useEffect(() => {
        if (!sessionId) return;
        const socket = io(`${SERVER_URL}/message`, {
            withCredentials: true,
            transports: ['polling', 'websocket'],
            autoConnect: false,
        });
        socketRef.current = socket;

        const handleConnect = () => {
            console.log('[WebSocket] Connected:', socket.id);
            setIsConnected(true);
            setConnectionError(false);
            socket.emit('register_client', { client: 'web' });
        };

        const handleDisconnect = (reason) => {
            console.log('[WebSocket] Disconnected:', reason);
            setIsConnected(false);
            setIsRegistered(false);
            setConnectionError(true);
        };

        const handleRegistrationSuccess = () => {
            console.log('[WebSocket] Registered successfully');
            setIsRegistered(true);
            handlersRef.current?.handleRegistrationSuccess?.();
        };

        const handleConnectError = (error) => {
            console.error('[WebSocket] Connection error:', error);
            setConnectionError(true);
            handlersRef.current?.handleConnectError?.(error);
        };

        const handleError = (error) => {
            console.error('[WebSocket] Error:', error);
        };

        socket.on('connect', handleConnect);
        socket.on('disconnect', handleDisconnect);
        socket.on('registration_success', handleRegistrationSuccess);
        socket.on('connect_error', handleConnectError);
        socket.on('error', handleError);

        socket.connect();
        return () => {
            socket.off('connect', handleConnect);
            socket.off('disconnect', handleDisconnect);
            socket.off('registration_success', handleRegistrationSuccess);
            socket.off('connect_error', handleConnectError);
            socket.off('error', handleError);
            socket.disconnect();
            socketRef.current = null;
            setConnectionError(false);
            setIsConnected(false);
            setIsRegistered(false);
        };
    }, [sessionId]);

    const emit = useCallback((event, data) => {
        if (socketRef.current?.connected) {
            socketRef.current.emit(event, data);
            return true;
        }
        console.error('[WebSocket] Cannot emit — not connected');
        return false;
    }, []);

    const value = useMemo(() => ({
        socket: socketRef.current,
        isConnected,
        isRegistered,
        connectionError,
        emit,
        id: socketRef.current?.id,
    }), [emit, isConnected, isRegistered, connectionError]);

    return (
        <WebSocketContext.Provider value={value}>
            {children}
        </WebSocketContext.Provider>
    );
};
