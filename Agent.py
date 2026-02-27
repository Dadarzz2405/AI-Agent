import json
import subprocess
import os
import sys
import logging
import re
import shlex
import platform
from typing import List, Tuple
import threading
import webbrowser
import time
from flask import Flask, render_template, request, jsonify
from groq import Groq as g

# ==========================
# PLATFORM DETECTION
# ==========================
PLATFORM = platform.system()  # "Darwin", "Windows", "Linux"
IS_WINDOWS = PLATFORM == "Windows"
IS_MAC     = PLATFORM == "Darwin"
IS_LINUX   = PLATFORM == "Linux"

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
MODEL       = "llama-3.3-70b-versatile"
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".dadarzz_config.json")

# ── Per-platform allowed commands ──
if IS_WINDOWS:
    COMMANDS = [
        "dir", "echo", "cd", "type", "copy", "move",
        "del", "mkdir", "rmdir", "where", "whoami",
        "hostname", "date", "time", "ver", "vol",
        "tree", "find", "findstr", "attrib",
    ]
else:
    # macOS + Linux
    COMMANDS = [
        "ls", "pwd", "whoami", "date", "cal", "echo",
        "mkdir", "touch", "cat", "head", "tail", "wc",
        "uname", "uptime", "df", "du", "open", "which",
        "id", "rm", "mv", "find",
    ]

# ── Per-platform destructive commands (require confirmation) ──
if IS_WINDOWS:
    DESTRUCTIVE_COMMANDS = {"del", "move", "rmdir"}
else:
    DESTRUCTIVE_COMMANDS = {"rm", "mv"}

# ── Per-platform shell ──
if IS_WINDOWS:
    SHELL_EXECUTABLE = None          # subprocess uses cmd.exe by default
else:
    SHELL_EXECUTABLE = "/bin/zsh" if IS_MAC else "/bin/bash"

# ── Allowed directories (works on all platforms via expanduser) ──
ALLOWED_DIRECTORIES = {
    "Desktop":   os.path.expanduser("~/Desktop"),
    "Documents": os.path.expanduser("~/Documents"),
    "Downloads": os.path.expanduser("~/Downloads"),
}

# ── System prompt adapts to OS ──
OS_LABEL = {
    "Darwin":  "macOS",
    "Windows": "Windows",
    "Linux":   "Linux",
}.get(PLATFORM, PLATFORM)

COMMAND_EXAMPLES = {
    "Darwin":  'move files: { "command": "mv ~/Desktop/file.txt ~/Documents/" }',
    "Windows": 'move files: { "command": "move %USERPROFILE%\\Desktop\\file.txt %USERPROFILE%\\Documents\\" }',
    "Linux":   'move files: { "command": "mv ~/Desktop/file.txt ~/Documents/" }',
}.get(PLATFORM, "")

SYSTEM_PROMPT = f"""You are Dadarzz Agent, a smart {OS_LABEL} assistant that can both chat and execute terminal commands.

You have two response modes — pick the right one based on the user's intent:

MODE 1 — Terminal task (moving files, organizing folders, checking disk, etc):
First recon if needed:
{{ "recon": "shell command to inspect filesystem" }}
Then execute:
{{ "command": "shell command to run" }}

MODE 2 — Normal conversation (questions, explanations, greetings, etc):
{{ "chat": "your friendly response here" }}

RULES:
- ALWAYS respond with ONLY a JSON object. Never plain text, never markdown.
- You are running on {OS_LABEL}. Use only {OS_LABEL}-appropriate shell commands.
- Example: {COMMAND_EXAMPLES}
- If the user is just chatting, asking questions, or saying hi — use "chat" mode.
- If the user wants something done on their {OS_LABEL} — use "recon" then "command" mode.
- You have memory of the full conversation, so refer back to it naturally."""

client = None
conversation_history = []
MAX_HISTORY_MESSAGES  = 24
CONTEXT_TOKEN_WARN_AT  = 5000
CONTEXT_TOKEN_HARD_LIMIT = 6500

# ==========================
# JSON PARSING HELPERS
# ==========================
def _repair_invalid_json_escapes(json_str: str) -> str:
    valid_escapes = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}
    out = []
    in_string = False
    i = 0
    while i < len(json_str):
        ch = json_str[i]
        if ch == '"':
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
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        fixed = _repair_invalid_json_escapes(json_str)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            raise

def estimate_message_tokens(messages: List[dict]) -> int:
    total_chars = len(SYSTEM_PROMPT)
    for msg in messages:
        total_chars += len(msg.get("content", "")) + 16
    return max(1, total_chars // 4)

def trim_conversation_history() -> bool:
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
    start = text.find("{")
    if start == -1:
        return None
    in_string = False
    escaped   = False
    depth     = 0
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
    keywords = ["organize", "sort", "clean", "arrange", "tidy", "structure"]
    return any(kw in user_input.lower() for kw in keywords)

def requires_confirmation(command: str) -> bool:
    """Check if command contains any destructive operations."""
    # Windows uses spaces and doesn't need shlex — split naively
    if IS_WINDOWS:
        separators = re.split(r"\s*(?:&&|\|\||&|;)\s*", command)
        for part in separators:
            tokens = part.strip().split()
            if tokens and tokens[0].lower() in DESTRUCTIVE_COMMANDS:
                return True
        return False

    # Unix: split on shell chain operators
    parts = re.split(r"\s*(?:&&|\|\||;)\s*", command)
    for part in parts:
        tokens = part.strip().split()
        if tokens and tokens[0] in DESTRUCTIVE_COMMANDS:
            return True
    return False

def is_path_allowed(path: str) -> bool:
    abs_path = os.path.abspath(os.path.expanduser(path))
    for allowed_dir in ALLOWED_DIRECTORIES.values():
        allowed_abs = os.path.abspath(allowed_dir)
        if abs_path.startswith(allowed_abs):
            return True
    return False

def get_first_token(command: str) -> str:
    """Extract the base command name, stripping path separators."""
    try:
        if IS_WINDOWS:
            token = command.strip().split()[0]
        else:
            token = shlex.split(command, posix=True)[0]
        # Strip any path prefix (e.g. C:\Windows\System32\cmd.exe → cmd.exe)
        return os.path.basename(token).lower() if IS_WINDOWS else os.path.basename(token)
    except (ValueError, IndexError):
        return ""

def execution(command: str) -> str:
    first_cmd = get_first_token(command)

    if not first_cmd:
        return "Error: Empty command."

    # Normalise for Windows comparison (commands are case-insensitive)
    check_cmd = first_cmd.lower() if IS_WINDOWS else first_cmd
    allowed   = [c.lower() for c in COMMANDS] if IS_WINDOWS else COMMANDS

    if check_cmd not in allowed:
        return f"Error: Command '{first_cmd}' not allowed."

    # Path validation — only for Unix (Windows paths look different)
    if not IS_WINDOWS:
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError as e:
            return f"Error: Invalid command syntax ({e})."
        for token in tokens[1:]:
            if "/" in token or token.startswith("./") or token.startswith("~/"):
                if not is_path_allowed(token):
                    return f"Error: Access to '{token}' is not allowed."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            executable=SHELL_EXECUTABLE,   # None on Windows → uses cmd.exe
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
        warnings.append("Older messages were trimmed to avoid model context overflow.")
    if estimate_message_tokens(conversation_history) >= CONTEXT_TOKEN_WARN_AT:
        warnings.append("Conversation is getting long. If responses degrade, clear memory and continue.")
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
    data    = request.get_json()
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

    data       = request.get_json()
    user_input = data.get("message", "").strip()
    if not user_input:
        return jsonify({"error": "Empty message."}), 400

    try:
        ai_response, warnings = ask_llm(user_input)
        json_candidate  = extract_first_json_object(ai_response)
        warning_events  = [{"type": "info", "content": w} for w in warnings]

        if not json_candidate:
            return jsonify({"events": warning_events + [{"type": "chat", "content": ai_response}]})

        try:
            payload = safe_json_parse(json_candidate)
        except json.JSONDecodeError:
            log.warning("Could not parse model JSON payload: %s", json_candidate)
            return jsonify({"events": warning_events + [{"type": "chat", "content": ai_response}]})

        events = list(warning_events)

        if "chat" in payload:
            events.append({"type": "chat", "content": payload["chat"]})

        elif detect_organization_intent(user_input):
            events.append({
                "type":    "choose",
                "content": "Which folder would you like to organize?",
                "options": list(ALLOWED_DIRECTORIES.keys())
            })

        elif "recon" in payload:
            recon_cmd    = payload["recon"]
            recon_output = execution(recon_cmd)
            events.append({"type": "recon", "command": recon_cmd, "output": recon_output})

            conversation_history.append({
                "role":    "user",
                "content": f"Filesystem result:\n{recon_output}\nNow execute the correct command."
            })
            ai_response2, warnings2 = ask_llm("Execute based on what you found.")
            events.extend({"type": "info", "content": w} for w in warnings2)
            json_candidate2 = extract_first_json_object(ai_response2)
            if json_candidate2:
                try:
                    data2 = safe_json_parse(json_candidate2)
                except json.JSONDecodeError:
                    data2 = {}
                if "command" in data2:
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
    data      = request.get_json()
    command   = data.get("command", "").strip()
    confirmed = data.get("confirmed", False)
    if not confirmed:
        return jsonify({"events": [{"type": "info", "content": "Command cancelled."}]})
    output = execution(command)
    return jsonify({"events": [{"type": "ran", "command": command, "output": output}]})

@app.route("/api/choose-folder", methods=["POST"])
def choose_folder():
    global client
    data        = request.get_json()
    folder_name = data.get("folder", "").strip()

    if folder_name not in ALLOWED_DIRECTORIES:
        return jsonify({"error": "Invalid folder selection."}), 400

    folder_path = ALLOWED_DIRECTORIES[folder_name]
    conversation_history.append({
        "role":    "user",
        "content": f"User chose to organize: {folder_name}"
    })

    warnings = []
    if trim_conversation_history():
        warnings.append("Older messages were trimmed to avoid model context overflow.")
    if estimate_message_tokens(conversation_history) >= CONTEXT_TOKEN_WARN_AT:
        warnings.append("Conversation is getting long. If responses degrade, clear memory and continue.")

    prompt = (
        f"User wants to organize {folder_name} ({folder_path}) on {OS_LABEL}. "
        f"Create shell commands appropriate for {OS_LABEL} to organize files by type "
        f"into subdirectories. Respond with JSON."
    )

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

@app.route("/api/platform", methods=["GET"])
def get_platform():
    """Expose current platform to the frontend if needed."""
    return jsonify({"platform": OS_LABEL})

# ==========================
# AUTO-OPEN BROWSER
# ==========================
def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:5174")

# ==========================
# ENTRY POINT
# ==========================
if __name__ == "__main__":
    existing_key = load_api_key()
    if existing_key:
        init_client(existing_key)

    threading.Thread(target=open_browser, daemon=True).start()

    print(f"\n  ✦  Dadarzz Agent starting at http://127.0.0.1:5174  [{OS_LABEL}]")
    print("  Press Ctrl+C to quit.\n")

    app.run(host="127.0.0.1", port=5174, debug=False, use_reloader=False)