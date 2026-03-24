/**
 * useAuth
 *
 * Auth state utilities backed by localStorage.
 * Token and user_id are persisted across page reloads.
 */

import { SERVER_URL } from '../config';

export const useAuth = () => {
    const getToken = () => localStorage.getItem('auth_token');
    const getUserId = () => localStorage.getItem('auth_user_id');
    const isAuthenticated = () => !!getToken();

    const _storeSession = (data) => {
        localStorage.setItem('auth_token', data.token);
        localStorage.setItem('auth_user_id', data.user_id);
    };

    const login = async (username, password) => {
        const res = await fetch(`${SERVER_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al iniciar sesión');
        _storeSession(data);
        return data;
    };

    const register = async (username, password) => {
        const res = await fetch(`${SERVER_URL}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al registrarse');
        _storeSession(data);
        return data;
    };

    const logout = () => {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_user_id');
    };

    return { getToken, getUserId, isAuthenticated, login, register, logout };
};
