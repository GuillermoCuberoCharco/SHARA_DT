import { useEffect, useRef, useState } from "react";
import RobotView from "./components/RobotView";
import SessionLogin from "./components/SessionLogin";
import UI from "./components/UI/UI";
import { WebSocketProvider } from "./contexts/WebSocketContext";

function App() {
  const [sessionIdentity, setSessionIdentity] = useState(null);
  const [sharedStream, setSharedStream] = useState(null);
  const [isStreamReady, setIsStreamReady] = useState(false);
  const [robotState, setRobotState] = useState('neutral');
  const streamRef = useRef(null);

  const webSocketHandlers = {
    handleRegistrationSuccess: () => {
      console.log("Registration successful");
    },
    handleConnectError: (error) => {
      console.error("Connection error:", error);
    }
  };

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
      <RobotView robotState={robotState} />

      {!sessionIdentity && (
        <SessionLogin onLogin={setSessionIdentity} />
      )}

      {/* UI overlay: chat, audio controls, status bar */}
      {sessionIdentity && isStreamReady && (
        <UI
          sharedStream={sharedStream}
          onRobotStateChange={setRobotState}
          sessionIdentity={sessionIdentity}
          onSessionIdentityChange={setSessionIdentity}
        />
      )}
    </WebSocketProvider>
  );
}

export default App;
