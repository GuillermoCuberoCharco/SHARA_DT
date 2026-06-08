import { useEffect, useRef, useState } from "react";
import RobotView from "./components/RobotView";
import SessionLogin from "./components/SessionLogin";
import UI from "./components/UI/UI";
import { WebSocketProvider } from "./contexts/WebSocketContext";
import { SERVER_URL } from "./config";
import {
  installAudioUnlockListeners,
  isAudioPlaybackUnlocked,
  subscribeAudioPlaybackUnlock,
  unlockAudioPlayback,
} from "./utils/audioPlayback";
import { buildAuthenticatedSessionIdentity } from "./utils/sessionIdentity";

function App() {
  const [sessionIdentity, setSessionIdentity] = useState(null);
  const [isAuthResolved, setIsAuthResolved] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [sharedStream, setSharedStream] = useState(null);
  const [isStreamReady, setIsStreamReady] = useState(false);
  const [robotState, setRobotState] = useState('neutral');
  const [isAudioReady, setIsAudioReady] = useState(() => isAudioPlaybackUnlocked());
  const [isUnlockingAudio, setIsUnlockingAudio] = useState(false);
  const [audioUnlockError, setAudioUnlockError] = useState('');
  const streamRef = useRef(null);
  const sessionIdentityRef = useRef(null);

  const webSocketHandlers = {
    handleRegistrationSuccess: () => {
      console.log("Registration successful");
    },
    handleConnectError: (error) => {
      console.error("Connection error:", error);
    }
  };

  useEffect(() => {
    return installAudioUnlockListeners();
  }, []);

  useEffect(() => {
    return subscribeAudioPlaybackUnlock(setIsAudioReady);
  }, []);

  useEffect(() => {
    sessionIdentityRef.current = sessionIdentity;
  }, [sessionIdentity]);

  useEffect(() => {
    let isMounted = true;

    const restoreSession = async () => {
      try {
        const res = await fetch(`${SERVER_URL}/api/auth/me`, {
          method: 'GET',
          cache: 'no-store',
          credentials: 'include',
        });

        if (!isMounted) {
          return;
        }

        if (res.ok) {
          const data = await res.json();
          setSessionIdentity(buildAuthenticatedSessionIdentity({
            loginName: data.loginName,
            sharaName: data.sharaName,
            isNewUser: false,
          }));
          return;
        }

        if (res.status !== 401) {
          console.error('Unable to restore session:', res.status);
        }
      } catch (error) {
        if (isMounted) {
          console.error('Unable to restore session:', error);
        }
      } finally {
        if (isMounted) {
          setIsAuthResolved(true);
        }
      }
    };

    restoreSession();

    return () => {
      isMounted = false;
    };
  }, []);

  const handleLogout = async () => {
    setIsLoggingOut(true);

    try {
      const res = await fetch(`${SERVER_URL}/api/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          sessionId: sessionIdentity?.sessionId || null,
          loginName: sessionIdentity?.loginName || null,
        }),
      });

      let data = null;
      try {
        data = await res.json();
      } catch {
        data = null;
      }

      if (!res.ok) {
        throw new Error(data?.error || 'No se pudo cerrar la sesion');
      }

      setSessionIdentity(null);
      setRobotState('neutral');
      return true;
    } catch (error) {
      console.error('Unable to logout:', error);
      throw error;
    } finally {
      setIsLoggingOut(false);
    }
  };

  const handleBeginInteraction = async () => {
    setIsUnlockingAudio(true);
    setAudioUnlockError('');

    try {
      const unlocked = await unlockAudioPlayback();
      if (!unlocked) {
        throw new Error('No se pudo activar el audio');
      }

      setIsAudioReady(true);
    } catch (error) {
      console.error('Unable to unlock audio:', error);
      setAudioUnlockError('No se pudo activar el audio. Toca de nuevo para intentarlo.');
    } finally {
      setIsUnlockingAudio(false);
    }
  };

  useEffect(() => {
    const flushSessionOnPageHide = () => {
      const currentSessionIdentity = sessionIdentityRef.current;
      if (!currentSessionIdentity?.sessionId || !currentSessionIdentity?.loginName) {
        return;
      }

      const flushUrl = `${SERVER_URL}/api/session/flush`;
      const payload = JSON.stringify({
        sessionId: currentSessionIdentity.sessionId,
        loginName: currentSessionIdentity.loginName,
      });

      if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
        const beacon = new Blob([payload], { type: 'application/json' });
        if (navigator.sendBeacon(flushUrl, beacon)) {
          return;
        }
      }

      fetch(flushUrl, {
        method: 'POST',
        keepalive: true,
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
      }).catch(() => {});
    };

    window.addEventListener('pagehide', flushSessionOnPageHide);

    return () => {
      window.removeEventListener('pagehide', flushSessionOnPageHide);
    };
  }, []);

  useEffect(() => {
    if (!sessionIdentity?.sessionId) {
      setSharedStream(null);
      setIsStreamReady(false);
      return undefined;
    }

    let isMounted = true;

    const initializeCamera = async () => {
      try {
        if (typeof navigator.mediaDevices === 'undefined' || !navigator.mediaDevices.getUserMedia) {
          console.log("MediaDevices API not available");
          return;
        }

        const devices = await navigator.mediaDevices.enumerateDevices();
        const hasCamera = devices.some(device => device.kind === 'videoinput');

        if (!hasCamera) {
          console.log("No camera devices found");
          return;
        }

        const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        if (!isMounted) {
          stream.getTracks().forEach(track => track.stop());
          return;
        }

        console.log("Camera stream ready");
        streamRef.current = stream;
        setSharedStream(stream);
      } catch (error) {
        console.log("Proceeding without camera:", error?.message || error);
        setSharedStream(null);
      } finally {
        if (isMounted) {
          setIsStreamReady(true);
        }
      }
    };

    initializeCamera();

    return () => {
      isMounted = false;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
        streamRef.current = null;
      }
    };
  }, [sessionIdentity?.sessionId]);

  return (
    <WebSocketProvider handlers={webSocketHandlers}>
      {/* Full-screen robot image with eye animation overlay */}
      <RobotView robotState={robotState} sessionIdentity={sessionIdentity} />

      {!isAuthResolved && (
        <div className="session-login-shell">
          <div className="session-login-card session-restore-card">
            <p className="session-login-kicker">SHARA</p>
            <h1 className="session-login-title">Recuperando sesion</h1>
            <p className="session-login-copy">
              Comprobando si ya hay una sesion guardada en este navegador.
            </p>
          </div>
        </div>
      )}

      {isAuthResolved && !sessionIdentity && (
        <SessionLogin onLogin={setSessionIdentity} />
      )}

      {isAuthResolved && sessionIdentity && !isAudioReady && (
        <div className="session-login-shell">
          <div className="session-login-card session-restore-card">
            <p className="session-login-kicker">SHARA</p>
            <h1 className="session-login-title">Toca para empezar</h1>
            <p className="session-login-copy">
              Así SHARA puede saludarte con voz antes de escuchar.
            </p>
            <button
              className="session-login-button session-login-button-primary"
              type="button"
              onClick={handleBeginInteraction}
              disabled={isUnlockingAudio}
            >
              {isUnlockingAudio ? 'Activando...' : 'Empezar'}
            </button>
            {audioUnlockError && (
              <p className="session-login-error">{audioUnlockError}</p>
            )}
          </div>
        </div>
      )}

      {/* UI overlay: chat, audio controls, status bar */}
      {isAuthResolved && sessionIdentity && isStreamReady && isAudioReady && (
        <UI
          sharedStream={sharedStream}
          onRobotStateChange={setRobotState}
          sessionIdentity={sessionIdentity}
          onSessionIdentityChange={setSessionIdentity}
          onLogout={handleLogout}
          isLoggingOut={isLoggingOut}
        />
      )}
    </WebSocketProvider>
  );
}

export default App;
