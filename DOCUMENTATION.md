# Dadarzz Agent — Documentation

**Author:** Haidar Ali Fawwaz Nasirodin  
**Organization:** Global Darussalam Academy  
**Target Users:** GDA Students (general)  
**Platform:** macOS Apple Silicon (M1/M2/M3), Windows, Linux
**License:** MIT © 2026 Dadarzz  

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Tech Stack](#tech-stack)
3. [System Architecture](#system-architecture)
4. [Project Structure](#project-structure)
5. [Core Features](#core-features)
6. [How the Agent Works](#how-the-agent-works)
7. [Command Execution Model](#command-execution-model)
8. [API Key Management](#api-key-management)
9. [Building the Executable](#building-the-executable)
10. [Distribution & Installation](#distribution--installation)
11. [Troubleshooting](#troubleshooting)
12. [Roadmap & Next Steps](#roadmap--next-steps)

---

## Project Overview

Dadarzz Agent is a local macOS AI assistant with a web-based chat UI, packaged as a single standalone executable for Apple Silicon devices. It was developed during the Passion Project at Global Darussalam Academy as a second product targeting GDA students in general — specifically students who may not be fully comfortable with digital tools and could benefit from a natural language interface for automating common everyday tasks on their Mac.

The agent runs entirely on the user's local machine. There is no cloud server, no account required, and no data sent anywhere except to the Groq API for language model inference.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python |
| Web Framework | Flask |
| LLM Provider | Groq API (Llama 3.1) |
| HTTP Client | httpx + anyio |
| Packaging | PyInstaller (onefile, arm64) |
| Frontend | HTML + CSS + Vanilla JS (bundled) |
| Config Storage | JSON file (`~/.dadarzz_config.json`) |

---

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│                  User's Mac (local)                 │
│                                                     │
│   Browser (auto-opened)                             │
│   http://127.0.0.1:5174                             │
│          │                                          │
│          │ HTTP (localhost only)                    │
│          ▼                                          │
│   ┌──────────────────────────────────┐              │
│   │   Flask App (dadarzz-agent)      │              │
│   │                                  │              │
│   │  ┌────────────┐ ┌─────────────┐ │              │
│   │  │  Chat API  │ │ Shell Exec  │ │              │
│   │  │ /api/chat  │ │ (approved   │ │              │
│   │  └─────┬──────┘ │  commands)  │ │              │
│   │        │        └─────────────┘ │              │
│   └────────┼─────────────────────────┘              │
│            │                                        │
│            │ HTTPS                                  │
│            ▼                                        │
│   ┌──────────────────┐                              │
│   │   Groq API       │                              │
│   │  (Llama 3.1)     │                              │
│   └──────────────────┘                              │
│                                                     │
│   Config: ~/.dadarzz_config.json                    │
│   (stores Groq API key)                             │
└─────────────────────────────────────────────────────┘
```

The executable bundles the Flask app, all templates, and static files into a single binary. On launch, it starts the Flask server on `127.0.0.1:5174` and automatically opens the browser. All inference requests go out to the Groq API over HTTPS.

---

## Project Structure

```
project/
├── Agent.py               # Main Flask app + chat + shell execution logic
├── dadarzz.spec           # PyInstaller build specification
├── templates/
│   └── index.html         # Chat UI (auto-opened in browser)
└── static/
    ├── css/
    │   └── style.css
    └── js/
        └── app.js
```

After building:

```
dist/
└── dadarzz-agent          # Single executable (~40–80 MB)
```

---

## Core Features

- **Local Flask web server** — runs on `127.0.0.1:5174`, accessible only from the user's own machine
- **AI chat interface** — natural language conversation powered by Groq (Llama 3.1)
- **Shell command execution** — the agent can run approved shell commands on behalf of the user
- **Confirmation prompt for destructive commands** — `rm` and `mv` operations require explicit user confirmation before execution
- **Browser auto-launch** — opens the chat UI automatically on startup
- **API key prompt on first launch** — guides non-technical users through setup
- **Persistent config** — API key saved to `~/.dadarzz_config.json` so users only enter it once

---

## How the Agent Works

1. User types a message in the browser chat UI
2. The frontend sends the message to `POST /api/chat` (localhost)
3. `Agent.py` forwards the message to the Groq API with a system prompt that defines the agent's capabilities and behavior
4. Groq returns a response, which may include a shell command to run
5. If a command is present, the agent checks it against the approved command list
6. If the command requires confirmation (`rm`, `mv`), the user is prompted before execution
7. The command output is returned to the user alongside the AI's reply

---

## Command Execution Model

The agent operates on a **whitelist + confirmation model** for safety:

| Category | Behavior |
|---|---|
| Read-only commands (`ls`, `cat`, `find`, `pwd`, etc.) | Executed automatically |
| File organization commands (`mkdir`, `cp`) | Executed automatically |
| Destructive commands (`rm`, `mv`) | Requires explicit user confirmation |
| Arbitrary code execution | Not supported |

This model is designed to be useful for everyday file management tasks while preventing accidental data loss.

**Example tasks the agent can handle:**
- List and organize files in a folder
- Find files by name or extension
- Create folder structures
- Move or rename files (with confirmation)
- Show disk usage

---

## API Key Management

On first launch, the agent detects that no config file exists and prompts the user to enter their **Groq API key** (free at console.groq.com).

The key is saved to:

```
~/.dadarzz_config.json
```

Format:

```json
{
  "groq_api_key": "gsk_xxxxxxxxxxxxxxxxxxxx"
}
```

On all subsequent launches, the key is loaded from this file automatically. Users can reset their key by deleting the config file.

---

## Building the Executable

### Requirements

- macOS with Apple Silicon (M1/M2/M3)
- Python installed natively as arm64 (not via Rosetta)
- Dependencies: `pyinstaller flask groq httpx anyio`

### Verify arm64 Python

```bash
python3 -c "import platform; print(platform.machine())"
# Expected: arm64
```

### Install dependencies

```bash
pip3 install pyinstaller flask groq httpx anyio
```

### Build

```bash
pyinstaller dadarzz.spec
```

Output: `dist/dadarzz-agent`

### Why bundled files work

`Agent.py` uses a `resource_path()` helper to locate templates and static files in both development mode and when running as a frozen PyInstaller executable. In frozen mode, PyInstaller extracts bundled files to a temporary `sys._MEIPASS` directory — `resource_path()` handles this transparently:

```python
def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)
```

`use_reloader=False` is set in the Flask run configuration to prevent the reloader from spawning a second process, which causes unstable behavior in the packaged executable.

---

## Distribution & Installation

### For the distributor (developer)

Before sharing:
- [ ] Build on Apple Silicon (not Rosetta)
- [ ] Confirm `platform.machine()` returns `arm64`
- [ ] Cold-test in a fresh Terminal: `./dist/dadarzz-agent`
- [ ] Confirm browser opens within ~2 seconds
- [ ] Confirm API key prompt appears on first launch
- [ ] Confirm key persists to `~/.dadarzz_config.json`

### For end users (non-developers)

1. Move `dadarzz-agent` to the `Downloads` folder
2. Open Terminal
3. Run the unlock command:
```bash
chmod +x ~/Downloads/dadarzz-agent && xattr -dr com.apple.quarantine ~/Downloads/dadarzz-agent
```
4. Launch:
```bash
~/Downloads/dadarzz-agent
```
5. The browser opens automatically at `http://127.0.0.1:5174`
6. Enter your Groq API key when prompted (free at console.groq.com)

The quarantine removal step (`xattr`) is required because the executable is not code-signed with an Apple Developer certificate. This is a standard macOS Gatekeeper behavior for unsigned binaries downloaded from the internet.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `zsh: permission denied` | Run the `chmod + xattr` unlock command |
| `"dadarzz-agent" is damaged` | Run `xattr -dr com.apple.quarantine ~/Downloads/dadarzz-agent` |
| Browser does not open automatically | Manually visit `http://127.0.0.1:5174` |
| `ModuleNotFoundError: flask` | Rebuild with Flask added to hidden imports in `dadarzz.spec` |
| Port already in use | Change `port=5174` in `Agent.py` and rebuild |
| App exits immediately | Run from Terminal to read the traceback, check `app.log` |
| API key not saving | Check write permissions on home directory (`~`) |

---

## Roadmap & Next Steps

The current version (v0.1 beta) is limited to macOS Apple Silicon. Planned improvements for future versions:

- **Code signing** — eliminate the macOS quarantine step for a smoother install experience
- **Cross-platform support** — Windows and Intel Mac builds
- **Web-based version** — remove the hardware barrier and allow any GDA student to use the agent via browser without installing anything
- **Expanded task support** — web browsing automation, scheduled tasks, clipboard management
- **Improved NLU** — better handling of ambiguous or complex multi-step commands
- **Broader GDA distribution** — target the original goal of 20+ student users once the hardware barrier is resolved
