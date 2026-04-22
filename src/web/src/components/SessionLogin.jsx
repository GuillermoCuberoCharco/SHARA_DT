import PropTypes from 'prop-types';
import { useState } from 'react';
import { SERVER_URL } from '../config';
import { buildAuthenticatedSessionIdentity } from '../utils/sessionIdentity';

/**
 * SessionLogin
 *
 * Initial login screen shown before any interaction with Shara.
 *
 * Modes:
 *   login    — existing user enters login name + password
 *   register — new user creates login name + password
 *
 * The loginName is the stable key used for conversation history.
 * It does NOT need to match the name Shara uses — the user can tell Shara
 * their preferred name during the session ("llámame María").
 */

const SessionLogin = ({ onLogin }) => {
    const [mode, setMode] = useState('login');
    const [loginName, setLoginName] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);

    const resetForm = (nextMode) => {
        setMode(nextMode);
        setLoginName('');
        setPassword('');
        setConfirmPassword('');
        setError('');
    };

    const handleLogin = async (event) => {
        event.preventDefault();
        setError('');
        setIsLoading(true);

        try {
            const res = await fetch(`${SERVER_URL}/api/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ loginName: loginName.trim(), password }),
            });
            const data = await res.json();

            if (!res.ok) {
                setError(data.error || 'Error al iniciar sesión');
                return;
            }

            onLogin(buildAuthenticatedSessionIdentity({
                loginName: data.loginName,
                sharaName: data.sharaName,
                isNewUser: false,
            }));
        } catch {
            setError('No se pudo conectar con el servidor');
        } finally {
            setIsLoading(false);
        }
    };

    const handleRegister = async (event) => {
        event.preventDefault();
        setError('');

        if (password !== confirmPassword) {
            setError('Las contraseñas no coinciden');
            return;
        }

        setIsLoading(true);

        try {
            const res = await fetch(`${SERVER_URL}/api/auth/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ loginName: loginName.trim(), password }),
            });
            const data = await res.json();

            if (!res.ok) {
                setError(data.error || 'Error al registrarse');
                return;
            }

            onLogin(buildAuthenticatedSessionIdentity({
                loginName: data.loginName,
                sharaName: data.sharaName,
                isNewUser: true,
            }));
        } catch {
            setError('No se pudo conectar con el servidor');
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="session-login-shell">
            <div className="session-login-card">
                <p className="session-login-kicker">SHARA</p>
                <h1 className="session-login-title">
                    {mode === 'login' ? 'Iniciar sesión' : 'Crear cuenta'}
                </h1>
                <p className="session-login-copy">
                    {mode === 'login'
                        ? 'Entra con tu nombre de usuario y contraseña para retomar la conversación donde la dejaste.'
                        : 'Crea una cuenta nueva. Shara te preguntará tu nombre al comenzar.'}
                </p>

                <form
                    className="session-login-form"
                    onSubmit={mode === 'login' ? handleLogin : handleRegister}
                >
                    <label className="session-login-label" htmlFor="login-name">
                        Nombre de usuario
                    </label>
                    <input
                        id="login-name"
                        className="session-login-input"
                        type="text"
                        value={loginName}
                        onChange={(e) => setLoginName(e.target.value)}
                        placeholder="Ej. Carmen"
                        autoComplete="username"
                        disabled={isLoading}
                    />

                    <label className="session-login-label" htmlFor="login-password" style={{ marginTop: '16px' }}>
                        Contraseña
                    </label>
                    <input
                        id="login-password"
                        className="session-login-input"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="••••••••"
                        autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                        disabled={isLoading}
                    />

                    {mode === 'register' && (
                        <>
                            <label className="session-login-label" htmlFor="login-confirm" style={{ marginTop: '16px' }}>
                                Confirmar contraseña
                            </label>
                            <input
                                id="login-confirm"
                                className="session-login-input"
                                type="password"
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                placeholder="••••••••"
                                autoComplete="new-password"
                                disabled={isLoading}
                            />
                        </>
                    )}

                    {error && (
                        <p className="session-login-error">{error}</p>
                    )}

                    <button
                        className="session-login-button session-login-button-primary"
                        type="submit"
                        disabled={isLoading || !loginName.trim() || !password}
                    >
                        {isLoading
                            ? (mode === 'login' ? 'Entrando...' : 'Registrando...')
                            : (mode === 'login' ? 'Entrar' : 'Crear cuenta y entrar')}
                    </button>
                </form>

                <div className="session-login-divider">
                    <span>{mode === 'login' ? '¿Primera vez?' : '¿Ya tienes cuenta?'}</span>
                </div>

                <button
                    className="session-login-button session-login-button-secondary"
                    type="button"
                    onClick={() => resetForm(mode === 'login' ? 'register' : 'login')}
                    disabled={isLoading}
                >
                    {mode === 'login' ? 'Crear cuenta nueva' : 'Volver al inicio de sesión'}
                </button>
            </div>
        </div>
    );
};

SessionLogin.propTypes = {
    onLogin: PropTypes.func.isRequired,
};

export default SessionLogin;
