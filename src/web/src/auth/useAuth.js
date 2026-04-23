/**
 * useAuth
 *
 * Auth state utilities backed by localStorage.
 * Token and user session data are persisted across page reloads.
 */

import { SERVER_URL } from '../config';

export const useAuth = () => {
    const getToken = () => localStorage.getItem('auth_token');
    const getUserId = () => localStorage.getItem('auth_user_id');
    const getUserRole = () => localStorage.getItem('auth_user_role') || 'student';
    const getSubjectCode = () => localStorage.getItem('auth_subject_code') || '';
    const getSubjectCodes = () => {
        try {
            const rawValue = localStorage.getItem('auth_subject_codes');
            const parsedValue = rawValue ? JSON.parse(rawValue) : [];
            return Array.isArray(parsedValue) ? parsedValue : [];
        } catch {
            return [];
        }
    };
    const isAuthenticated = () => !!getToken();

    const _storeSession = (data) => {
        if (data.token) {
            localStorage.setItem('auth_token', data.token);
        }
        if (data.user_id) {
            localStorage.setItem('auth_user_id', data.user_id);
        }
        localStorage.setItem('auth_user_role', data.role || 'student');
        localStorage.setItem('auth_subject_code', data.subject_code || '');
        localStorage.setItem('auth_subject_codes', JSON.stringify(data.subject_codes || []));
    };

    const login = async (username, password, subjectCode) => {
        const res = await fetch(`${SERVER_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, subject_code: subjectCode }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al iniciar sesion');
        _storeSession(data);
        return data;
    };

    const register = async (username, password, subjectCodes) => {
        const res = await fetch(`${SERVER_URL}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, subject_codes: subjectCodes }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al registrarse');
        _storeSession(data);
        return data;
    };

    const addSubjects = async (subjectCodes) => {
        const token = getToken();
        if (!token) {
            throw new Error('Sesion no valida');
        }

        const res = await fetch(`${SERVER_URL}/auth/subjects`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ subject_codes: subjectCodes }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al vincular asignaturas');
        _storeSession(data);
        return data;
    };

    const createSubject = async (subjectCode, maxStudents) => {
        const token = getToken();
        if (!token) {
            throw new Error('Sesion no valida');
        }

        const res = await fetch(`${SERVER_URL}/auth/teacher/subjects`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
                subject_code: subjectCode,
                max_students: maxStudents,
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al crear la asignatura');
        _storeSession(data);
        return data;
    };

    const switchSubject = async (subjectCode) => {
        const token = getToken();
        if (!token) {
            throw new Error('Sesion no valida');
        }

        const res = await fetch(`${SERVER_URL}/auth/switch-subject`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ subject_code: subjectCode }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al cambiar de asignatura');
        _storeSession(data);
        return data;
    };

    const logout = () => {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_user_id');
        localStorage.removeItem('auth_user_role');
        localStorage.removeItem('auth_subject_code');
        localStorage.removeItem('auth_subject_codes');
    };

    return {
        getToken,
        getUserId,
        getUserRole,
        getSubjectCode,
        getSubjectCodes,
        isAuthenticated,
        login,
        register,
        addSubjects,
        createSubject,
        switchSubject,
        logout,
    };
};
