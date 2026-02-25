import json
import subprocess
import os
import sys
import logging
import re
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
    "id", "rm", "mv"
]

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

# ==========================
# JSON PARSING HELPER
# ==========================
def safe_json_parse(json_str):
    """Safely parse JSON from LLM response handling literal backslashes."""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # Try fixing common escaping issues from model output:
        # - invalid escape sequences (e.g. "\D" in paths)
        # - backslash-escaped spaces often used in shell commands
        fixed = json_str.replace('\\ ', ' ')
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', fixed)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            # If still failing, raise the original error
            raise

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
def execution(command):
    first_cmd = command.strip().split()[0] if command.strip() else ""
    if not first_cmd:
        return "Error: Empty command."
    if first_cmd not in COMMANDS:
        return f"Error: Command '{first_cmd}' not allowed."
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
def ask_llm(user_message):
    conversation_history.append({"role": "user", "content": user_message})
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
        return response
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
        ai_response = ask_llm(user_input)
        json_candidate = extract_first_json_object(ai_response)

        if not json_candidate:
            return jsonify({"events": [{"type": "chat", "content": ai_response}]})

        try:
            payload = safe_json_parse(json_candidate)
        except json.JSONDecodeError:
            log.warning("Could not parse model JSON payload: %s", json_candidate)
            return jsonify({"events": [{"type": "chat", "content": ai_response}]})
        events = []

        if "chat" in payload:
            events.append({"type": "chat", "content": payload["chat"]})

        elif "recon" in payload:
            recon_cmd = payload["recon"]
            recon_output = execution(recon_cmd)
            events.append({"type": "recon", "command": recon_cmd, "output": recon_output})

            conversation_history.append({
                "role": "user",
                "content": f"Filesystem result:\n{recon_output}\nNow execute the correct command."
            })
            ai_response2 = ask_llm("Execute based on what you found.")
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
                    first = cmd.strip().split()[0]
                    if first in ["rm", "mv"]:
                        events.append({"type": "confirm", "command": cmd})
                    else:
                        output = execution(cmd)
                        events.append({"type": "ran", "command": cmd, "output": output})

        elif "command" in payload:
            cmd = payload["command"]
            first = cmd.strip().split()[0]
            if first in ["rm", "mv"]:
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
