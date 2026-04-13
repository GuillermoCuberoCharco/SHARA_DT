/**
 * Login
 *
 * Full-screen card with two modes: login and register.
 * Calls POST /auth/login or POST /auth/register and stores the JWT token.
 *
 * Props:
 *   onLoginSuccess - called after a successful login or registration
 */

import { useState } from 'react';
import { useAuth } from './useAuth';
import '../styles/Login.css';

const Login = ({ onLoginSuccess }) => {
    const [mode, setMode] = useState('login'); // 'login' | 'register'
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [subjectCodesInput, setSubjectCodesInput] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const { login, register } = useAuth();

    const switchMode = (newMode) => {
        setMode(newMode);
        setError('');
        setPassword('');
        setConfirmPassword('');
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');

        if (mode === 'register' && password !== confirmPassword) {
            setError('Las contrasenas no coinciden');
            return;
        }

        setLoading(true);
        try {
            if (mode === 'login') {
                await login(username.trim(), password, subjectCodesInput.trim());
            } else {
                await register(username.trim(), password, subjectCodesInput.trim());
            }
            onLoginSuccess();
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const isLogin = mode === 'login';
    const canSubmit = username.trim()
        && password
        && subjectCodesInput.trim()
        && (isLogin || confirmPassword)
        && !loading;

    return (
        <div className="login-overlay">
            <div className="login-card">
                <div className="login-avatar">🤖</div>
                <h1 className="login-title">SHARA</h1>
                <p className="login-subtitle">
                    {isLogin ? 'Inicia sesion para continuar' : 'Crea tu cuenta'}
                </p>

                <div className="login-tabs">
                    <button
                        type="button"
                        className={`login-tab ${isLogin ? 'active' : ''}`}
                        onClick={() => switchMode('login')}
                    >
                        Entrar
                    </button>
                    <button
                        type="button"
                        className={`login-tab ${!isLogin ? 'active' : ''}`}
                        onClick={() => switchMode('register')}
                    >
                        Registrarse
                    </button>
                </div>

                <form className="login-form" onSubmit={handleSubmit}>
                    <div className="login-field">
                        <label htmlFor="username">Usuario</label>
                        <input
                            id="username"
                            type="text"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            placeholder="nombre de usuario"
                            autoComplete="username"
                            autoFocus
                            disabled={loading}
                        />
                    </div>

                    <div className="login-field">
                        <label htmlFor="password">Contrasena</label>
                        <input
                            id="password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="********"
                            autoComplete={isLogin ? 'current-password' : 'new-password'}
                            disabled={loading}
                        />
                    </div>

                    <div className="login-field">
                        <label htmlFor="subjectCode">
                            {isLogin ? 'Codigo de asignatura' : 'Codigo/s de asignatura'}
                        </label>
                        <input
                            id="subjectCode"
                            type="text"
                            value={subjectCodesInput}
                            onChange={(e) => setSubjectCodesInput(e.target.value)}
                            placeholder={isLogin ? 'mat101' : 'mat101, mat102'}
                            autoComplete="off"
                            disabled={loading}
                        />
                    </div>

                    {!isLogin && (
                        <div className="login-field">
                            <label htmlFor="confirmPassword">Confirmar contrasena</label>
                            <input
                                id="confirmPassword"
                                type="password"
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                placeholder="********"
                                autoComplete="new-password"
                                disabled={loading}
                            />
                        </div>
                    )}

                    {error && <p className="login-error">{error}</p>}

                    <button
                        type="submit"
                        className="login-btn"
                        disabled={!canSubmit}
                    >
                        {loading
                            ? (isLogin ? 'Entrando...' : 'Registrando...')
                            : (isLogin ? 'Entrar' : 'Crear cuenta')}
                    </button>
                </form>
            </div>
        </div>
    );
};

export default Login;
