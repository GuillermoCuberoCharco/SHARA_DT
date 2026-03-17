/**
 * WebSocketContext
 *
 * Connects to the Flask-SocketIO server /message namespace.
 *
 * Migration note (Node.js → Flask):
 *   Before: io(SERVER_URL, { path: '/message-socket' })
 *   After:  io(SERVER_URL + '/message')   ← Socket.IO namespace syntax
 *
 * The namespace approach is idiomatic for Flask-SocketIO and requires
 * no path configuration — the namespace is part of the URL.
 */

import { createContext, useContext, useEffect, useRef, useState } from "react";
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

export const WebSocketProvider = ({ children, handlers }) => {
    const [isConnected, setIsConnected] = useState(false);
    const [isRegistered, setIsRegistered] = useState(false);
    const socketRef = useRef(null);
    const handlersRef = useRef(handlers);

    useEffect(() => {
        handlersRef.current = handlers;
    }, [handlers]);

    useEffect(() => {
        console.log('[WebSocket] Connecting to:', SERVER_URL + '/message');

        if (!socketRef.current) {
            // Flask-SocketIO namespace: SERVER_URL + '/message'
            const newSocket = io(`${SERVER_URL}/message`, {
                transports: ['websocket', 'polling'],
                reconnectionAttempts: 10,
                reconnectionDelay: 1000,
                timeout: 20000,
                autoConnect: true,
            });
            socketRef.current = newSocket;
        }

        const socket = socketRef.current;

        const handleConnect = () => {
            console.log('[WebSocket] Connected:', socket.id);
            setIsConnected(true);
            socket.emit('register_client', { client: 'web' });
        };

        const handleDisconnect = (reason) => {
            console.log('[WebSocket] Disconnected:', reason);
            setIsConnected(false);
            setIsRegistered(false);

            setTimeout(() => {
                if (socketRef.current && !socket.connected) {
                    socket.connect();
                }
            }, 1000);
        };

        const handleRegistrationSuccess = () => {
            console.log('[WebSocket] Registered successfully');
            setIsRegistered(true);
            handlersRef.current?.handleRegistrationSuccess?.();
        };

        const handleConnectError = (error) => {
            console.error('[WebSocket] Connection error:', error);
            handlersRef.current?.handleConnectError?.(error);
        };

        const handleReconnectAttempt = (attempt) => {
            console.log(`[WebSocket] Reconnecting... attempt ${attempt}`);
        };

        const handleReconnect = () => {
            console.log('[WebSocket] Reconnected');
            socket.emit('register_client', { client: 'web' });
        };

        const handleError = (error) => {
            console.error('[WebSocket] Error:', error);
        };

        socket.on('connect', handleConnect);
        socket.on('disconnect', handleDisconnect);
        socket.on('registration_success', handleRegistrationSuccess);
        socket.on('connect_error', handleConnectError);
        socket.on('reconnect_attempt', handleReconnectAttempt);
        socket.on('reconnect', handleReconnect);
        socket.on('error', handleError);

        return () => {
            socket.off('connect', handleConnect);
            socket.off('disconnect', handleDisconnect);
            socket.off('registration_success', handleRegistrationSuccess);
            socket.off('connect_error', handleConnectError);
            socket.off('reconnect_attempt', handleReconnectAttempt);
            socket.off('reconnect', handleReconnect);
            socket.off('error', handleError);
        };
    }, []);

    const emit = (event, data) => {
        if (socketRef.current?.connected) {
            socketRef.current.emit(event, data);
            return true;
        }
        console.error('[WebSocket] Cannot emit — not connected');
        return false;
    };

    return (
        <WebSocketContext.Provider value={{
            socket: socketRef.current,
            isConnected,
            isRegistered,
            emit,
            id: socketRef.current?.id,
        }}>
            {children}
        </WebSocketContext.Provider>
    );
};
