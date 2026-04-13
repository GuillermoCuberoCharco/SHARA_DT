"""
services/cloud/openai_api.py

OpenAI API wrapper. Maintains a separate conversation history per user
persisted in Postgres.
"""

from openai import OpenAI
from pydantic import BaseModel, Field

from db import ensure_schema, get_db_connection
from subject_codes import normalize_subject_code
from user_roles import STUDENT_USER_ROLE, is_teacher_role

client = OpenAI()

SYSTEM_PROMPT_FILE = "files/shara_prompt.txt"
TEACHER_SYSTEM_PROMPT_SUFFIX = """

INSTRUCCIONES ADICIONALES CUANDO HABLAS CON UNA PERSONA PROFESORA:
- Este chat pertenece a profesorado, no a alumnado.
- Manten el historial propio de este profesor separado del historial de los alumnos.
- Recibiras como contexto interno los historiales completos de chat del alumnado.
- Analiza tu esos historiales para responder al profesor.
- No inventes informacion que no este en esos historiales.
- Si el contexto del alumnado no es suficiente para afirmar algo con claridad, dilo de forma honesta.
"""
TEACHER_CONTEXT_PREFIX = """
CONTEXTO PRIVADO DEL ALUMNADO PARA USO INTERNO.
Los historiales completos del alumnado aparecen a continuacion.
Usalos para analizar tendencias, dudas comunes y respuestas previas del asistente.
""".strip()


def load_prompt(filename=SYSTEM_PROMPT_FILE):
    try:
        with open(filename, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        return "Eres un asistente conversacional util y amigable."


system_prompt = load_prompt()


class ResponseFormat(BaseModel):
    robot_mood: str = Field(default="neutral")
    response: str


def _load_user_history(user_id: str, subject_code: str) -> list[dict[str, str]]:
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select role, content
                from chat_messages
                where user_id = %s and subject_code = %s
                order by created_at asc, id asc
                """,
                (user_id, normalize_subject_code(subject_code)),
            )
            return [
                {"role": row["role"], "content": row["content"]}
                for row in cur.fetchall()
            ]


def _store_message(user_id: str, subject_code: str, role: str, content: str):
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into chat_messages (user_id, subject_code, role, content)
                values (%s, %s, %s, %s)
                """,
                (user_id, normalize_subject_code(subject_code), role, content),
            )


def _load_student_chat_messages(subject_code: str) -> list[dict]:
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select m.user_id, m.role, m.content
                from chat_messages m
                join users u on u.username = m.user_id
                where u.role = %s
                  and m.subject_code = %s
                  and m.role in ('user', 'assistant')
                order by m.user_id asc, m.created_at asc, m.id asc
                """,
                (STUDENT_USER_ROLE, normalize_subject_code(subject_code)),
            )
            return list(cur.fetchall())


def _build_teacher_private_context(subject_code: str) -> str:
    student_messages = _load_student_chat_messages(subject_code)

    if not student_messages:
        return (
            f"{TEACHER_CONTEXT_PREFIX}\n"
            f"- No hay mensajes de alumnos disponibles todavia para la asignatura {normalize_subject_code(subject_code)}."
        )

    context_lines = [
        TEACHER_CONTEXT_PREFIX,
        f"[Asignatura activa: {normalize_subject_code(subject_code)}]",
        "",
    ]
    current_user_id = None

    for item in student_messages:
        user_id = (item.get("user_id") or "").strip()
        content = (item.get("content") or "").strip()
        if not user_id or not content:
            continue

        if user_id != current_user_id:
            if current_user_id is not None:
                context_lines.append("")
            current_user_id = user_id
            context_lines.append(f"[Historial completo de {user_id}]")

        speaker = "Alumno" if item.get("role") == "user" else "Asistente"
        context_lines.append(f"{speaker}: {content}")

    return "\n".join(context_lines)


def load_user_messages(user_id: str, subject_code: str) -> list[dict[str, str]]:
    """
    Return a user's persisted conversation in frontend-friendly format.
    """
    history = _load_user_history(user_id, subject_code)
    messages = []
    for item in history:
        sender = "client" if item["role"] == "user" else "robot"
        messages.append({"text": item["content"], "sender": sender})
    return messages


def _build_instructions(user_role: str) -> str:
    if is_teacher_role(user_role):
        return f"{system_prompt}\n{TEACHER_SYSTEM_PROMPT_SUFFIX}".strip()
    return system_prompt


def _build_history_snapshot(user_id: str, input_text: str, user_role: str, subject_code: str) -> list[dict[str, str]]:
    history_snapshot = _load_user_history(user_id, subject_code)

    if is_teacher_role(user_role):
        teacher_context = _build_teacher_private_context(subject_code)
        if teacher_context:
            history_snapshot = [{"role": "developer", "content": teacher_context}, *history_snapshot]

    history_snapshot.append({"role": "user", "content": input_text})
    return history_snapshot


def generate_response(
    input_text: str,
    user_id: str,
    user_role: str = STUDENT_USER_ROLE,
    subject_code: str = "",
) -> tuple[str, str]:
    """
    Generate a response from OpenAI for the given user.
    Each user maintains an independent conversation history persisted in Postgres.

    Returns:
        (response_text, robot_mood)
    """
    history_snapshot = _build_history_snapshot(user_id, input_text, user_role, subject_code)

    completion_args = {
        "model": "gpt-4o-mini",
        "text_format": ResponseFormat,
        "temperature": 1,
        "top_p": 1,
        "instructions": _build_instructions(user_role),
        "input": history_snapshot,
        "truncation": "auto",
    }

    response = client.responses.parse(**completion_args)
    parsed = response.output_parsed

    response_text = parsed.response.translate(str.maketrans("'", '"', '*_#'))
    robot_mood = parsed.robot_mood or "neutral"

    _store_message(user_id, subject_code, "user", input_text)
    _store_message(user_id, subject_code, "assistant", response_text)

    return response_text, robot_mood


def clear_user_history(user_id: str, subject_code: str | None = None):
    """Remove the persisted conversation history for a specific user."""
    ensure_schema()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if subject_code:
                cur.execute(
                    """
                    delete from chat_messages
                    where user_id = %s and subject_code = %s
                    """,
                    (user_id, normalize_subject_code(subject_code)),
                )
            else:
                cur.execute(
                    """
                    delete from chat_messages
                    where user_id = %s
                    """,
                    (user_id,),
                )
