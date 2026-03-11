# SHARA_DT: Digital Twin of SHARA^3

## Diferencias actuales vs Proactive Shara Robot

Este apartado compara:
- Repo robot fisico: `Proactive-Shara-Robot-main`
- Repo gemelo digital: `SHARA_DT`

### Implementado recientemente en SHARA_DT

- **Reconocimiento facial batch operativo**
  - `src/web/src/components/FaceDetection.jsx` + `src/server_flask/app.py::/api/recognize-face` + `src/server_flask/services/camera_service.py` ya implementan el flujo batch completo.
- **Semantica de reconocimiento fiel al robot**
  - El gemelo acumula reconocimientos por sesion y confirma:
    - **usuario conocido** al llegar a `3`,
    - **usuario desconocido** al llegar a `8`.
- **Paridad funcional de `record_face` / `set_username`**
  - `state_machine.py` ya mantiene `user_id`, distingue correctamente usuarios desconocidos y conecta `record_face` con la base facial del gemelo.
- **Correccion necesaria en tool calling del backend**
  - `src/server_flask/services/cloud/openai_api.py` ya no reinyecta el objeto crudo devuelto por `responses.parse()`.
  - Esta correccion es **tecnica**, no de comportamiento: preserva el flow del robot (`who_are_you_response` / `record_face`) y evita un bug de serializacion del SDK/API.
  - El mismo patron defectuoso existe en el repo del robot fisico, pero **no se modifica aqui**; en SHARA_DT ya se habia manifestado y por eso era necesario corregirlo.

### Resumen de arquitectura

- **Proactive Shara Robot (fisico)** usa una unica app Python (`main.py`) que orquesta servicios hardware: camara/presencia, wakeface, microfono, altavoz, LEDs, pantalla tactil, render de ojos local (OpenCV), y servicios cloud.
- **SHARA_DT (gemelo digital)** divide el sistema en:
  - `src/server_flask` (Flask + Socket.IO + maquina de estados + servicios cloud),
  - `src/web` (captura de camara/microfono, deteccion facial, chat UI, render de ojos).

### Metodos adaptados al gemelo digital (y justificacion)

| Metodo/modulo robot fisico | Adaptacion en SHARA_DT | Por que se tomo esta decision |
|---|---|---|
| `main.py::wf_event_handler`, `main.py::pd_event_handler` | `src/server_flask/state_machine.py::on_user_detected`, `on_user_lost` (disparados por eventos web socket) | El gemelo no tiene sensores fisicos de wakeface/presencia, asi que se emulan con eventos del navegador manteniendo la semantica de la maquina de estados. |
| `main.py::mic_event_handler` (`start_recording`/`stop_recording`) | `state_machine.py::on_audio_stream_start`, `on_audio_stream_end` + `src/web/src/components/UI/hooks/useAudioRecorder.jsx::startRecording`, `stopRecording` | Se conserva el mismo contrato de turno de voz (inicio/fin), pero capturando audio desde el navegador en vez del microfono embebido. |
| Flujo STT streaming del fisico (`main.py` + `services/mic.py`) | Pipeline PCM por lotes en `state_machine.py::_process_audio_stream_end` usando `audio_chunk` | En despliegue web/gevent reduce problemas de estabilidad con streaming gRPC y mantiene un flujo STT/LLM/TTS robusto. |
| `main.py::speaker_event_handler` (`finish_speak`) | `state_machine.py::on_tts_complete` emitido desde `src/web/src/components/UI/UI.jsx::handleRobotMessage` | En el gemelo, el fin de habla lo confirma el reproductor del navegador, no un callback del altavoz fisico. |
| `main.py::process_transition` | `src/server_flask/state_machine.py::process_transition` (transiciones simplificadas sin hardware) | Se mantiene la logica de estados conversacionales eliminando dependencias directas de actuadores fisicos. |
| `main.py::proactive_service_event_handler` + `services/proactive_service.py::update` | `state_machine.py::proactive_event_handler` + `src/server_flask/proactive_service.py::update` | Se mantiene la proactividad, pero ahora se dispara por eventos web y timers/cooldown en lugar de sensores de sala. |
| `services/camera_services.py::{Wakeface,FaceDB,RecordFace}` | `src/web/src/components/FaceDetection.jsx` + `src/server_flask/services/camera_service.py` + `src/server_flask/app.py::/api/recognize-face` | El gemelo sustituye la camara embebida por batches de frames del navegador, pero conserva la semantica de decision: 3 reconocimientos para conocido y 8 para desconocido, con persistencia posterior de `record_face`. |
| `services/eyes/service.py::set` (dibujado/cache/parpadeo OpenCV) | `src/server_flask/eyes/service.py::set` emite `set_face`; render en `src/web/src/components/RobotView.jsx` | La logica de estado emocional sigue en servidor, pero el render se mueve al frontend para simular la pantalla del robot en browser. |
| `services/cloud/server.py::{query,query_with_text,proactive_query,load_conversation_db,dump_conversation_db}` | Mismos metodos en `src/server_flask/services/cloud/server.py` (casi sin cambios) | Maximiza fidelidad reutilizando la logica de conversacion del robot fisico con minimas modificaciones. |
| `services/cloud/openai_api.py::{generate_response,build_messages,get_tools_for_context,...}` | Mismo set de metodos en `src/server_flask/services/cloud/openai_api.py` + correccion de reserializacion en tool calling | Preserva prompt, herramientas y politica conversacional del robot fisico. La unica desviacion deliberada es una correccion tecnica para no reenviar objetos parseados del SDK con campos no validos como `parsed_arguments`. |
| `services/cloud/google_api.py::{speech_to_text,text_to_speech,...}` | Mismo set de metodos + `_build_credentials` en `src/server_flask/services/cloud/google_api.py` | Mantiene STT/TTS y agrega autenticacion cloud apta para despliegues (Render/env vars). |

### Nivel de reutilizacion (fidelidad al fisico)

- **Reutilizacion alta (casi 1:1):** `services/cloud/server.py`, `services/cloud/openai_api.py`.
- **Reutilizacion media (mismos metodos, adaptacion de despliegue):** `services/cloud/google_api.py`, `services/proactive_service.py`.
- **Alta adaptacion (obligatoria por arquitectura de gemelo):** `main.py` -> `state_machine.py` + handlers Socket.IO + hooks de frontend.

### Elementos que faltan para completar el gemelo

Para que SHARA_DT sea lo mas fiel posible al robot fisico, faltan estos puntos:

1. **Capa equivalente de servicios hardware**
   - No existen equivalentes completos de `services/camera_services.py` (`Wakeface`, `RecordFace`, `PresenceDetector`), `services/mic.py`, `services/speaker.py`, `services/leds.py`, `services/touchscreen.py`.
2. **Paridad incompleta de `RecordFace` respecto al robot fisico**
   - El robot fisico graba nuevos encodings desde camara dedicada y genera augmentations antes de persistir.
   - SHARA_DT reutiliza los descriptores ya capturados en el flujo batch web; funcionalmente resuelve `record_face`, pero no replica 1:1 el pipeline de captura/augmentacion del fisico.
3. **Paridad parcial de maquina de estados**
   - Faltan o estan fusionadas transiciones del fisico como `listening_without_cam`, `recording_face`, y timeout de inactividad (`listen_timeout_handler`).
4. **Paridad incompleta del canal de video**
   - `src/server_flask/sockets/video_handler.py::on_video_frame` actualmente descarta frames (`pass`) y no los procesa.
5. **Ruta proactiva por presencia no cableada end-to-end**
   - Existe `ProactiveService.update('sensor', 'presence', ...)`, pero hoy no recibe eventos del frontend.
6. **Limpieza pendiente de nombres de base de conversacion**
   - SHARA_DT incluye `files/conversation_db.json`, mientras modulos cloud referencian `files/conversations_db.json` y `files/conversations_unknown_db.json`.
7. **Faltan pruebas de paridad operacional**
   - No hay tests automaticos que comparen transiciones de estado y decisiones de herramientas/acciones entre fisico y gemelo ante las mismas trazas.
8. **Bug latente equivalente en el repo fisico no reflejado en codigo compartido**
   - El patron original de tool calling del robot fisico sigue reinyectando objetos parseados del SDK.
   - En SHARA_DT ya se ha corregido por necesidad operativa, pero la divergencia sigue existiendo porque el repo fisico no debe modificarse aqui.

## Contributing

Contributions are welcome. Please:

1. Fork the repository.
2. Create a branch for your feature (`git checkout -b feature/new-feature`).
3. Make your changes and commit (`git commit -m 'Add new feature'`).
4. Push to the branch (`git push origin feature/new-feature`).
5. Open a Pull Request.

## License

[MIT](https://choosealicense.com/licenses/mit/)

## Contact

Guillermo Cubero Charco  
Guillermo.Cubero@uclm.es

This project is part of a Final Master Project carried out at the ESI (UCLM), Ciudad Real, Spain.

## Acknowledgments

- Ramon Hervas Lucas (Advisor).
- Laura Villa Fernandez-Arroyo (Co-advisor).
- MAmI Research Lab research group.
- International panel of HRI experts for their evaluation and feedback.
