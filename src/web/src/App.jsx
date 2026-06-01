import { useEffect, useState } from "react";
import RobotView from "./components/RobotView";
import UI from "./components/UI/UI";
import { WebSocketProvider } from "./contexts/WebSocketContext";
import Login from "./auth/Login";
import { useAuth } from "./auth/useAuth";
import { installAudioUnlockListeners } from "./utils/audioPlayback";

function App() {
    const [robotState, setRobotState] = useState('neutral');
    const { isAuthenticated, logout } = useAuth();
    const [authenticated, setAuthenticated] = useState(isAuthenticated());

    useEffect(() => installAudioUnlockListeners(), []);

    const handleLogout = () => {
        logout();
        setAuthenticated(false);
    };

    if (!authenticated) {
        return <Login onLoginSuccess={() => setAuthenticated(true)} />;
    }

    return (
        <WebSocketProvider onAuthError={handleLogout}>
            <RobotView robotState={robotState} />
            <UI onRobotStateChange={setRobotState} onLogout={handleLogout} />
        </WebSocketProvider>
    );
}

export default App;
