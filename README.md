# SHARA_DT: Digital Twin of SHARA

SHARA_DT is the web-based digital twin of SHARA. It reproduces the physical robot's conversational flow with a Flask + Socket.IO + React/Vite architecture, replacing embedded sensors and actuators with browser camera, microphone, facial rendering, and audio playback.

The system currently runs as a single service: Flask serves the built SPA, exposes the HTTP API, and hosts the Socket.IO channel used by the web interface for conversation, session identity, presence, and robot state visualization.

## Current System Status

- Main backend lives in `src/server_flask` with Flask, Socket.IO, the state machine, proactive behavior, OpenAI integration, Google Cloud STT/TTS, and session identity.
- Frontend lives in `src/web` with React + Vite for camera capture, audio capture, chat UI, eye rendering, and LED ring rendering.
- Current cloud stack uses OpenAI `gpt-4o-mini`, Google batch STT at `16 kHz`, and Google TTS in Spanish (`es-ES`, LINEAR16 output).
- Face presence is detected locally in the browser with BlazeFace; identity is handled through session login and the stored SHARA name.
- Voice flow is operational with PCM LINEAR16 capture through `AudioWorklet` and a blob-based fallback when the worklet is unavailable.
- Contextual conversation is persisted per user, with tool calling for both `record_face` and `set_username`.
- Deployment is prepared for Render through `Dockerfile` and `render.yaml`.

## Changes Already Incorporated

The previous README had become heavily focused on the comparison with the physical robot. The current implementation also includes these relevant improvements:

- Frontend face-presence detection with BlazeFace, wired to the shared session identity flow.
- Login-based identity persistence through the auth/session model and stored SHARA name.
- Operational parity for `record_face` and `set_username` inside the state machine:
  - `record_face` stores the provided name for the active login/session flow,
  - `set_username` is connected end-to-end from `casual_ask_known_username` in the current conversational state machine.
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

### 1. Presence and Session Identity

1. The browser opens the camera and runs BlazeFace locally.
2. When it detects a valid face, the frontend emits `user_detected` with the current session identity.
3. When the face is lost for long enough, the frontend emits `user_lost`.
4. The backend restores conversation history for the login name when available.
5. If the session has no stored SHARA name, the conversational flow asks for the user's name and persists it.
6. `POST /api/recognize-face` remains as a compatibility endpoint for older clients, but it no longer performs backend embedding extraction.

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

- If a known user/session is present, `ProactiveService` can trigger `ask_how_are_you`.
- If an unknown user/session is detected, it can trigger `ask_who_are_you`.
- The active proactive question is stored in `robot_context.proactive_question` so that the prompt and the available tools remain coherent.
- If the conversation continues without a confirmed username, the state machine can switch into `casual_ask_known_username`, enabling the end-to-end `set_username` flow.

## Implemented Features

- Text chat and voice conversation with the backend.
- Local face-presence detection in the browser.
- Session-based identity with stored SHARA names.
- New user naming through the `record_face` tool flow.
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

### Session Identity

- Login/session identity is managed by the auth flow in `src/server_flask/auth.py`
- The user's preferred SHARA name is stored and reused by the state machine when the session returns
- `POST /api/recognize-face` remains only as a compatibility endpoint for older clients

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
- Runtime Python dependencies are listed in `src/server_flask/requirements.txt`.
- The current web deployment uses session login and frontend face-presence detection, so `face_recognition` / `dlib` are not required.

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

The main `Dockerfile` builds the frontend, installs the Python runtime dependencies, copies the React build into the backend, and starts Flask:

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
pip install -r requirements.txt
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

### GHCR image

The workflow `.github/workflows/build-shara-dt-image.yml` builds and publishes the production image from the root `Dockerfile`. It uses GitHub Actions cache for Docker layers so repeated builds do not reinstall the full dependency stack from scratch.

## Current Differences vs the Physical Robot

| Physical robot | Current SHARA_DT |
|---|---|
| Hardware sensors (`wakeface`, presence, microphone, speaker, LEDs, display) | Browser events and web rendering |
| Embedded audio capture | Browser capture through `AudioWorklet` and `MediaRecorder` |
| Local Python/OpenCV eye rendering | React canvas rendering in `src/web/src/eyes` |
| Cloud services integrated into one Python robot app | Cloud services reused from Flask + Socket.IO |
| Dedicated robot camera | Browser camera with frontend face-presence detection and session login |

Behavioral fidelity is high in the conversational logic and voice flow, while identity is handled through the web session model instead of the physical robot's local face-recognition pipeline.

## Known Limitations and Remaining Work

- There are still no automated parity tests between the physical robot and the digital twin.
- The `presence` path in `ProactiveService` exists, but it is not yet wired end-to-end from the frontend.
- The active conversation store is `conversations_db.json`, while the repository still carries the legacy placeholder `conversation_db.json`.
- The web state machine still simplifies some hardware-specific transitions from the physical robot.

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
