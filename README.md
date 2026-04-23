# PI-ChatShara

PI-ChatShara es una variante de SHARA_DT centrada en una interfaz de chat autenticado con texto y audio. La aplicacion se ejecuta como un unico servicio: Flask sirve la SPA de React, mantiene el canal Socket.IO y orquesta las llamadas a OpenAI y Google Cloud. El sistema distingue entre alumnado y profesorado, y todas las conversaciones quedan segmentadas por asignatura activa.

## Estado actual

La rama `PI-ChatShara` implementa actualmente:

- Login y registro de usuarios con JWT, rol y asignatura activa.
- Roles `student` y `teacher`.
- Conexion Socket.IO autenticada en el namespace `/message`.
- Persistencia de usuarios, asignaturas y conversaciones en Postgres a traves de `DATABASE_URL`.
- Recuperacion automatica del historial de chat de la asignatura activa al reconectar.
- Contexto privado para profesorado con acceso a los historiales completos del alumnado de su asignatura activa, sin exponer esos chats en la UI.
- Interfaz web de chat con estado de conexion, espera, grabacion de audio y reproduccion opcional de voz.
- Gestion de asignaturas desde la propia interfaz: el alumnado solo puede vincular asignaturas existentes y el profesorado puede crear asignaturas con limite opcional de alumnos.
- STT y TTS con Google Cloud integrados en el flujo del chat.
- Vista visual del robot con ojos animados y anillo LED.

La aplicacion sigue centrada en una experiencia de chat web autenticada con persistencia fuera del filesystem efimero de Render. El reconocimiento facial y el comportamiento proactivo siguen fuera del flujo activo, pero el chat vuelve a admitir audio: el usuario puede grabar mensajes, el backend los transcribe con Google Cloud Speech-to-Text y la respuesta del robot puede reproducirse con Google Cloud Text-to-Speech. Esta voz se puede silenciar desde la interfaz y, cuando esta desactivada, no se invoca el servicio TTS.

## Arquitectura

```text
PI-ChatShara
|-- src/server_flask
|   |-- app.py                      # Flask, Socket.IO, SPA y bootstrap de DB
|   |-- db.py                       # Conexion Postgres + autocreacion de schema
|   |-- auth.py                     # Login, registro, asignaturas y verificacion de JWT
|   |-- create_user.py              # Utilidad CLI para crear o actualizar usuarios
|   |-- migrate_users_json.py       # Importa usuarios legacy desde users.json
|   |-- state_machine.py            # Estado por usuario y ejecucion de consultas
|   |-- subject_codes.py            # Normalizacion y validacion de codigos de asignatura
|   |-- sockets/message_handler.py  # Namespace /message autenticado
|   |-- user_roles.py               # Roles validos y utilidades de autorizacion
|   `-- services/cloud
|       |-- server.py               # Pipeline de consulta al modelo
|       |-- google_api.py           # STT/TTS de Google Cloud
|       `-- openai_api.py           # Historial por usuario/asignatura y contexto docente
`-- src/web
    |-- src/App.jsx
    |-- src/auth
    |   |-- Login.jsx               # Pantalla de login/registro por asignatura
    |   `-- useAuth.js              # Sesion y asignaturas en localStorage
    |-- public
    |   `-- pcm-processor.js        # AudioWorklet para enviar PCM LINEAR16
    |-- src/contexts/WebSocketContext.jsx
    `-- src/components
        |-- RobotView.jsx           # Imagen del robot, ojos y LED
        `-- UI
            |-- UI.jsx              # Estado del chat y gestion de asignaturas
            |-- hooks/useAudioRecorder.jsx
            `-- subcomponents/ChatWindow.jsx
```

## Flujo de funcionamiento

### 1. Autenticacion

1. El usuario entra en la SPA y ve la pantalla de login/registro.
2. En login debe indicar `username`, `password` y `subject_code`.
3. En registro publico se crea siempre una cuenta `student` con una o varias `subject_codes` ya existentes.
4. El frontend llama a `POST /auth/login` o `POST /auth/register`.
5. El backend consulta o inserta usuarios en Postgres usando `DATABASE_URL`.
6. El backend devuelve un JWT, `user_id`, `role`, `subject_code` activo y `subject_codes`.
7. El frontend guarda esos datos en `localStorage`.
8. Socket.IO se conecta a `/message` enviando el token en `auth`.
9. Al conectar, el backend devuelve el historial persistido del usuario para esa asignatura activa.
10. Desde la UI, el usuario autenticado puede vincular asignaturas existentes con `POST /auth/subjects`.
11. El profesorado puede crear asignaturas nuevas con `POST /auth/teacher/subjects`, indicando un limite opcional de alumnos.
12. Desde ese mismo panel puede cambiar la asignatura activa pulsando una de las asignaturas disponibles; el frontend pide un nuevo JWT con `POST /auth/switch-subject` y reconecta el socket con el nuevo contexto.

### 2. Chat

```text
Usuario autenticado escribe texto o envia audio
    -> client_message / audio_stream_* (Socket.IO)
        -> state_machine.py
            -> Google STT (solo si hay audio)
            -> services/cloud/server.py
                -> OpenAI Responses API (gpt-4o-mini)
                -> Google TTS opcional segun el altavoz del chat
                    -> robot_message / transcription_result (Socket.IO)
                        -> UI muestra la transcripcion y la respuesta
```

1. El usuario envia un mensaje escrito o pulsa el boton de microfono del chat.
2. El frontend emite `client_message` o el flujo `audio_stream_start` -> `audio_chunk` -> `audio_stream_end` al namespace `/message`.
3. El backend valida el socket con el JWT y resuelve `user_id`, `role` y `subject_code`.
4. Si el mensaje es de audio, `google_api.py` lo transcribe con Google Cloud STT y el frontend recibe `transcription_result` para pintar lo que se ha entendido.
5. `state_machine.py` marca al usuario como `processing_query`.
6. `openai_api.py` carga desde Postgres el historial del usuario para la asignatura activa y envia ese contexto mas el nuevo mensaje a OpenAI.
7. Si el usuario autenticado es `teacher`, el backend anade como contexto interno los historiales completos del alumnado de esa misma asignatura para que el modelo pueda analizarlos.
8. Ese contexto docente solo se usa en el prompt interno: la UI del profesor no muestra los chats crudos del alumnado.
9. La respuesta vuelve como `robot_message` con `text`, `state` y, solo si el altavoz esta activado, `audio`.
10. El backend persiste en Postgres el mensaje del usuario y la respuesta del asistente asociados a `user_id` y `subject_code`.
11. El frontend actualiza el chat, la expresion visual del robot y reproduce el audio si el TTS esta habilitado.
12. El backend emite `state_update` con `idle`.

## Persistencia y estado

- Usuarios: se almacenan en Postgres usando la variable `DATABASE_URL`.
- Tabla de usuarios: `users(username, password_hash, role, created_at)`.
- Tabla de asignaturas: `subjects(code, created_by, max_students, created_at)`.
- Relacion usuario-asignatura: `user_subjects(user_id, subject_code, created_at)`.
- Tabla de conversaciones: `chat_messages(id, user_id, subject_code, role, content, created_at)`.
- Sesion web: el frontend guarda `auth_token`, `auth_user_id`, `auth_user_role`, `auth_subject_code` y `auth_subject_codes` en `localStorage`.
- Conversaciones: se guardan en Postgres por `user_id` y `subject_code`.
- Reinicio del servidor: tanto los usuarios como el historial de chat persisten.

El backend crea automaticamente las tablas `users`, `subjects`, `user_subjects` y `chat_messages` al arrancar si todavia no existen, incluyendo columnas, constraints e indices nuevos cuando la base ya existia.

## API HTTP

| Metodo | Ruta | Uso |
|---|---|---|
| `POST` | `/auth/login` | Inicia sesion y devuelve `{ token, user_id, role, subject_code, subject_codes }` |
| `POST` | `/auth/register` | Registra un alumno y devuelve `{ token, user_id, role, subject_code, subject_codes }` |
| `POST` | `/auth/subjects` | Vincula asignaturas existentes al usuario autenticado y devuelve la lista actualizada |
| `POST` | `/auth/teacher/subjects` | Crea una asignatura nueva como profesor y la vincula a su cuenta |
| `POST` | `/auth/switch-subject` | Cambia la asignatura activa del usuario autenticado y devuelve un nuevo JWT |
| `GET` | `/health` | Devuelve `{ status, active_queries }` |
| `GET` | `/*` | Sirve la SPA de React en produccion |

### Ejemplo de login

```json
{
  "username": "alice",
  "password": "mipassword",
  "subject_code": "mat101"
}
```

Respuesta:

```json
{
  "token": "<jwt>",
  "user_id": "alice",
  "role": "student",
  "subject_code": "mat101",
  "subject_codes": ["mat101", "mat102"]
}
```

### Ejemplo de registro

```json
{
  "username": "alice",
  "password": "mipassword",
  "subject_codes": ["mat101", "mat102"]
}
```

### Ejemplo para vincular asignaturas existentes desde la UI o HTTP

Cabecera:

```http
Authorization: Bearer <jwt>
```

Body:

```json
{
  "subject_codes": ["mat103", "mat104"]
}
```

### Ejemplo para crear una asignatura como profesor

Cabecera:

```http
Authorization: Bearer <jwt>
```

Body:

```json
{
  "subject_code": "mat105",
  "max_students": 30
}
```

### Ejemplo para cambiar de asignatura activa

Cabecera:

```http
Authorization: Bearer <jwt>
```

Body:

```json
{
  "subject_code": "mat102"
}
```

## Contrato Socket.IO

Namespace activo: `/message`

### Conexion

El cliente debe conectarse enviando el JWT en la opcion `auth`:

```js
io("/message", {
  auth: { token: "<jwt>" }
})
```

Si el token es invalido o ha expirado, el servidor rechaza la conexion.

### Eventos recibidos del frontend

| Evento | Payload | Descripcion |
|---|---|---|
| `client_message` | `{ type, text }` o `{ type: "audio", data }` | Mensaje de texto o audio enviado en bloque |
| `audio_stream_start` | `{}` | Inicio de una grabacion PCM LINEAR16 |
| `audio_chunk` | `{ data }` | Chunk PCM codificado en base64 |
| `audio_stream_end` | `{}` | Fin de la grabacion y envio a STT |
| `tts_preference` | `{ enabled }` | Preferencia actual del altavoz del chat |

### Eventos emitidos por el backend

| Evento | Payload | Descripcion |
|---|---|---|
| `registration_success` | `{ status, user_id, role, subject_code }` | Confirmacion de conexion autenticada |
| `conversation_history` | `{ messages }` | Historial persistido del usuario para repintar el chat |
| `robot_message` | `{ text, state, audio? }` | Respuesta del asistente, con audio opcional |
| `transcription_result` | `{ text }` | Texto transcrito a partir del audio del usuario |
| `state_update` | `{ state }` | Estado operativo del usuario en curso |

### Estados operativos

| Estado | Significado |
|---|---|
| `idle` | Esperando una nueva consulta |
| `recording` | El usuario esta grabando audio |
| `processing_query` | Llamada al modelo en curso |

## Variables de entorno

```env
OPENAI_API_KEY=...
DATABASE_URL=postgresql://...      # Cadena de conexion Postgres, por ejemplo Neon
FLASK_SECRET_KEY=...               # Opcional, por defecto: shara-woz-secret
JWT_SECRET=...                     # Muy recomendable en produccion
JWT_EXPIRY_HOURS=8                 # Opcional, por defecto: 8
GOOGLE_CLIENT_EMAIL=...            # Opcion 1 para credenciales de Google Cloud
GOOGLE_PRIVATE_KEY=...             # Opcion 1 para credenciales de Google Cloud
GOOGLE_PROJECT_ID=...              # Opcion 1 para credenciales de Google Cloud
GOOGLE_APPLICATION_CREDENTIALS=... # Opcion 2: JSON completo o ruta a fichero
PORT=8081                          # Opcional, por defecto: 8081
```

`DATABASE_URL` es obligatoria para la autenticacion y la persistencia de usuarios, asignaturas y conversaciones.
Las credenciales de Google Cloud son necesarias para el envio de audio y para la reproduccion TTS.

## Requisitos

- Python `3.10` o `3.11`
- Node.js `20+`
- Yarn
- OpenAI API key
- Credenciales de Google Cloud Speech/Text-to-Speech si se quiere usar audio
- Una base de datos Postgres accesible desde el backend

## Desarrollo local

### Con Docker

```bash
docker build -t pi-chatshara .
docker run --env-file .env -p 8081:8081 pi-chatshara
```

La aplicacion queda disponible en `http://localhost:8081`.

### Con dos procesos

#### Backend Flask

```bash
cd src/server_flask
python -m venv .venv
source .venv/bin/activate
# En PowerShell: .\.venv\Scripts\Activate.ps1
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
- `src/web/src/config.js` apunta automaticamente a `http://localhost:8081` cuando `import.meta.env.PROD` es `false`

## Gestion de usuarios

### Registro web

- El registro desde la interfaz web crea siempre cuentas `student`.
- Durante el registro se pueden indicar una o varias asignaturas existentes.
- Una vez autenticado, cualquier usuario puede vincular asignaturas existentes desde el panel del chat.
- El profesorado puede crear asignaturas nuevas desde ese panel e indicar un limite opcional de alumnos.
- Desde ese mismo panel se puede cambiar la asignatura activa sin cerrar sesion.

### CLI

Ademas del registro desde la interfaz web, se pueden crear o actualizar usuarios desde la CLI:

```bash
cd src/server_flask
python create_user.py <usuario> <contrasena> [student|teacher] <subject_codes>
```

Ejemplo:

```bash
python create_user.py profesor1 shara2024 teacher mat101,mat102
python create_user.py alumno1 mipassword mat101
```

Notas:

- Si el usuario ya existe, el script actualiza su password y su rol.
- Para usuarios `student`, las asignaturas indicadas deben existir y respetar el limite de alumnos.
- Para usuarios `teacher`, las asignaturas indicadas se crean si no existen y se vinculan a su cuenta.
- Es el flujo recomendado para crear cuentas `teacher`.

## Migracion desde users.json

Si todavia tienes un fichero legacy `files/users.json`, puedes importarlo a Postgres:

```bash
cd src/server_flask
python migrate_users_json.py
```

O indicando una ruta concreta:

```bash
python migrate_users_json.py C:\ruta\users.json
```

El script hace upsert sobre la tabla `users`, asi que sirve tanto para importar como para resincronizar hashes.

## Despliegue en Render

- `render.yaml` define un unico servicio Docker llamado `shara-dt`
- El contenedor usa el `Dockerfile` de la raiz
- El frontend se construye con Vite y se copia a `src/server_flask/static`
- En produccion, frontend y backend comparten el mismo origen
- En Render debes definir `DATABASE_URL` como variable de entorno apuntando a tu Postgres externo

## Limitaciones actuales

- La interfaz recupera el historial persistido, pero no implementa aun paginacion ni borrado de conversaciones.
- La grabacion de audio depende de un navegador con soporte para `AudioWorklet`.
- El registro publico solo crea cuentas `student`; las cuentas `teacher` deben crearse por CLI o por un backoffice futuro.
- El profesorado recibe el historial del alumnado como contexto interno del modelo, pero no existe todavia una vista administrativa para navegar esos chats en bruto.
- Si el volumen de conversaciones por asignatura crece mucho, el contexto docente puede verse truncado por el modelo.
- La rama conserva algunos restos del proyecto original en dependencias y archivos auxiliares, pero el flujo activo es ya el de chat autenticado descrito arriba.

## Contexto del proyecto

Este repositorio forma parte de un Trabajo de Fin de Master desarrollado en la ESI (UCLM), Ciudad Real, España.

**Autor:** Guillermo Cubero Charco - Guillermo.Cubero@uclm.es  
**Director:** Ramon Hervás Lucas  
**Co-directora:** Laura Villa Fernández-Arroyo  
**Laboratorio:** MAmI Research Lab
