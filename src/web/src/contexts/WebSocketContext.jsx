/**
 * Connects the frontend to the authenticated Socket.IO namespace.
 */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { io } from 'socket.io-client';
import { useAuth } from '../auth/useAuth';
import { SERVER_URL } from '../config';

const WebSocketContext = createContext(null);

export const useWebSocketContext = () => {
    const context = useContext(WebSocketContext);
    if (!context) {
        throw new Error('useWebSocketContext must be used within a WebSocketProvider');
    }
    return context;
};

export const WebSocketProvider = ({ children, handlers, onAuthError }) => {
    const [isConnected, setIsConnected] = useState(false);
    const [isRegistered, setIsRegistered] = useState(false);
    const socketRef = useRef(null);
    const handlersRef = useRef(handlers);

    const { getToken } = useAuth();

    useEffect(() => {
        handlersRef.current = handlers;
    }, [handlers]);

    useEffect(() => {
        console.log('[WebSocket] Connecting to:', `${SERVER_URL}/message`);

        if (!socketRef.current) {
            socketRef.current = io(`${SERVER_URL}/message`, {
                auth: { token: getToken() },
                transports: ['websocket', 'polling'],
                reconnectionAttempts: 10,
                reconnectionDelay: 1000,
                timeout: 20000,
                autoConnect: true,
            });
        }

        const socket = socketRef.current;

        const handleConnect = () => {
            console.log('[WebSocket] Connected:', socket.id);
            setIsConnected(true);
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

        const handleRegistrationSuccess = (payload) => {
            console.log('[WebSocket] Registered successfully');
            if (payload?.role) {
                localStorage.setItem('auth_user_role', payload.role);
            }
            if (payload?.subject_code) {
                localStorage.setItem('auth_subject_code', payload.subject_code);
            }
            setIsRegistered(true);
            handlersRef.current?.handleRegistrationSuccess?.(payload);
        };

        const handleConnectError = (error) => {
            console.error('[WebSocket] Connection error:', error.message);
            if (error.message === 'Authentication error' || error.data?.code === 401) {
                onAuthError?.();
            }
            handlersRef.current?.handleConnectError?.(error);
        };

        const handleReconnectAttempt = (attempt) => {
            console.log(`[WebSocket] Reconnecting... attempt ${attempt}`);
        };

        const handleReconnect = () => {
            console.log('[WebSocket] Reconnected');
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
    }, [getToken, onAuthError]);

    const emit = useCallback((event, data) => {
        if (socketRef.current?.connected) {
            socketRef.current.emit(event, data);
            return true;
        }

        console.error('[WebSocket] Cannot emit - not connected');
        return false;
    }, []);

    return (
        <WebSocketContext.Provider
            value={{
                socket: socketRef.current,
                isConnected,
                isRegistered,
                emit,
                id: socketRef.current?.id,
            }}
        >
            {children}
        </WebSocketContext.Provider>
    );
};
