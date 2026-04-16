import PropTypes from 'prop-types';
import { useState } from 'react';
import { buildSessionIdentity } from '../utils/sessionIdentity';

const SessionLogin = ({ onLogin }) => {
    const [knownUsername, setKnownUsername] = useState('');

    const handleKnownUserSubmit = (event) => {
        event.preventDefault();
        const cleanUsername = knownUsername.trim();
        if (!cleanUsername) {
            return;
        }

        onLogin(buildSessionIdentity({
            username: cleanUsername,
            isNewUser: false,
            needsIdentification: false,
            userStatus: 'existing',
        }));
    };

    const handleUnknownUserStart = () => {
        onLogin(buildSessionIdentity({
            username: 'unknown',
            isNewUser: true,
            needsIdentification: true,
            userStatus: 'new_unknown',
        }));
    };

    return (
        <div className="session-login-shell">
            <div className="session-login-card">
                <p className="session-login-kicker">SHARA</p>
                <h1 className="session-login-title">Inicia la sesión del estudio</h1>
                <p className="session-login-copy">
                    Usa un nombre conocido para recuperar su historial o entra como usuario nuevo
                    para que Shara le pregunte quién es al comenzar.
                </p>

                <form className="session-login-form" onSubmit={handleKnownUserSubmit}>
                    <label className="session-login-label" htmlFor="known-username">
                        Usuario conocido
                    </label>
                    <input
                        id="known-username"
                        className="session-login-input"
                        type="text"
                        value={knownUsername}
                        onChange={(event) => setKnownUsername(event.target.value)}
                        placeholder="Ej. Carmen"
                        autoComplete="off"
                    />
                    <button
                        className="session-login-button session-login-button-primary"
                        type="submit"
                        disabled={!knownUsername.trim()}
                    >
                        Entrar con este usuario
                    </button>
                </form>

                <div className="session-login-divider">
                    <span>o</span>
                </div>

                <button
                    className="session-login-button session-login-button-secondary"
                    type="button"
                    onClick={handleUnknownUserStart}
                >
                    Entrar como usuario nuevo
                </button>
            </div>
        </div>
    );
};

SessionLogin.propTypes = {
    onLogin: PropTypes.func.isRequired,
};

export default SessionLogin;
