# SHARA_DT: Digital Twin of SHARA^3

SHARA_DT is the web-based digital twin of SHARA^3. It reproduces the physical robot's conversational flow with a Flask + Socket.IO + React/Vite architecture, replacing embedded sensors and actuators with browser camera, microphone, facial rendering, and audio playback.

The system currently runs as a single service: Flask serves the built SPA, exposes the HTTP API, and hosts the Socket.IO channel used by the web interface for conversation, face recognition, and robot state visualization.

## Current System Status

- Main backend lives in `src/server_flask` with Flask, Socket.IO, the state machine, proactive behavior, OpenAI integration, Google Cloud STT/TTS, and face recognition.
- Frontend lives in `src/web` with React + Vite for camera capture, audio capture, chat UI, eye rendering, and LED ring rendering.
- Current cloud stack uses OpenAI `gpt-4o-mini`, Google batch STT at `16 kHz`, and Google TTS in Spanish (`es-ES`, LINEAR16 output).
- Batch face recognition is operational, with local face detection in the browser and embeddings generated on the backend with `face_recognition`.
- Voice flow is operational with PCM LINEAR16 capture through `AudioWorklet` and a blob-based fallback when the worklet is unavailable.
- Contextual conversation is persisted per user, with tool calling for both `record_face` and `set_username`.
- Deployment is prepared for Render through `Dockerfile` and `render.yaml`.

## Changes Already Incorporated

The previous README had become heavily focused on the comparison with the physical robot. The current implementation also includes these relevant improvements:

- Batch face recognition with `faceBoxes` sent by the frontend to improve embedding extraction.
- Current face confirmation semantics:
  - known user confirmed after `3` valid recognitions,
  - unknown user confirmed after `6` valid recognitions.
- Real facial persistence in `encodings.csv`, with automatic migration from `face_database.json` if a legacy database exists.
- Operational parity for `record_face` and `set_username` inside the state machine:
  - `record_face` persists the pending embeddings linked to the active face session,
  - `set_username` is now connected end-to-end from `casual_ask_known_username` in the current conversational state machine.
- The tool-calling serialization fix in `src/server_flask/services/cloud/openai_api.py`, avoiding raw objects returned by `responses.parse()` from being injected back into the request flow.
- Frontend support for rendering the robot LED ring according to the operational state (`idle`, `listening`, `recording`, `speaking`, and related modes).
- `RobotView` uses a single Socket.IO namespace, `/message`, for both `set_face` and `state_update`; there is no active separate animation route anymore.
- Legacy comments that still referred to old namespaces or old socket paths have been cleaned up in the active modules.
- Unified deployment: in production, the built frontend is served directly by Flask and shares origin with Socket.IO and the HTTP API.

## Current Architecture

```text
SHARA_DT
|-- src/server_flask
|   |-- app.py                      # Flask, Socket.IO, HTTP API, and SPA serving
|   |-- state_machine.py            # Conversational logic and state transitions
|   |-- proactive_service.py        # Proactive triggers and cooldown logic
|   |-- robot_context.py            # Global robot state container
|   |-- sockets/message_handler.py  # Socket.IO events for the /message namespace
|   |-- eyes/service.py             # Emits set_face events to the frontend
|   |-- services/camera_service.py  # Face recognition and persistence
|   `-- services/cloud
|       |-- server.py               # STT -> LLM -> TTS orchestration
|       |-- google_api.py           # Google Cloud Speech and TTS
|       `-- openai_api.py           # Prompt, tools, and conversation history
`-- src/web
    |-- src/App.jsx
    |-- src/components/FaceDetection.jsx
    |-- src/components/RobotView.jsx
    |-- src/components/LedCircle.jsx
    |-- src/components/UI
    |   |-- UI.jsx
    |   |-- hooks/useAudioRecorder.jsx
    |   `-- subcomponents/*
    `-- src/eyes/*                  # Face rendering, interpolation, and blinking
```

## Current Runtime Flow

### 1. Face Detection and Recognition

1. The browser opens the camera and runs BlazeFace locally.
2. When it detects a valid face, it crops and normalizes the face and builds a batch of `3` frames.
3. The frontend sends the batch to `POST /api/recognize-face` together with `clientId`, `sessionId`, and `faceBoxes`.
4. The backend extracts embeddings with `face_recognition`, compares them against `encodings.csv`, and accumulates per-session recognition history.
5. If a known user is confirmed, the frontend emits `user_detected` with `needsIdentification=false`.
6. If an unknown user is confirmed, their embeddings remain temporarily available until the conversational flow triggers `record_face`.

### 2. Voice Conversation

1. When a user is present and the system is free, the frontend can start audio capture automatically.
2. `useAudioRecorder.jsx` captures mono audio at `16 kHz` with `AudioWorklet` and sends PCM chunks through Socket.IO (`audio_stream_start`, `audio_chunk`, `audio_stream_end`).
3. Recording stops automatically after `2` seconds of silence or after the configured hard limit.
4. Once the stream closes, `state_machine.py` executes a batch pipeline:
   - Google Cloud STT,
   - response generation with OpenAI,
   - Google Cloud TTS.
5. The backend answers with `robot_message`, `state_update`, and, when needed, `set_face`.
6. The frontend plays the audio, updates the robot visuals, and notifies `tts_complete`.

### 3. Proactivity

- If a known face is recognized, `ProactiveService` can trigger `ask_how_are_you`.
- If an unknown face is detected, it can trigger `ask_who_are_you`.
- The active proactive question is stored in `robot_context.proactive_question` so that the prompt and the available tools remain coherent.
- If the conversation continues without a confirmed username, the state machine can switch into `casual_ask_known_username`, enabling the end-to-end `set_username` flow.

## Implemented Features

- Text chat and voice conversation with the backend.
- Local face detection in the browser.
- Batch face recognition with confirmation through per-session history.
- New user registration through the `record_face` tool flow.
- Username recovery through the `casual_ask_known_username -> set_username` flow.
- Loading and storing conversation history per username.
- Frontend face rendering with expression interpolation and automatic blinking.
- LED ring visualization with `off`, `static`, `loop`, and `breath` effects.
- Distributed operational state updates between backend and frontend through `state_update`.
- HTTP speech synthesis fallback endpoint (`/api/synthesize`).
- Service health endpoint (`/health`).

## Robot States

The current state machine uses these main states:

| State | Meaning |
|---|---|
| `idle` | No user is currently present. |
| `idle_presence` | A user is present, but there is no active interaction yet. |
| `listening` | The robot is waiting for user input. |
| `recording` | The frontend is currently capturing audio. |
| `processing_query` | The backend is running STT, LLM, and/or TTS work. |
| `speaking` | The frontend is playing the robot response. |

## Current HTTP API

| Method | Route | Current usage |
|---|---|---|
| `GET` | `/health` | Returns `status` and `robot_state`. |
| `POST` | `/api/synthesize` | Synthesizes text to audio if the frontend needs fallback audio generation. |
| `POST` | `/api/recognize-face` | Processes a face batch sent as `multipart/form-data`. |
| `GET` | `/*` | Serves the built SPA in production. |

### `POST /api/recognize-face`

Expected fields:

- `faces`: list of JPEG/PNG images in the batch.
- `clientId`: web client identifier.
- `sessionId`: face-session identifier.
- `faceBoxes`: JSON list of bounding boxes for each frame.

Main response fields:

- `userName`
- `recognitionBackend`
- `isNewUser`
- `needsIdentification`
- `userStatus`
- `pendingRecognition`
- `isConfirmed`
- `historyCount`
- `detectionProgress`
- `totalRequired`

## Current Socket.IO Contract

The system uses a single active namespace: `/message`.

### Events sent by the frontend

- `register_client`
- `client_message`
- `audio_stream_start`
- `audio_chunk`
- `audio_stream_end`
- `user_detected`
- `user_lost`
- `tts_complete`

### Events emitted by the backend

- `registration_success`
- `robot_message`
- `client_message`
- `transcription_result`
- `state_update`
- `set_face`
- `audio_empty`

## Persistence and Data Files

### Face Recognition

- Current main file: `src/server_flask/files/encodings.csv`
- Format: one embedding per row using `username;128 values`
- If `src/server_flask/files/face_database.json` exists, the backend attempts to migrate it automatically into `encodings.csv`

### Conversations

- The backend loads and stores conversation history in `src/server_flask/files/conversations_db.json`
- Unknown-user testing traces may be written to `src/server_flask/files/conversations_unknown_db.json`
- The repository still contains `src/server_flask/files/conversation_db.json` as a legacy placeholder, but it is not the file used by `openai_api.py`

### Prompt and Tools

- Main prompt: `src/server_flask/files/shara_prompt.txt`
- Tool definitions: `src/server_flask/files/tools_config.json`

## Requirements

- Python `3.10` or `3.11`
- Node.js `20+`
- Yarn
- OpenAI API key
- Google Cloud credentials for Speech-to-Text and Text-to-Speech
- Native dependencies required by `face_recognition` / `dlib`

In Linux or Docker environments, the project explicitly installs:

- `build-essential`
- `cmake`
- `g++`
- `pkg-config`
- `python3-dev`
- `libopenblas-dev`
- `liblapack-dev`
- `libjpeg-dev`
- `zlib1g-dev`

## Environment Variables Currently Used

Variables actually consumed by the code:

```env
OPENAI_API_KEY=...
GOOGLE_CLIENT_EMAIL=...
GOOGLE_PRIVATE_KEY=...
GOOGLE_PROJECT_ID=...
GOOGLE_APPLICATION_CREDENTIALS=...
FLASK_SECRET_KEY=...
PORT=8081
```

Notes:

- `GOOGLE_CLIENT_EMAIL` + `GOOGLE_PRIVATE_KEY` + `GOOGLE_PROJECT_ID` is the preferred setup for deployments such as Render.
- `GOOGLE_APPLICATION_CREDENTIALS` can be either a JSON string or a local path to a credentials file.
- `FLASK_SECRET_KEY` falls back to `shara-woz-secret` if it is not defined.
- `PORT` falls back to `8081`.

Legacy or compatibility variables that still appear in some files but do not change the current behavior:

- `ALLOWED_ORIGINS`
- `FACE_DESCRIPTOR_BACKEND`
- `EYES_WIDTH`
- `EYES_HEIGHT`

## Local Development

### Recommended option: Docker

The main `Dockerfile` builds the frontend, installs the Python dependencies including `face_recognition`, copies the React build into the backend, and starts Flask:

```bash
docker build -t shara-dt .
docker run --env-file .env -p 8081:8081 shara-dt
```

Once started, the application is available at `http://localhost:8081`.

### Local development with two processes

#### 1. Flask backend

```bash
cd src/server_flask
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .\.venv\Scripts\Activate.ps1  # PowerShell
pip install -r requirements.face-recognition.txt
python app.py
```

#### 2. Vite frontend

```bash
cd src/web
yarn install
yarn dev
```

In development:

- the frontend is usually served at `http://localhost:5173`
- the backend listens at `http://localhost:8081`
- `src/web/src/config.js` uses `http://localhost:8081` when `import.meta.env.PROD` is false

## Deployment

### Render

- `render.yaml` defines a single Docker web service called `shara-dt`
- the container uses the root `Dockerfile`
- in production, the frontend and backend share the same origin

### Alternative image for `face_recognition` validation

The repository also includes:

- `Dockerfile.face-recognition`
- workflow `.github/workflows/build-face-recognition-image.yml`

That pipeline builds and publishes an image focused on validating the `face_recognition` installation.

## Current Differences vs the Physical Robot

| Physical robot | Current SHARA_DT |
|---|---|
| Hardware sensors (`wakeface`, presence, microphone, speaker, LEDs, display) | Browser events and web rendering |
| Embedded audio capture | Browser capture through `AudioWorklet` and `MediaRecorder` |
| Local Python/OpenCV eye rendering | React canvas rendering in `src/web/src/eyes` |
| Cloud services integrated into one Python robot app | Cloud services reused from Flask + Socket.IO |
| Dedicated robot camera | Browser camera plus face batches sent to the backend |

Behavioral fidelity is high in the conversational logic and medium-high in voice and face recognition, but some adaptations are still unavoidable because this is a web-based twin rather than the embedded robot stack.

Notable difference:

- The web face-recognition pipeline currently confirms unknown users after `6` valid detections, while the physical robot used `8` consecutive unknown detections in its original wakeface flow.

## Known Limitations and Remaining Work

- There are still no automated parity tests between the physical robot and the digital twin.
- The `presence` path in `ProactiveService` exists, but it is not yet wired end-to-end from the frontend.
- The active conversation store is `conversations_db.json`, while the repository still carries the legacy placeholder `conversation_db.json`.
- The web state machine still simplifies some hardware-specific transitions from the physical robot.
- Local installation of `face_recognition` can be expensive outside Docker because of the native `dlib` toolchain.

## Contributing

Contributions are welcome:

1. Fork the repository.
2. Create a branch for your change (`git checkout -b feature/new-feature`).
3. Make your changes and commit them.
4. Push the branch to your fork.
5. Open a Pull Request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contact

Guillermo Cubero Charco  
Guillermo.Cubero@uclm.es

This project is part of a Master's Thesis carried out at ESI (UCLM), Ciudad Real, Spain.

## Acknowledgments

- Ramon Hervas Lucas (advisor)
- Laura Villa Fernandez-Arroyo (co-advisor)
- MAmI Research Lab
- The international panel of HRI experts for their evaluation and feedback
