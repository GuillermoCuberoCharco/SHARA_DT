"""
    services/cloud/openai_api.py
OpenAI API wrapper for SHARA. Handles prompt loading, conversation history management,
tool calling, and response generation. Designed to work with the new OpenAI Python SDK
and the structured response format defined in the prompt.

Same code as the original OpenAI API wrapper.
"""
import json
import logging
from datetime import datetime
from openai import OpenAI
from pydantic import BaseModel, Field

from db import get_connection

client = OpenAI()
logger = logging.getLogger('OpenAI')

prev_conversation_history = []  # Conversation history from previous sessions (from DB)
current_conversation_history = []  # Conversation history from current session (in-RAM)

# Load prompt from file
def load_prompt(filename="files/shara_prompt.txt"):
    with open(filename, "r", encoding="utf-8") as file:
        return file.read().strip()

# Load function tools from file
def load_tools(filename="files/tools_config.json"):
    with open(filename, "r", encoding="utf-8") as file:
        return json.load(file)


# ── Conversation history — backed by PostgreSQL ───────────────────────────────

def load_conversation_history(username):
    """
    Load all past messages for *username* from the DB into prev_conversation_history.
    Messages are returned in chronological order (created_at ASC, id ASC).
    """
    global prev_conversation_history

    if not username:
        prev_conversation_history = []
        return

    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content
                FROM   conversation_messages
                WHERE  login_name = %s
                ORDER  BY created_at ASC, id ASC
                """,
                (username,),
            )
            rows = cur.fetchall()
        prev_conversation_history = [{'role': r[0], 'content': r[1]} for r in rows]
        logger.info('Loaded %d messages for user %s', len(prev_conversation_history), username)
    except Exception as exc:
        logger.error('Failed to load conversation history for %s: %s', username, exc)
        prev_conversation_history = []
    finally:
        if conn:
            conn.close()


def save_conversation_history(username, session_id=None):
    """
    Persist current_conversation_history to the DB under *username*.
    Each message becomes an individual row with an optional session_id
    so sessions can be reconstructed for study analysis.
    Does nothing if username is None or there are no new messages.
    """
    if not username or not current_conversation_history:
        return

    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO conversation_messages (login_name, role, content, session_id)
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (username, msg['role'], msg['content'], session_id)
                    for msg in current_conversation_history
                ],
            )
        conn.commit()
        logger.info(
            'Saved %d messages for user %s (session %s)',
            len(current_conversation_history), username, session_id,
        )
    except Exception as exc:
        if conn:
            conn.rollback()
        logger.error('Failed to save conversation history for %s: %s', username, exc)
    finally:
        if conn:
            conn.close()


def get_full_conversation_history():
    return prev_conversation_history + current_conversation_history


# Clear conversation history in-RAM (temporal context conversation)
def clear_conversation_history():
    prev_conversation_history.clear()
    current_conversation_history.clear()


shara_prompt = load_prompt()
tools = load_tools()


# JSON Schema for response format
class ResponseFormat(BaseModel):
    continue_conversation: bool = Field(alias="continue")
    robot_mood: str
    response: str

# OpenAI completion arguments configuration.
#
# IMPORTANT:
# This base config must stay immutable per request. The previous implementation
# reused a single mutable dict and appended SDK response objects from
# `responses.parse()` back into `input`.
#
# That pattern is also present in the physical robot repo, but the bug has
# manifested in SHARA_DT first because this deployment is actively exercising
# the tool-calling flow (`who_are_you_response` / `record_face`).
#
# This tool-calling bug is also present in the physical robot code path.
# SHARA_DT fixes it here because it has already manifested in this deployment.
# The behavioral flow is kept identical; only the SDK/API re-serialization bug is corrected.
#
# Why the fix is necessary:
# - SDK output items may contain parsed-only fields such as `parsed_arguments`.
# - Those fields are valid in Python objects returned by the SDK, but they are
#   NOT valid request parameters for the next `/responses` call.
# - Re-sending them causes OpenAI to reject the request with:
#   `Unknown parameter: input[n].parsed_arguments`.
# - Keeping request args local also avoids cross-request state leakage.
BASE_COMPLETION_ARGS = {
    "model": "gpt-4o-mini",
    "text_format": ResponseFormat,
    "temperature": 1,
    "top_p": 1,
    "instructions": shara_prompt,
    "truncation": "auto" # Truncate messages automatically if they exceed the model's context length
}


def _serialize_function_call_for_reinput(tool_call):
    """
    Convert a parsed SDK function_call object into a clean Responses API input item.

    This is required because SDK objects may include internal parsed-only fields
    like `parsed_arguments`. Reinjecting the raw object works until a tool call
    happens, and then the next `/responses` request fails.

    Note: the same latent bug exists in the physical robot implementation. We do
    not modify that repository here; we fix it only in SHARA_DT, where it has
    already surfaced in production usage.
    """
    return {
        "type": "function_call",
        "call_id": tool_call.call_id,
        "name": tool_call.name,
        "arguments": tool_call.arguments,
    }



def handle_tool_call(tool_call, context_data):
    ''' Tool (functions) calling handler. Process tool calls and return the result and robot action if needed '''

    tool_name = tool_call.name
    args = json.loads(tool_call.arguments)

    result = ''
    robot_action = {}

    if tool_name == "record_face" and context_data.get("proactive_question") == "who_are_you_response":
        username = args.get("username", 'Desconocido')
        if username != 'Desconocido':
            result = 'True'
            robot_action = {"action": "record_face", "username": args['username']} 
        else:
            result = 'False'
    
    elif tool_name == "set_username":
        username = args.get("username", 'Desconocido')
        if username != 'Desconocido':
            result = 'True'
            robot_action = {"action": "set_username", "username": args['username']}
        else:
            result = 'False'
    
    return result, robot_action


def build_messages(input_text, context_data):
    ''' Build messages with conversation history '''

    messages = prev_conversation_history + current_conversation_history # include previous conversation history
    user_message = {"role": "user", "content": json.dumps({**context_data,
                                                           "user_input": input_text,
                                                           "timestamp": datetime.now().strftime("%d-%m-%Y %H:%M")}, ensure_ascii=False)}

    messages.append(user_message)
    current_conversation_history.append(user_message)

    return messages


def get_tools_for_context(context_data):
    ''' Return tools to use based on context data '''
    # Filter who_are_you proactive question (avoid unnecessary record_face tool)
    pq = context_data.get("proactive_question", None)
    tools_to_use = []
    requireness = None

    if pq == "who_are_you_response":
        tools_to_use = [t for t in tools if t["name"] == "record_face"]
        requireness = "required"
    
    elif pq == "casual_ask_known_username":
        tools_to_use = [t for t in tools if t["name"] == "set_username"]
        requireness = "auto"

    return tools_to_use, requireness


def generate_response(input_text, context_data={}):
    ''' Generate response from user input, context data, and conversation history '''
    
    messages = build_messages(input_text, context_data)
    tools_to_use, requireness_tool = get_tools_for_context(context_data)

    # Create request-local completion args.
    # Do not mutate a shared global dict across requests.
    completion_args = {
        **BASE_COMPLETION_ARGS,
        "input": messages,
    }
    if tools_to_use:  # Only add 'tools' if there are tools available
        completion_args["tools"] = tools_to_use
        completion_args["tool_choice"] = requireness_tool

    robot_action = {}
    response = client.responses.parse(**completion_args)

    # Check if there is a function call in the list of response.output
    if any(item.type == "function_call" for item in response.output):
        tool_call = next(item for item in response.output if item.type == "function_call")
        result, robot_action = handle_tool_call(tool_call, context_data)

        # IMPORTANT:
        # Never append the raw SDK object returned by `responses.parse()`.
        # It may contain parsed-only fields such as `parsed_arguments`, which
        # are rejected if sent back to the API in the next request.
        messages.append(_serialize_function_call_for_reinput(tool_call))
        messages.append({                   # append function result message
            "type": "function_call_output",
            "call_id": tool_call.call_id,
            "output": result
        })

        completion_args.pop("tool_choice", None)  # Remove tools
        completion_args.pop("tools", None)

        response = client.responses.parse(**completion_args)
    
    # Get response dict from OpenAI response
    response_dict = response.output_parsed.model_dump(by_alias=True)
    
    response_text = response_dict.get("response", "").translate(str.maketrans("'", '"', '*_#'))
    
    # Add response to conversation history
    current_conversation_history.append({"role": "assistant", "content": response_text})

    # Build robot_context from parsed data (continue, robot_mood, robot_action)
    robot_context = {
        "continue": response_dict.get("continue", False),
        "robot_mood": response_dict.get("robot_mood", "neutral"),
    } | robot_action
    
    return response_text, robot_context
