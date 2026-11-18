# SHARA_DT: gemelo digital web de SHARA

SHARA_DT es el gemelo digital web de SHARA. Reproduce el flujo conversacional del robot fisico con una arquitectura Flask + Socket.IO + React/Vite, sustituyendo sensores y actuadores embebidos por camara, microfono, renderizado facial, anillo LED y reproduccion de audio en el navegador.

En el estado actual, el sistema se despliega como un unico servicio: Flask sirve la SPA compilada, expone la API HTTP, mantiene el canal Socket.IO `/message` y orquesta autenticacion, sesiones, presencia, conversacion, STT, LLM y TTS.

## Estado Actual

- Backend en `src/server_flask`, con Flask, Flask-SocketIO, maquina de estados por cliente, autenticacion, PostgreSQL, OpenAI Responses API y Google Cloud Speech/Text-to-Speech.
- Frontend en `src/web`, con React + Vite, login de sesion, deteccion local de presencia facial con BlazeFace, captura de audio, renderizado de ojos y anillo LED.
- Persistencia actual en PostgreSQL mediante `DATABASE_URL`; los historiales ya no se guardan en JSON.
- Identidad basada en cuenta de usuario y cookie `shara_auth`; el nombre con el que SHARA se dirige al usuario se guarda como `shara_name`.
- La presencia facial se detecta localmente en el navegador; `/api/recognize-face` queda como endpoint de compatibilidad y no calcula embeddings.
- Captura de voz mono en el navegador, remuestreada a PCM LINEAR16 de 16 kHz. Google STT procesa el turno en streaming con respaldo por lotes sobre el audio completo.
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
5. El servidor autentica el socket mediante la cookie y obtiene el nombre preferido desde PostgreSQL. El navegador vincula su `sessionId` a ese socket con `set_login_identity` y `protocolVersion: 2`.
6. Cada conexión tiene su propio estado. El modelo recibe el historial de la cuenta autenticada.

### 2. Presencia facial

1. Tras iniciar sesión y activar el sonido, el navegador solicita la cámara para buscar presencia. La interfaz permite reintentar si falla el permiso, el dispositivo o el modelo.
2. El navegador carga BlazeFace desde la propia aplicación y espera `250 ms` entre inferencias. El modelo TF.js v1 de TensorFlow se distribuye con su licencia Apache 2.0 en `src/web/public/models/blazeface`. [Modelo original](https://www.kaggle.com/models/tensorflow/blazeface/TfJs/default/1)
3. La presencia requiere confianza minima de `0.90`, una cara suficientemente grande, cajas estables y al menos seis muestras durante `1.25 s` antes de emitir `user_detected`.
4. Si la cara se pierde durante suficiente tiempo, emite `user_lost`.
5. SHARA usa la presencia para pasar de `idle` a `idle_presence` y despues a `listening`.
6. Si el usuario no tiene `shara_name`, el flujo proactivo puede preguntar quien es y registrar el nombre mediante `record_face`.

### 3. Conversacion por voz

1. Cuando SHARA cede la palabra, el navegador libera la cámara y abre el micrófono. Los 12 s de silencio empiezan con el primer bloque de audio capturado. Hasta entonces se indica que el micrófono está arrancando.
2. AudioWorklet o la captura alternativa de Web Audio entregan las mismas muestras PCM a 16 kHz. Al detectar voz se abre el flujo Socket.IO. Una pausa de 1,8 s cierra la intervención. El grabador tiene un límite de 50 s.
3. La transcripción recoge todos los segmentos finales. Si el streaming falla, termina antes de consumir el audio o sigue incompleto al cerrar, se transcribe la grabación completa por lotes.
4. Al cerrar el micrófono se vuelve a activar la cámara. Antes de hablar, SHARA exige una confirmación visual reciente. La pérdida de presencia, una pestaña oculta o la desconexión invalidan el turno y sus resultados pendientes.
5. El navegador confirma la reproducción con el identificador del mensaje. Tras una respuesta escuchada, SHARA comprueba la presencia antes de ceder la palabra. Si la reproducción falla o falta la confirmación, vuelve al reposo y muestra el motivo.
6. Tras silencio sin voz, la cámara comprueba si la persona sigue delante. Si la encuentra, SHARA vuelve a escuchar sin repetir el saludo. Una despedida deja el robot en reposo. El botón **Retomar conversación** permite iniciar otro turno sin salir de plano.

### 4. Proactividad

- Si hay un nombre guardado, SHARA puede iniciar el saludo `how_are_you` usando el historial de la cuenta.
- Si falta el nombre, puede iniciar `who_are_you` para preguntar cómo llamar a la persona.
- Tras una interaccion sin nombre confirmado, la maquina puede activar `casual_ask_known_username`, que habilita `set_username`.
- El intervalo entre saludos es de 30 min por cuenta. Empieza al confirmarse la reproducción y se conserva en PostgreSQL al reconectar.

## Estados del Robot

| Estado | Significado |
|---|---|
| `idle` | No hay usuario activo. |
| `idle_presence` | Hay presencia, pero no interaccion activa. |
| `listening` | SHARA espera entrada del usuario. |
| `recording` | El frontend esta capturando audio. |
| `processing_query` | El backend esta ejecutando STT, LLM o TTS. |
| `speaking` | El frontend esta reproduciendo la respuesta de SHARA. |

El anillo está apagado en `idle` y `processing_query`. Se mantiene morado en `idle_presence` y mientras arranca el micrófono. Gira en azul al recibir las primeras muestras y en blanco al detectar voz. El azul que respira indica que SHARA está hablando.

## API HTTP

| Metodo | Ruta | Uso actual |
|---|---|---|
| `POST` | `/api/auth/login` | Verifica `loginName` y `password`; crea cookie `shara_auth`. |
| `POST` | `/api/auth/register` | Crea usuario con password minimo de 4 caracteres; crea cookie. |
| `GET` | `/api/auth/me` | Restaura la sesion desde cookie. |
| `POST` | `/api/auth/logout` | Invalida el contexto de la sesión y limpia la cookie. |
| `POST` | `/api/session/flush` | Comprueba si la sesión sigue activa al abandonar la página. La persistencia se realiza por turno. |
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
- `microphone_ready`, `device_error` y `resume_listening`
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
- `audio_empty` e `interaction_error`

En el protocolo 2 cada evento de turno incluye `sessionId` y `turnId`. Las comprobaciones de cámara usan además `presenceCheck` y los acuses de voz incluyen `messageId` y `status`.

`RobotView` y `UI` escuchan el mismo namespace `/message`; ya no hay una ruta Socket.IO separada para animacion.

## Persistencia

La base de datos activa es PostgreSQL:

- `users`
  - `login_name`: identificador estable de login.
  - `password_hash`: password con hash de Werkzeug.
  - `shara_name`: nombre preferido que SHARA usa al hablar.
  - `last_greeting_at`: último saludo proactivo oído.
  - `created_at`.
- `conversation_messages`
  - `login_name`.
  - `role`: `user` o `assistant`.
  - `content`.
  - `session_id`.
  - `turn_id`: permite reintentar la escritura sin duplicar un mensaje.
  - `created_at`.

El servidor lee el historial por cuenta, guarda la intervención transcrita y añade la respuesta de SHARA al recibir la confirmación de reproducción. Las filas históricas sin `turn_id` siguen siendo legibles. Una avería de la base de datos genera un mensaje visible.

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
LISTENING_RESPONSE_TIMEOUT_SECONDS=12
```

Notas:

- `DATABASE_URL` es obligatorio: `db.init_schema()` se ejecuta al iniciar Flask.
- `GOOGLE_CLIENT_EMAIL` + `GOOGLE_PRIVATE_KEY` + `GOOGLE_PROJECT_ID` tienen prioridad sobre `GOOGLE_APPLICATION_CREDENTIALS`.
- `GOOGLE_APPLICATION_CREDENTIALS` puede ser un JSON de credenciales o una ruta local.
- `FLASK_SECRET_KEY` usa una clave efímera si se omite. Define un valor estable en el despliegue para restaurar la cookie tras reiniciar.
- `AUTH_COOKIE_SECURE=auto` activa cookie segura cuando detecta HTTPS o un host no local.
- `LISTENING_RESPONSE_TIMEOUT_SECONDS` limita cuanto espera SHARA una respuesta antes de volver al LED morado; es independiente del cooldown proactivo de `30 min`.
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
- La comprobación visual requiere una cámara operativa. Mientras el micrófono está abierto, una marcha se comprueba al terminar la captura o al agotar el plazo de escucha.
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
