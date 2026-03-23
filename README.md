# PI-ChatShara

PI-ChatShara es una variante del gemelo digital SHARA_DT que elimina los componentes de voz, reconocimiento facial y comportamiento proactivo, reduciendo el sistema a una **interfaz de chat de texto** conectada directamente a la API de OpenAI.

El sistema corre como un único servicio: Flask sirve la SPA de React, gestiona el canal Socket.IO y orquesta las llamadas a OpenAI.

## Objetivo

Proporcionar una interfaz conversacional limpia y desplegable en Render donde el usuario escribe mensajes de texto y recibe respuestas generadas por `gpt-4o-mini`, manteniendo el historial de conversación en memoria durante la sesión.

## Arquitectura

```text
PI-ChatShara
|-- src/server_flask
|   |-- app.py                      # Flask, Socket.IO y servido de la SPA
|   |-- state_machine.py            # Gestión del estado (idle / processing_query)
|   |-- robot_context.py            # Contenedor de estado global thread-safe
|   |-- sockets/message_handler.py  # Eventos Socket.IO del namespace /message
|   `-- services/cloud
|       |-- server.py               # Recibe texto, llama a OpenAI, devuelve respuesta
|       `-- openai_api.py           # Historial de conversación y llamadas al API
`-- src/web
    |-- src/App.jsx
    |-- src/components/RobotView.jsx
    |-- src/components/LedCircle.jsx
    `-- src/components/UI
        |-- UI.jsx
        |-- subcomponents/ChatWindow.jsx
        `-- utils/StatusBar.jsx
```

## Flujo de funcionamiento

```
Usuario escribe texto
    → client_message  (Socket.IO)
        → state_machine.on_text_message()
            → OpenAI gpt-4o-mini
                → robot_message  (Socket.IO)
                    → UI muestra la respuesta
```

1. El usuario escribe un mensaje en el chat y pulsa Enviar (o Enter).
2. El frontend emite `client_message` al namespace `/message` de Socket.IO.
3. El backend cambia el estado a `processing_query` y llama a `services/cloud/server.py`.
4. `openai_api.py` envía el historial completo de la sesión más el nuevo mensaje a `gpt-4o-mini`.
5. La respuesta se emite de vuelta al frontend como `robot_message` con texto y estado emocional.
6. El estado vuelve a `idle` y el mensaje se muestra en el chat.

## Estados del sistema

| Estado | Significado |
|---|---|
| `idle` | Esperando entrada del usuario |
| `processing_query` | Llamada a OpenAI en curso |

## API HTTP

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/health` | Devuelve `status` y `robot_state` |
| `GET` | `/*` | Sirve la SPA de React en producción |

## Contrato Socket.IO

Namespace activo: `/message`

### Eventos recibidos del frontend

| Evento | Descripción |
|---|---|
| `register_client` | Registro del cliente web |
| `client_message` | Mensaje de texto del usuario (`{ type, text }`) |

### Eventos emitidos por el backend

| Evento | Descripción |
|---|---|
| `registration_success` | Confirmación de registro |
| `robot_message` | Respuesta del asistente (`{ text, state }`) |
| `state_update` | Cambio de estado del sistema (`{ state }`) |

## Componentes eliminados respecto a SHARA_DT

| Componente | Motivo de eliminación |
|---|---|
| Reconocimiento facial (BlazeFace + `face_recognition`) | No se usa cámara |
| Captura de audio (AudioWorklet + PCM) | No se usa micrófono |
| Google Cloud STT / TTS | Sin voz |
| `ProactiveService` | Sin comportamiento proactivo |
| `eyes/service.py` | Sin emisión de expresiones por hardware |
| `AudioControls.jsx` | Sin controles de grabación |
| `FaceDetection.jsx` | Sin detección de cara |
| `useAudioRecorder.jsx` | Sin captura de audio |
| `pcm-processor.js` | Sin AudioWorklet |
| `Dockerfile.face-recognition` | Sin dependencias nativas de dlib |

## Requisitos

- Python `3.10` o `3.11`
- Node.js `20+`
- Yarn
- OpenAI API key

## Variables de entorno

```env
OPENAI_API_KEY=...
FLASK_SECRET_KEY=...   # Opcional, por defecto: shara-woz-secret
PORT=8081              # Opcional, por defecto: 8081
```

## Desarrollo local

### Con Docker

```bash
docker build -t pi-chatshara .
docker run --env-file .env -p 8081:8081 pi-chatshara
```

La aplicación queda disponible en `http://localhost:8081`.

### Con dos procesos

#### Backend Flask

```bash
cd src/server_flask
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# o: .\.venv\Scripts\Activate.ps1  # PowerShell
pip install -r requirements.txt
python app.py
```

#### Frontend Vite

```bash
cd src/web
yarn install
yarn dev
```

En desarrollo:
- Frontend en `http://localhost:5173`
- Backend en `http://localhost:8081`
- `src/web/src/config.js` apunta automáticamente a `http://localhost:8081` cuando `import.meta.env.PROD` es false

## Despliegue en Render

- `render.yaml` define un único servicio Docker llamado `shara-dt`
- El contenedor usa el `Dockerfile` de la raíz
- En producción, frontend y backend comparten el mismo origen

## Contexto del proyecto

Este repositorio es parte de un Trabajo de Fin de Máster desarrollado en la ESI (UCLM), Ciudad Real, España.

**Autor:** Guillermo Cubero Charco — Guillermo.Cubero@uclm.es
**Director:** Ramon Hervas Lucas
**Co-directora:** Laura Villa Fernandez-Arroyo
**Laboratorio:** MAmI Research Lab
