import json
import subprocess
import os
import sys
import logging
import re
import shlex
from typing import List, Tuple
import threading
import webbrowser
import time
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from groq import Groq as g

# ==========================
# RESOURCE PATH (PyInstaller)
# ==========================
def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# ==========================
# FLASK APP INIT
# ==========================
app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static"),
)

# ==========================
# LOGGING SETUP
# ==========================
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ==========================
# CONSTANTS
# ==========================
MODEL = "llama-3.3-70b-versatile"
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".dadarzz_config.json")

COMMANDS = [
    "ls", "pwd", "whoami", "date", "cal", "echo",
    "mkdir", "touch", "cat", "head", "tail", "wc",
    "uname", "uptime", "df", "du", "open", "which",
    "id", "rm", "mv", "find"
]

ALLOWED_DIRECTORIES = {
    "Desktop": os.path.expanduser("~/Desktop"),
    "Documents": os.path.expanduser("~/Documents"),
    "Downloads": os.path.expanduser("~/Downloads"),
}

SYSTEM_PROMPT = """You are Dadarzz Agent, a smart macOS assistant that can both chat and execute terminal commands.

You have two response modes — pick the right one based on the user's intent:

MODE 1 — Terminal task (moving files, organizing folders, checking disk, etc):
First recon if needed:
{ "recon": "shell command to inspect filesystem" }
Then execute:
{ "command": "shell command to run" }

MODE 2 — Normal conversation (questions, explanations, greetings, etc):
{ "chat": "your friendly response here" }

RULES:
- ALWAYS respond with ONLY a JSON object. Never plain text, never markdown.
- If the user is just chatting, asking questions, or saying hi — use "chat" mode.
- If the user wants something done on their Mac — use "recon" then "command" mode.
- You have memory of the full conversation, so refer back to it naturally."""

client = None
conversation_history = []
MAX_HISTORY_MESSAGES = 24
CONTEXT_TOKEN_WARN_AT = 5000
CONTEXT_TOKEN_HARD_LIMIT = 6500

# ==========================
# JSON PARSING HELPER
# ==========================
def _repair_invalid_json_escapes(json_str: str) -> str:
    """
    Repair invalid escape sequences inside JSON strings.
    - "\\ " becomes " " for shell-escaped spaces.
    - Unknown escapes like "\\D" become "\\\\D" to preserve literal backslash.
    """
    valid_escapes = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}
    out = []
    in_string = False
    i = 0

    while i < len(json_str):
        ch = json_str[i]

        if ch == '"':
            # Count preceding backslashes to detect escaped quote
            backslashes = 0
            j = i - 1
            while j >= 0 and json_str[j] == "\\":
                backslashes += 1
                j -= 1
            if backslashes % 2 == 0:
                in_string = not in_string
            out.append(ch)
            i += 1
            continue

        if in_string and ch == "\\" and i + 1 < len(json_str):
            nxt = json_str[i + 1]
            if nxt == " ":
                # Convert shell-escaped spaces to literal spaces for JSON validity.
                out.append(" ")
                i += 2
                continue
            if nxt not in valid_escapes:
                out.append("\\\\")
                out.append(nxt)
                i += 2
                continue

        out.append(ch)
        i += 1

    return "".join(out)

def safe_json_parse(json_str):
    """Safely parse JSON from LLM response handling literal backslashes."""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        fixed = _repair_invalid_json_escapes(json_str)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            # If still failing, raise the original error
            raise

def estimate_message_tokens(messages: List[dict]) -> int:
    """Very rough token estimate to prevent context overflow."""
    total_chars = len(SYSTEM_PROMPT)
    for msg in messages:
        total_chars += len(msg.get("content", "")) + 16
    return max(1, total_chars // 4)

def trim_conversation_history() -> bool:
    """
    Trim oldest messages if conversation grows too large.
    Returns True if trimming occurred.
    """
    global conversation_history
    trimmed = False
    while (
        len(conversation_history) > MAX_HISTORY_MESSAGES
        or estimate_message_tokens(conversation_history) > CONTEXT_TOKEN_HARD_LIMIT
    ):
        if not conversation_history:
            break
        conversation_history.pop(0)
        trimmed = True
    return trimmed

def extract_first_json_object(text):
    """Return first balanced JSON object from text, respecting quoted strings."""
    start = text.find("{")
    if start == -1:
        return None

    in_string = False
    escaped = False
    depth = 0

    for i in range(start, len(text)):
        ch = text[i]

        if escaped:
            escaped = False
            continue

        if ch == "\\":
            escaped = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None

# ==========================
# API KEY MANAGEMENT
# ==========================
def load_api_key():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f).get("api_key")
    return None

def save_api_key(api_key):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"api_key": api_key}, f)

def init_client(api_key):
    global client
    client = g(api_key=api_key)
    log.info("Groq client initialized.")

# ==========================
# EXECUTION
# ==========================
def detect_organization_intent(user_input: str) -> bool:
    """
    Detect if user wants to organize/sort/clean files.
    """
    keywords = ["organize", "sort", "clean", "arrange", "tidy", "structure"]
    user_lower = user_input.lower()
    return any(keyword in user_lower for keyword in keywords)

def requires_confirmation(command: str) -> bool:
    """
    Detect if a shell command contains dangerous operations
    like rm or mv anywhere in chained commands.
    """
    # Split by common shell chain operators
    parts = re.split(r"\s*(?:&&|\|\||;)\s*", command)

    for part in parts:
        tokens = part.strip().split()
        if not tokens:
            continue
        if tokens[0] in ["rm", "mv"]:
            return True

    return False

def is_path_allowed(path: str) -> bool:
    """
    Check if a path is within ALLOWED_DIRECTORIES.
    """
    abs_path = os.path.abspath(os.path.expanduser(path))
    for allowed_dir in ALLOWED_DIRECTORIES.values():
        allowed_abs = os.path.abspath(allowed_dir)
        if abs_path.startswith(allowed_abs):
            return True
    return False

def execution(command):
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as e:
        return f"Error: Invalid command syntax ({str(e)})."

    first_cmd = tokens[0] if tokens else ""
    if not first_cmd:
        return "Error: Empty command."
    if first_cmd not in COMMANDS:
        return f"Error: Command '{first_cmd}' not allowed."
    
    # Validate that paths in command are within allowed directories
    for token in tokens:
        if "/" in token or "./" in token or "~/" in token:
            if not is_path_allowed(token):
                return f"Error: Access to '{token}' is not allowed."
    
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
            text=True, executable="/bin/zsh"
        )
        return result.stdout if result.stdout else result.stderr
    except Exception as e:
        return f"Error: {str(e)}"

# ==========================
# LLM
# ==========================
def ask_llm(user_message) -> Tuple[str, List[str]]:
    conversation_history.append({"role": "user", "content": user_message})
    warnings = []
    if trim_conversation_history():
        warnings.append(
            "Older messages were trimmed to avoid model context overflow."
        )

    current_tokens = estimate_message_tokens(conversation_history)
    if current_tokens >= CONTEXT_TOKEN_WARN_AT:
        warnings.append(
            "Conversation is getting long. If responses degrade, clear memory and continue."
        )

    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *conversation_history
            ],
            temperature=0.3
        )
        response = completion.choices[0].message.content.strip()
        conversation_history.append({"role": "assistant", "content": response})
        return response, warnings
    except Exception:
        conversation_history.pop()
        raise

# ==========================
# FLASK ROUTES
# ==========================
@app.route("/")
def index():
    api_key = load_api_key()
    return render_template("index.html", has_api_key=bool(api_key))

@app.route("/api/set-key", methods=["POST"])
def set_key():
    data = request.get_json()
    api_key = data.get("api_key", "").strip()
    if not api_key:
        return jsonify({"error": "API key is required."}), 400
    save_api_key(api_key)
    init_client(api_key)
    return jsonify({"ok": True})

@app.route("/api/chat", methods=["POST"])
def chat():
    global client
    if client is None:
        api_key = load_api_key()
        if api_key:
            init_client(api_key)
        else:
            return jsonify({"error": "No API key configured."}), 401

    data = request.get_json()
    user_input = data.get("message", "").strip()
    if not user_input:
        return jsonify({"error": "Empty message."}), 400

    try:
        ai_response, warnings = ask_llm(user_input)
        json_candidate = extract_first_json_object(ai_response)
        warning_events = [{"type": "info", "content": w} for w in warnings]

        if not json_candidate:
            return jsonify({"events": warning_events + [{"type": "chat", "content": ai_response}]})

        try:
            payload = safe_json_parse(json_candidate)
        except json.JSONDecodeError:
            log.warning("Could not parse model JSON payload: %s", json_candidate)
            return jsonify({"events": warning_events + [{"type": "chat", "content": ai_response}]})
        events = []
        events.extend(warning_events)

        if "chat" in payload:
            events.append({"type": "chat", "content": payload["chat"]})

        elif detect_organization_intent(user_input):
            events.append({
                "type": "choose",
                "content": "Which folder would you like to organize?",
                "options": list(ALLOWED_DIRECTORIES.keys())
            })

        elif "recon" in payload:
            recon_cmd = payload["recon"]
            recon_output = execution(recon_cmd)
            events.append({"type": "recon", "command": recon_cmd, "output": recon_output})

            conversation_history.append({
                "role": "user",
                "content": f"Filesystem result:\n{recon_output}\nNow execute the correct command."
            })
            ai_response2, warnings2 = ask_llm("Execute based on what you found.")
            events.extend({"type": "info", "content": w} for w in warnings2)
            json_candidate2 = extract_first_json_object(ai_response2)
            if json_candidate2:
                try:
                    data2 = safe_json_parse(json_candidate2)
                except json.JSONDecodeError:
                    log.warning("Could not parse follow-up JSON payload: %s", json_candidate2)
                    data2 = {}
                if "command" in data2:
                    # rm/mv: flag for frontend confirmation
                    cmd = data2["command"]
                    if requires_confirmation(cmd):
                        events.append({"type": "confirm", "command": cmd})
                    else:
                        output = execution(cmd)
                        events.append({"type": "ran", "command": cmd, "output": output})

        elif "command" in payload:
            cmd = payload["command"]
            if requires_confirmation(cmd):
                events.append({"type": "confirm", "command": cmd})
            else:
                output = execution(cmd)
                events.append({"type": "ran", "command": cmd, "output": output})

        else:
            events.append({"type": "chat", "content": ai_response})

        return jsonify({"events": events})

    except Exception as e:
        log.exception("Error in /api/chat")
        return jsonify({"error": str(e)}), 500

@app.route("/api/confirm-run", methods=["POST"])
def confirm_run():
    data = request.get_json()
    command = data.get("command", "").strip()
    confirmed = data.get("confirmed", False)
    if not confirmed:
        return jsonify({"events": [{"type": "info", "content": "Command cancelled."}]})
    output = execution(command)
    return jsonify({"events": [{"type": "ran", "command": command, "output": output}]})

@app.route("/api/choose-folder", methods=["POST"])
def choose_folder():
    global client
    data = request.get_json()
    folder_name = data.get("folder", "").strip()
    
    if folder_name not in ALLOWED_DIRECTORIES:
        return jsonify({"error": "Invalid folder selection."}), 400
    
    folder_path = ALLOWED_DIRECTORIES[folder_name]
    
    # Add user's choice to conversation
    conversation_history.append({
        "role": "user",
        "content": f"User chose to organize: {folder_name}"
    })
    warnings = []
    if trim_conversation_history():
        warnings.append("Older messages were trimmed to avoid model context overflow.")
    if estimate_message_tokens(conversation_history) >= CONTEXT_TOKEN_WARN_AT:
        warnings.append(
            "Conversation is getting long. If responses degrade, clear memory and continue."
        )
    
    # Ask AI to generate organization commands
    prompt = f"User wants to organize {folder_name} ({folder_path}). Create shell commands to organize files by type into subdirectories. Respond with JSON."
    
    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are Dadarzz Agent. Respond only with JSON."},
                *conversation_history,
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        ai_response = completion.choices[0].message.content.strip()
        conversation_history.append({"role": "assistant", "content": ai_response})
        
        json_candidate = extract_first_json_object(ai_response)
        events = [{"type": "info", "content": w} for w in warnings]
        
        if json_candidate:
            try:
                payload = safe_json_parse(json_candidate)
                if "command" in payload:
                    cmd = payload["command"]
                    if requires_confirmation(cmd):
                        events.append({"type": "confirm", "command": cmd})
                    else:
                        output = execution(cmd)
                        events.append({"type": "ran", "command": cmd, "output": output})
                elif "chat" in payload:
                    events.append({"type": "chat", "content": payload["chat"]})
            except json.JSONDecodeError:
                events.append({"type": "chat", "content": ai_response})
        else:
            events.append({"type": "chat", "content": ai_response})
        
        return jsonify({"events": events})
    
    except Exception as e:
        log.exception("Error in /api/choose-folder")
        return jsonify({"error": str(e)}), 500

@app.route("/api/clear", methods=["POST"])
def clear_memory():
    global conversation_history
    conversation_history = []
    return jsonify({"ok": True})

# ==========================
# AUTO-OPEN BROWSER
# ==========================
def open_browser():
    """Wait briefly for Flask to start, then open the browser once."""
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:5174")

# ==========================
# ENTRY POINT
# ==========================
if __name__ == "__main__":
    # Pre-load API key if it exists
    existing_key = load_api_key()
    if existing_key:
        init_client(existing_key)

    # Open browser in background thread
    threading.Thread(target=open_browser, daemon=True).start()

    print("\n  ✦  Dadarzz Agent starting at http://127.0.0.1:5174")
    print("  Press Ctrl+C to quit.\n")

    app.run(host="127.0.0.1", port=5174, debug=False, use_reloader=False)
