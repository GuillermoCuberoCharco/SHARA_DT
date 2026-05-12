# SHARA_DT: gemelo digital web de SHARA

SHARA_DT es el gemelo digital web de SHARA. Reproduce el flujo conversacional del robot fisico con una arquitectura Flask + Socket.IO + React/Vite, sustituyendo sensores y actuadores embebidos por camara, microfono, renderizado facial, anillo LED y reproduccion de audio en el navegador.

En el estado actual, el sistema se despliega como un unico servicio: Flask sirve la SPA compilada, expone la API HTTP, mantiene el canal Socket.IO `/message` y orquesta autenticacion, sesiones, presencia, conversacion, STT, LLM y TTS.

## Estado Actual

- Backend en `src/server_flask`, con Flask, Flask-SocketIO, maquina de estados por cliente, autenticacion, PostgreSQL, OpenAI Responses API y Google Cloud Speech/Text-to-Speech.
- Frontend en `src/web`, con React + Vite, login de sesion, deteccion local de presencia facial con BlazeFace, captura de audio, renderizado de ojos y anillo LED.
- Persistencia actual en PostgreSQL mediante `DATABASE_URL`; los historiales ya no se guardan en JSON.
- Identidad basada en cuenta de usuario y cookie `shara_auth`; el nombre con el que SHARA se dirige al usuario se guarda como `shara_name`.
- La presencia facial se detecta localmente en el navegador; `/api/recognize-face` queda como endpoint de compatibilidad y no calcula embeddings.
- Audio principal por `AudioWorklet`: PCM LINEAR16 mono a 16 kHz, enviado por Socket.IO y procesado con Google STT batch.
- TTS actual con Google Cloud en espanol (`es-ES`) y salida MP3 (`audio/mpeg`).
- LLM actual: OpenAI `gpt-4o-mini`, salida estructurada con `response`, `robot_mood` y `continue`.
- Herramientas activas del modelo: `record_face` y `set_username`, usadas para registrar o recuperar el nombre preferido del usuario.
- Despliegue preparado con `Dockerfile`, `render.yaml` y workflow manual de GHCR.

## Arquitectura

```text
SHARA_DT
|-- Dockerfile
|-- render.yaml
|-- .github/workflows/build-shara-dt-image.yml
|-- src/server_flask
|   |-- app.py                      # Flask, Socket.IO, auth HTTP API y SPA serving
|   |-- auth.py                     # Login, registro y shara_name en PostgreSQL
|   |-- db.py                       # Conexion y schema PostgreSQL
|   |-- state_machine.py            # Estado conversacional por Socket.IO sid
|   |-- proactive_service.py        # Preguntas proactivas y cooldowns
|   |-- robot_context.py            # Contenedor de estado por sesion
|   |-- sockets/message_handler.py  # Eventos Socket.IO del namespace /message
|   |-- eyes/service.py             # Emision de set_face hacia el frontend
|   |-- services/cloud
|   |   |-- server.py               # STT -> LLM -> TTS
|   |   |-- google_api.py           # Google Speech-to-Text y Text-to-Speech
|   |   `-- openai_api.py           # Prompt, tools e historial PostgreSQL
|   `-- files
|       |-- shara_prompt.txt
|       |-- tools_config.json
|       `-- conversation_db.json    # Placeholder legado, no usado como store activo
`-- src/web
    |-- package.json
    |-- public
    |   |-- pcm-processor.js        # AudioWorklet PCM LINEAR16
    |   `-- images/shara.png
    `-- src
        |-- App.jsx
        |-- config.js
        |-- contexts/WebSocketContext.jsx
        |-- components
        |   |-- SessionLogin.jsx
        |   |-- FaceDetection.jsx
        |   |-- RobotView.jsx
        |   |-- LedCircle.jsx
        |   `-- UI/UI.jsx
        `-- eyes/*                 # Renderizado de cara, interpolacion y parpadeo
```

## Flujo de Ejecucion

### 1. Autenticacion y sesion

1. Al cargar la app, `App.jsx` llama a `GET /api/auth/me` para restaurar una sesion existente.
2. Si no hay cookie valida, `SessionLogin.jsx` muestra login o registro.
3. Login y registro crean una cookie HTTP-only `shara_auth`.
4. Al conectarse Socket.IO, el frontend emite `register_client`.
5. Cuando la conexion queda registrada, el frontend emite `set_login_identity` con `loginName`, `sessionId`, `userName` y estado de identificacion.
6. El backend crea un `RobotContext` por `sid`, carga el historial de `loginName` desde PostgreSQL y marca si falta `shara_name`.

### 2. Presencia facial

1. Tras autenticarse, el navegador solicita camara si hay dispositivo disponible.
2. `FaceDetection.jsx` carga BlazeFace y evalua la presencia localmente cada `250 ms`.
3. Con dos detecciones consecutivas validas, emite `user_detected`.
4. Si la cara se pierde durante suficiente tiempo, emite `user_lost`.
5. SHARA usa la presencia para pasar de `idle` a `idle_presence` y despues a `listening`.
6. Si el usuario no tiene `shara_name`, el flujo proactivo puede preguntar quien es y registrar el nombre mediante `record_face`.

### 3. Conversacion por voz

1. Cuando hay presencia y el sistema esta libre, el frontend inicia grabacion automaticamente.
2. `useAudioRecorder.jsx` usa `AudioWorklet` (`public/pcm-processor.js`) para convertir audio a PCM LINEAR16 mono a `16 kHz`.
3. El frontend envia `audio_stream_start`, multiples `audio_chunk` en base64 y `audio_stream_end`.
4. La grabacion se detiene tras `2 s` de silencio o al alcanzar el limite duro de `50 s`.
5. `state_machine.py` pasa a `processing_query` y ejecuta la cadena en `services/cloud/server.py`:
   - Google Speech-to-Text,
   - OpenAI Responses API,
   - Google Text-to-Speech.
6. El backend emite `transcription_result`, `robot_message`, `set_face` y `state_update`.
7. El frontend reproduce el MP3 recibido, actualiza ojos/anillo LED y emite `tts_complete`.

### 4. Proactividad

- Usuario conocido: `ProactiveService` puede disparar `ask_how_are_you`.
- Usuario desconocido o sin `shara_name`: puede disparar `ask_who_are_you`.
- Tras una interaccion sin nombre confirmado, la maquina puede activar `casual_ask_known_username`, que habilita `set_username`.
- El cooldown de preguntas proactivas es de `120 s`.

## Estados del Robot

| Estado | Significado |
|---|---|
| `idle` | No hay usuario activo. |
| `idle_presence` | Hay presencia, pero no interaccion activa. |
| `listening` | SHARA espera entrada del usuario. |
| `recording` | El frontend esta capturando audio. |
| `processing_query` | El backend esta ejecutando STT, LLM o TTS. |
| `speaking` | El frontend esta reproduciendo la respuesta de SHARA. |

El anillo LED replica estos estados: apagado para `idle`/`processing_query`, morado fijo en `idle_presence`, azul giratorio en `listening`, blanco giratorio en `recording` y azul respirando en `speaking`.

## API HTTP

| Metodo | Ruta | Uso actual |
|---|---|---|
| `POST` | `/api/auth/login` | Verifica `loginName` y `password`; crea cookie `shara_auth`. |
| `POST` | `/api/auth/register` | Crea usuario con password minimo de 4 caracteres; crea cookie. |
| `GET` | `/api/auth/me` | Restaura la sesion desde cookie. |
| `POST` | `/api/auth/logout` | Fuerza flush de sesion runtime y limpia la cookie. |
| `POST` | `/api/session/flush` | Flush explicito al cerrar o abandonar pagina. |
| `GET` | `/health` | Devuelve `status`, `active_sessions` y `session_states`. |
| `POST` | `/api/synthesize` | Convierte texto a audio MP3 base64 como fallback TTS. |
| `POST` | `/api/recognize-face` | Compatibilidad con clientes antiguos; resuelve identidad por sesion, no por embeddings. |
| `GET` | `/*` | Sirve la SPA compilada desde `src/server_flask/static` en produccion. |

### `/api/recognize-face`

Este endpoint acepta campos legacy como `faces`, `clientId`, `sessionId`, `userName` o `username`, pero en el sistema actual no hace reconocimiento facial real. Responde con `recognitionBackend: "session_login"` y datos derivados de la sesion recibida.

## Contrato Socket.IO

Namespace activo: `/message`.

Eventos enviados por el frontend:

- `register_client`
- `set_login_identity`
- `user_detected`
- `user_lost`
- `audio_stream_start`
- `audio_chunk`
- `audio_stream_end`
- `client_message` para texto o audio blob legacy
- `transcription_result` como ruta de texto fallback
- `tts_complete`

Eventos emitidos por el backend:

- `registration_success`
- `client_message`
- `transcription_result`
- `robot_message`
- `state_update`
- `set_face`
- `session_identity_updated`
- `audio_empty`

`RobotView` y `UI` escuchan el mismo namespace `/message`; ya no hay una ruta Socket.IO separada para animacion.

## Persistencia

La base de datos activa es PostgreSQL:

- `users`
  - `login_name`: identificador estable de login.
  - `password_hash`: password con hash de Werkzeug.
  - `shara_name`: nombre preferido que SHARA usa al hablar.
  - `created_at`.
- `conversation_messages`
  - `login_name`.
  - `role`: `user` o `assistant`.
  - `content`.
  - `session_id`.
  - `created_at`.

`openai_api.py` carga el historial por `login_name` en cada peticion y persiste cada intercambio exitoso usuario/asistente como filas nuevas. El antiguo flujo de volcado a JSON queda como compatibilidad; `src/server_flask/files/conversation_db.json` no es el store activo.

## Variables de Entorno

Obligatorias para un arranque funcional:

```env
DATABASE_URL=postgresql://user:password@host/db?sslmode=require
OPENAI_API_KEY=...

# Opcion recomendada en Render:
GOOGLE_CLIENT_EMAIL=...
GOOGLE_PRIVATE_KEY=...
GOOGLE_PROJECT_ID=...

# Alternativa local/legacy:
GOOGLE_APPLICATION_CREDENTIALS=...
```

Recomendadas u opcionales:

```env
FLASK_SECRET_KEY=...
PORT=8081
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
AUTH_COOKIE_MAX_AGE_SECONDS=2592000
AUTH_COOKIE_SAMESITE=Lax
AUTH_COOKIE_SECURE=auto
```

Notas:

- `DATABASE_URL` es obligatorio: `db.init_schema()` se ejecuta al iniciar Flask.
- `GOOGLE_CLIENT_EMAIL` + `GOOGLE_PRIVATE_KEY` + `GOOGLE_PROJECT_ID` tienen prioridad sobre `GOOGLE_APPLICATION_CREDENTIALS`.
- `GOOGLE_APPLICATION_CREDENTIALS` puede ser un JSON de credenciales o una ruta local.
- `FLASK_SECRET_KEY` tiene fallback de desarrollo, pero en despliegue debe definirse.
- `AUTH_COOKIE_SECURE=auto` activa cookie segura cuando detecta HTTPS o un host no local.
- `EYES_WIDTH` y `EYES_HEIGHT` aparecen en `render.yaml`, pero el codigo actual no los consume.

## Desarrollo Local

### Opcion Docker

```bash
docker build -t shara-dt .
docker run --env-file .env -p 8081:8081 shara-dt
```

La app queda disponible en `http://localhost:8081`.

### Opcion con dos procesos

Backend Flask:

```bash
cd src/server_flask
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

En PowerShell:

```powershell
cd src/server_flask
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Frontend Vite:

```bash
cd src/web
yarn install
yarn dev
```

En desarrollo, Vite sirve la interfaz normalmente en `http://localhost:5173` y el backend escucha en `http://localhost:8081`. `src/web/src/config.js` usa origen vacio en produccion y `http://localhost:8081` en desarrollo.

## Despliegue

### Render

`render.yaml` define un unico servicio web Docker llamado `shara-dt` que usa el `Dockerfile` de la raiz. En produccion, Flask sirve la SPA compilada y comparte origen con la API HTTP y Socket.IO.

Configura en Render las variables obligatorias, especialmente `DATABASE_URL`, `OPENAI_API_KEY` y credenciales de Google. El `render.yaml` actual no provisiona la base de datos por si mismo.

### GHCR

`.github/workflows/build-shara-dt-image.yml` ejecuta manualmente (`workflow_dispatch`) la construccion y publicacion de la imagen en GHCR con tags `latest` y `sha`.

## Diferencias con el Robot Fisico

| Robot fisico | SHARA_DT actual |
|---|---|
| Sensores, microfono, altavoz, LEDs y pantalla embebidos | Camara/microfono del navegador, audio web, canvas de ojos y LED renderizado |
| Identificacion por pipeline local del robot | Login web + presencia facial local con BlazeFace |
| Estado conversacional global | `RobotContext` por cliente Socket.IO |
| Captura de audio PyAudio | `AudioWorklet` PCM LINEAR16 en navegador |
| Visualizacion de ojos en Python/OpenCV | React canvas en `src/web/src/eyes` |
| Persistencia local/legacy | PostgreSQL por `login_name` |

La fidelidad principal esta en el flujo conversacional, proactividad, estados operativos, voz y expresividad visual. La identidad se ha adaptado al modelo web con cuenta, cookie y nombre preferido.

## Limitaciones Conocidas

- No hay tests automatizados de paridad con el robot fisico.
- La ruta principal de audio es batch STT con PCM acumulado; los helpers de streaming STT existen, pero no estan conectados al flujo activo.
- El componente `ChatWindow` y el path de texto por Socket.IO existen, pero la UI activa esta centrada en voz, presencia y visualizacion del robot.
- `/api/recognize-face` es solo compatibilidad legacy.
- `render.yaml` no crea ni enlaza una base de datos; `DATABASE_URL` debe configurarse aparte.
- El repositorio no incluye actualmente un archivo `LICENSE`.

## Requisitos

- Python `3.10` recomendado.
- Node.js `20+`.
- Yarn.
- PostgreSQL accesible por `DATABASE_URL`.
- Cuenta/API key de OpenAI.
- Credenciales de Google Cloud con Speech-to-Text y Text-to-Speech habilitados.

Las dependencias Python estan en `src/server_flask/requirements.txt`; las dependencias web estan en `src/web/package.json`.

## Contacto

Guillermo Cubero Charco  
Guillermo.Cubero@uclm.es

Proyecto realizado como parte de un Trabajo Fin de Master en la ESI (UCLM), Ciudad Real, Espana.

## Agradecimientos

- Ramon Hervas Lucas (advisor)
- Laura Villa Fernandez-Arroyo (co-advisor)
- MAmI Research Lab
- Panel internacional de expertos HRI por su evaluacion y feedback
