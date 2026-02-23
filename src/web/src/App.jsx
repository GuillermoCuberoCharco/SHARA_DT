import { useEffect, useRef, useState } from "react";
import RobotView from "./components/RobotView";
import UI from "./components/UI/UI";
import WebSocketVideoComponent from "./components/WebSocketVideo";
import { WebSocketProvider } from "./contexts/WebSocketContext";

function App() {
  const [sharedStream, setSharedStream] = useState(null);
  const [isStreamReady, setIsStreamReady] = useState(false);
  const [robotState, setRobotState] = useState('neutral');

  const videoTimeoutRef = useRef(null);
  const VIDEO_TIMEOUT = 10000;

  const webSocketHandlers = {
    handleRegistrationSuccess: () => {
      console.log("Registration successful");
    },
    handleConnectError: (error) => {
      console.error("Connection error:", error);
    }
  };

  const handleStreamReady = (stream) => {
    if (videoTimeoutRef.current) {
      clearTimeout(videoTimeoutRef.current);
      videoTimeoutRef.current = null;
    }

    if (stream) {
      console.log("Stream ready - camera available");
      setSharedStream(stream);
    } else {
      console.log("No stream available - proceeding without camera");
      setSharedStream(null);
    }
    setIsStreamReady(true);
  };

  const handleStreamError = (error) => {
    console.error("Stream error, proceeding without camera:", error);

    if (videoTimeoutRef.current) {
      clearTimeout(videoTimeoutRef.current);
      videoTimeoutRef.current = null;
    }

    setIsStreamReady(true);
  };

  useEffect(() => {
    const initializeApp = async () => {
      try {
        if (typeof navigator.mediaDevices === 'undefined') {
          console.log("MediaDevices API not available");
          setIsStreamReady(true);
          return;
        }

        const devices = await navigator.mediaDevices.enumerateDevices();
        const hasCamera = devices.some(device => device.kind === 'videoinput');

        if (!hasCamera) {
          console.log("No camera devices found");
          setIsStreamReady(true);
          return;
        }

        try {
          const testStream = await navigator.mediaDevices.getUserMedia({
            video: { width: 1, height: 1 },
            audio: false
          });
          testStream.getTracks().forEach(track => track.stop());
          console.log("Camera access test successful");

          videoTimeoutRef.current = setTimeout(() => {
            console.log("Video services timeout reached");
            setIsStreamReady(true);
          }, VIDEO_TIMEOUT);

        } catch (cameraError) {
          console.log("Camera access denied:", cameraError.message);
          setIsStreamReady(true);
        }

      } catch (error) {
        console.log("Initialization error:", error);
        setIsStreamReady(true);
      }
    };

    initializeApp();

    return () => {
      if (videoTimeoutRef.current) {
        clearTimeout(videoTimeoutRef.current);
      }
    };
  }, []);

  return (
    <WebSocketProvider handlers={webSocketHandlers}>
      {/* Full-screen robot image with eye animation overlay */}
      <RobotView robotState={robotState} />

      {/* Camera stream for face detection */}
      <WebSocketVideoComponent
        onStreamReady={handleStreamReady}
        onStreamError={handleStreamError}
      />

      {/* UI overlay: chat, audio controls, status bar */}
      {isStreamReady && (
        <UI
          sharedStream={sharedStream}
          onRobotStateChange={setRobotState}
        />
      )}
    </WebSocketProvider>
  );
}

export default App;