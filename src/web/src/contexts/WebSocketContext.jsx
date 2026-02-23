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

    useEffect(() => {
        console.log('[WebSocket] Connecting to:', SERVER_URL + '/message');

        if (!socketRef.current || !socketRef.current.connected) {
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
        socket.removeAllListeners();

        socket.on('connect', () => {
            console.log('[WebSocket] Connected:', socket.id);
            setIsConnected(true);
            socket.emit('register_client', { client: 'web' });
        });

        socket.on('disconnect', (reason) => {
            console.log('[WebSocket] Disconnected:', reason);
            setIsConnected(false);
            setIsRegistered(false);

            setTimeout(() => {
                if (socketRef.current && !socket.connected) {
                    socket.connect();
                }
            }, 1000);
        });

        socket.on('registration_success', () => {
            console.log('[WebSocket] Registered successfully');
            setIsRegistered(true);
            handlers?.handleRegistrationSuccess?.();
        });

        socket.on('connect_error', (error) => {
            console.error('[WebSocket] Connection error:', error);
            handlers?.handleConnectError?.(error);
        });

        socket.on('reconnect_attempt', (attempt) => {
            console.log(`[WebSocket] Reconnecting... attempt ${attempt}`);
        });

        socket.on('reconnect', () => {
            console.log('[WebSocket] Reconnected');
            socket.emit('register_client', { client: 'web' });
        });

        socket.on('error', (error) => {
            console.error('[WebSocket] Error:', error);
        });

        return () => {
            socket.removeAllListeners();
        };
    }, [handlers]);

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