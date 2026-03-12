# Dadarzz Agent

Local macOS AI assistant with a Flask web UI, packaged as a single executable for Apple Silicon (M1/M2/M3).
# Documentation
https://github.com/Dadarzz2405/AI-Agent/blob/main/DOCUMENTATION.md
## For Non-Developers (Install in 2 Minutes)

Use this if someone sent you the `dadarzz-agent` file.

1. Move `dadarzz-agent` to your `Downloads` folder.
2. Open Terminal.
3. Run:

```bash
chmod +x ~/Downloads/dadarzz-agent && xattr -dr com.apple.quarantine ~/Downloads/dadarzz-agent
```

4. Start the app:

```bash
~/Downloads/dadarzz-agent
```

Your browser should open automatically at `http://127.0.0.1:5174`.

### First Launch

- The app asks for your Groq API key.
- It saves your key to `~/.dadarzz_config.json` so you only enter it once.

## What This Project Does

- Runs a local Flask app on `127.0.0.1:5174`
- Lets you chat with the agent
- Can run approved shell commands (with confirmation for `rm`/`mv`)
- Opens the browser automatically on startup

## Required Project Structure (for building)

```text
project/
├── Agent.py
├── dadarzz.spec
├── templates/
│   └── index.html
└── static/
    ├── css/
    │   └── style.css
    └── js/
        └── app.js
```

## Developer Build Guide (M1/M2/M3 Macs)

### 1. Install dependencies

```bash
pip3 install pyinstaller flask groq httpx
```

### 2. Verify native ARM64 Python

```bash
python3 -c "import platform; print(platform.machine())"
```

Expected output:

```text
arm64
```

### 3. Build executable

Option A (recommended):

```bash
pyinstaller dadarzz.spec
```

Option B (one-liner):

```bash
pyinstaller \
  --onefile \
  --name dadarzz-agent \
  --target-arch arm64 \
  --add-data "templates:templates" \
  --add-data "static:static" \
  --hidden-import flask \
  --hidden-import flask.templating \
  --hidden-import jinja2 \
  --hidden-import werkzeug \
  --hidden-import groq \
  --hidden-import httpx \
  --hidden-import anyio \
  --exclude-module tkinter \
  --exclude-module PyQt5 \
  --console \
  --noupx \
  Agent.py
```

macOS/Linux use `:` for `--add-data`. Windows uses `;`.

### 4. Output file

```text
dist/dadarzz-agent
```

## Why Bundled Files Work in Onefile Mode

`Agent.py` uses `resource_path()` so Flask can find templates/static files in both:

- dev mode (normal files)
- frozen PyInstaller mode (`sys._MEIPASS` temp extraction directory)

## Browser Auto-Launch Behavior

At startup, a daemon thread waits ~1.2s, then opens:

```text
http://127.0.0.1:5174
```

`use_reloader=False` is required for stable behavior in the frozen executable.

## Distribution Checklist

- [ ] Build on Apple Silicon (not Rosetta)
- [ ] `platform.machine()` returns `arm64`
- [ ] `dist/dadarzz-agent` exists (~40-80 MB is typical)
- [ ] Cold test in a fresh Terminal: `./dist/dadarzz-agent`
- [ ] Browser opens within about 2 seconds
- [ ] API key prompt appears first launch
- [ ] Key persists in `~/.dadarzz_config.json`

## Troubleshooting

| Symptom | Fix |
|---|---|
| `zsh: permission denied` | Run the unlock one-liner in the Non-Developers section |
| `"dadarzz-agent" is damaged` | Run `xattr -dr com.apple.quarantine ~/Downloads/dadarzz-agent` |
| Browser does not open | Manually visit `http://127.0.0.1:5174` |
| `ModuleNotFoundError: flask` | Add Flask hidden imports in build config and rebuild |
| Port already in use | Change `port=5174` in `Agent.py` and rebuild |
| App exits immediately | Run from Terminal to view traceback and check `app.log` |
