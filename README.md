# PI-ChatShara

PI-ChatShara es una variante de SHARA_DT centrada en una interfaz de chat de texto con autenticacion de usuario. La aplicacion se ejecuta como un unico servicio: Flask sirve la SPA de React, mantiene el canal Socket.IO y orquesta las llamadas a OpenAI.

## Estado actual

La rama `PI-ChatShara` implementa actualmente:

- Login y registro de usuarios con JWT.
- Conexion Socket.IO autenticada en el namespace `/message`.
- Persistencia de usuarios y conversaciones en Postgres a traves de `DATABASE_URL`.
- Recuperacion automatica del historial de chat al reconectar.
- Interfaz web de chat con estado de conexion y espera.
- Vista visual del robot con ojos animados y anillo LED.

La aplicacion ya no usa audio, reconocimiento facial ni comportamiento proactivo. El foco actual es una experiencia de chat web autenticada con persistencia fuera del filesystem efimero de Render.

## Arquitectura

```text
PI-ChatShara
|-- src/server_flask
|   |-- app.py                      # Flask, Socket.IO, SPA y bootstrap de DB
|   |-- db.py                       # Conexion Postgres + autocreacion de schema
|   |-- auth.py                     # Login, registro, emision y verificacion de JWT
|   |-- create_user.py              # Utilidad CLI para crear usuarios en Postgres
|   |-- migrate_users_json.py       # Importa usuarios legacy desde users.json
|   |-- state_machine.py            # Estado por usuario y ejecucion de consultas
|   |-- sockets/message_handler.py  # Namespace /message autenticado
|   `-- services/cloud
|       |-- server.py               # Pipeline de consulta al modelo
|       `-- openai_api.py           # Historial por usuario y llamada a OpenAI
`-- src/web
    |-- src/App.jsx
    |-- src/auth
    |   |-- Login.jsx               # Pantalla de login/registro
    |   `-- useAuth.js              # Sesion en localStorage
    |-- src/contexts/WebSocketContext.jsx
    `-- src/components
        |-- RobotView.jsx           # Imagen del robot, ojos y LED
        `-- UI
            |-- UI.jsx              # Estado del chat
            `-- subcomponents/ChatWindow.jsx
```

## Flujo de funcionamiento

### 1. Autenticacion

1. El usuario entra en la SPA y ve la pantalla de login/registro.
2. El frontend llama a `POST /auth/login` o `POST /auth/register`.
3. El backend consulta o inserta usuarios en Postgres usando `DATABASE_URL`.
4. El backend devuelve un JWT y el `user_id`.
5. El frontend guarda ambos datos en `localStorage`.
6. Socket.IO se conecta a `/message` enviando el token en `auth`.
7. Al conectar, el backend devuelve el historial persistido del usuario.

### 2. Chat

```text
Usuario autenticado escribe texto
    -> client_message (Socket.IO)
        -> state_machine.on_text_message()
            -> services/cloud/server.py
                -> OpenAI Responses API (gpt-4o-mini)
                    -> robot_message (Socket.IO)
                        -> UI muestra la respuesta
```

1. El usuario envia un mensaje desde el chat.
2. El frontend emite `client_message` al namespace `/message`.
3. El backend valida el socket con el JWT y resuelve el `user_id`.
4. `state_machine.py` marca al usuario como `processing_query`.
5. `openai_api.py` carga desde Postgres el historial de ese usuario y envia ese contexto mas el nuevo mensaje a OpenAI.
6. La respuesta vuelve como `robot_message` con `text` y `state`.
7. El backend persiste en Postgres el mensaje del usuario y la respuesta del asistente.
8. El frontend actualiza el chat y la expresion visual del robot.
9. El backend emite `state_update` con `idle`.

## Persistencia y estado

- Usuarios: se almacenan en Postgres usando la variable `DATABASE_URL`.
- Tabla de usuarios: `users(username, password_hash, created_at)`.
- Tabla de conversaciones: `chat_messages(id, user_id, role, content, created_at)`.
- Sesion web: el frontend guarda `auth_token` y `auth_user_id` en `localStorage`.
- Conversaciones: se guardan en Postgres por `user_id`.
- Reinicio del servidor: tanto los usuarios como el historial de chat persisten.

El backend crea automaticamente las tablas `users` y `chat_messages` al arrancar si todavia no existen.

## API HTTP

| Metodo | Ruta | Uso |
|---|---|---|
| `POST` | `/auth/login` | Inicia sesion y devuelve `{ token, user_id }` |
| `POST` | `/auth/register` | Registra usuario y devuelve `{ token, user_id }` |
| `GET` | `/health` | Devuelve `{ status, active_queries }` |
| `GET` | `/*` | Sirve la SPA de React en produccion |

### Ejemplo de login

```json
{
  "username": "alice",
  "password": "mipassword"
}
```

Respuesta:

```json
{
  "token": "<jwt>",
  "user_id": "alice"
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
| `client_message` | `{ type, text }` | Mensaje de texto del usuario |

### Eventos emitidos por el backend

| Evento | Payload | Descripcion |
|---|---|---|
| `registration_success` | `{ status, user_id }` | Confirmacion de conexion autenticada |
| `conversation_history` | `{ messages }` | Historial persistido del usuario para repintar el chat |
| `robot_message` | `{ text, state }` | Respuesta del asistente |
| `state_update` | `{ state }` | Estado operativo del usuario en curso |

### Estados operativos

| Estado | Significado |
|---|---|
| `idle` | Esperando una nueva consulta |
| `processing_query` | Llamada al modelo en curso |

## Variables de entorno

```env
OPENAI_API_KEY=...
DATABASE_URL=postgresql://...      # Cadena de conexion Postgres, por ejemplo Neon
FLASK_SECRET_KEY=...               # Opcional, por defecto: shara-woz-secret
JWT_SECRET=...                     # Muy recomendable en produccion
JWT_EXPIRY_HOURS=8                 # Opcional, por defecto: 8
PORT=8081                          # Opcional, por defecto: 8081
```

`DATABASE_URL` es obligatoria para la autenticacion y la persistencia de usuarios y conversaciones.

## Requisitos

- Python `3.10` o `3.11`
- Node.js `20+`
- Yarn
- OpenAI API key
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

Ademas del registro desde la interfaz web, se pueden crear usuarios desde la CLI:

```bash
cd src/server_flask
python create_user.py <usuario> <contrasena>
```

Ejemplo:

```bash
python create_user.py admin shara2024
```

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
- La gestion de usuarios ya no depende del filesystem local, pero sigue siendo una autenticacion sencilla sobre una sola tabla principal de usuarios.
- La rama conserva algunos restos del proyecto original en dependencias y archivos auxiliares, pero el flujo activo es ya el de chat autenticado descrito arriba.

## Contexto del proyecto

Este repositorio forma parte de un Trabajo de Fin de Master desarrollado en la ESI (UCLM), Ciudad Real, Espana.

**Autor:** Guillermo Cubero Charco - Guillermo.Cubero@uclm.es  
**Director:** Ramon Hervas Lucas  
**Co-directora:** Laura Villa Fernandez-Arroyo  
**Laboratorio:** MAmI Research Lab
