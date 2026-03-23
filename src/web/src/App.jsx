import { useState } from "react";
import RobotView from "./components/RobotView";
import UI from "./components/UI/UI";
import { WebSocketProvider } from "./contexts/WebSocketContext";

function App() {
  const [robotState, setRobotState] = useState('neutral');

  return (
    <WebSocketProvider>
      <RobotView robotState={robotState} />
      <UI onRobotStateChange={setRobotState} />
    </WebSocketProvider>
  );
}

export default App;
