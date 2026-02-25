/* ============================================================
   DADARZZ AGENT — app.js
   ============================================================ */

const messagesEl  = document.getElementById("messages");
const inputEl     = document.getElementById("user-input");
const sendBtn     = document.getElementById("send-btn");
const sendLabel   = document.getElementById("send-label");
const statusDot   = document.getElementById("status-dot");
const statusText  = document.getElementById("status-text");
const clearBtn    = document.getElementById("clear-btn");
const changeKeyBtn = document.getElementById("change-key-btn");

const keyOverlay  = document.getElementById("key-overlay");
const apiKeyInput = document.getElementById("api-key-input");
const saveKeyBtn  = document.getElementById("save-key-btn");

const confirmOverlay = document.getElementById("confirm-overlay");
const confirmCmd     = document.getElementById("confirm-cmd");
const confirmYes     = document.getElementById("confirm-yes");
const confirmNo      = document.getElementById("confirm-no");

// ── Helpers ──────────────────────────────────────────────────
function scrollBottom() {
  const area = document.getElementById("chat-area");
  area.scrollTop = area.scrollHeight;
}

function setStatus(text, color = "green") {
  statusText.textContent = text;
  statusDot.className = `dot ${color}`;
}

function setLoading(loading) {
  inputEl.disabled = loading;
  sendBtn.disabled = loading;
  sendLabel.textContent = loading ? "…" : "Send";
}

// ── Message Renderers ─────────────────────────────────────────
function appendUser(text) {
  const d = document.createElement("div");
  d.className = "msg user-msg";
  d.innerHTML = `<div class="msg-sender">You</div><div class="msg-text">${escHtml(text)}</div>`;
  messagesEl.appendChild(d);
  scrollBottom();
}

function appendAI(text) {
  const d = document.createElement("div");
  d.className = "msg ai-msg";
  d.innerHTML = `<div class="msg-sender">Dadarzz Agent</div><div class="msg-text">${escHtml(text)}</div>`;
  messagesEl.appendChild(d);
  scrollBottom();
}

function appendRan(command, output) {
  const d = document.createElement("div");
  d.className = "msg ran-msg";
  d.innerHTML = `
    <div class="ran-header"><span class="ran-arrow">▶</span>${escHtml(command)}</div>
    ${output ? `<div class="ran-output">${escHtml(output.trim())}</div>` : ""}
  `;
  messagesEl.appendChild(d);
  scrollBottom();
}

function appendRecon(command, output) {
  const d = document.createElement("div");
  d.className = "msg recon-msg";
  d.innerHTML = `
    <div class="recon-header"><span>⟳</span> Scanning: ${escHtml(command)}</div>
    ${output ? `<div class="ran-output">${escHtml(output.trim())}</div>` : ""}
  `;
  messagesEl.appendChild(d);
  scrollBottom();
}

function appendInfo(text) {
  const d = document.createElement("div");
  d.className = "msg info-msg";
  d.innerHTML = `<span class="info-dot">◆</span>${escHtml(text)}`;
  messagesEl.appendChild(d);
  scrollBottom();
}

function appendError(text) {
  const d = document.createElement("div");
  d.className = "msg ai-msg error-msg";
  d.innerHTML = `<div class="msg-sender">Error</div><div class="msg-text">${escHtml(text)}</div>`;
  messagesEl.appendChild(d);
  scrollBottom();
}

function appendThinking() {
  const d = document.createElement("div");
  d.className = "msg thinking-msg";
  d.id = "thinking-indicator";
  d.innerHTML = `<div class="msg-sender" style="color:var(--accent);margin-bottom:8px;">Dadarzz Agent</div>
    <div class="thinking-dots"><span></span><span></span><span></span></div>`;
  messagesEl.appendChild(d);
  scrollBottom();
  return d;
}

function removeThinking() {
  const t = document.getElementById("thinking-indicator");
  if (t) t.remove();
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ── Render Events ─────────────────────────────────────────────
function renderEvents(events) {
  for (const ev of events) {
    if (ev.type === "chat") {
      appendAI(ev.content);
    } else if (ev.type === "ran") {
      appendRan(ev.command, ev.output);
    } else if (ev.type === "recon") {
      appendRecon(ev.command, ev.output);
    } else if (ev.type === "info") {
      appendInfo(ev.content);
    } else if (ev.type === "confirm") {
      showConfirm(ev.command);
    } else if (ev.type === "error") {
      appendError(ev.content);
    }
  }
}

// ── Confirm Dialog ────────────────────────────────────────────
function showConfirm(command) {
  confirmCmd.textContent = command;
  confirmOverlay.classList.remove("hidden");

  confirmYes.onclick = async () => {
    confirmOverlay.classList.add("hidden");
    setStatus("Executing…", "blue");
    try {
      const res = await fetch("/api/confirm-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command, confirmed: true })
      });
      const data = await res.json();
      renderEvents(data.events || []);
    } catch(e) {
      appendError(e.message);
    }
    setStatus("Ready", "green");
  };

  confirmNo.onclick = () => {
    confirmOverlay.classList.add("hidden");
    appendInfo("Command cancelled.");
    setStatus("Ready", "green");
  };
}

// ── Send Message ──────────────────────────────────────────────
async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;

  inputEl.value = "";
  autoResize();
  appendUser(text);
  setLoading(true);
  setStatus("Thinking…", "blue");

  const thinking = appendThinking();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text })
    });

    removeThinking();

    if (res.status === 401) {
      keyOverlay.classList.remove("hidden");
      setStatus("No API key", "red");
      setLoading(false);
      return;
    }

    const data = await res.json();

    if (data.error) {
      appendError(data.error);
    } else {
      renderEvents(data.events || []);
    }

    setStatus("Ready", "green");
  } catch (err) {
    removeThinking();
    appendError("Network error: " + err.message);
    setStatus("Error", "red");
  }

  setLoading(false);
  inputEl.focus();
}

// ── Clear Memory ──────────────────────────────────────────────
clearBtn.addEventListener("click", async () => {
  await fetch("/api/clear", { method: "POST" });
  messagesEl.innerHTML = "";
  appendInfo("Memory cleared. Starting fresh.");
  setStatus("Memory cleared", "yellow");
  setTimeout(() => setStatus("Ready", "green"), 2000);
});

// ── Change API Key ────────────────────────────────────────────
changeKeyBtn.addEventListener("click", () => {
  keyOverlay.classList.remove("hidden");
  apiKeyInput.value = "";
  apiKeyInput.focus();
});

saveKeyBtn.addEventListener("click", async () => {
  const key = apiKeyInput.value.trim();
  if (!key) return;

  const res = await fetch("/api/set-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: key })
  });

  if (res.ok) {
    keyOverlay.classList.add("hidden");
    appendInfo("API key saved. Ready to go.");
    setStatus("Ready", "green");
  } else {
    apiKeyInput.style.borderColor = "var(--red)";
  }
});

apiKeyInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") saveKeyBtn.click();
});

// ── Input Events ──────────────────────────────────────────────
sendBtn.addEventListener("click", sendMessage);

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

function autoResize() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + "px";
}
inputEl.addEventListener("input", autoResize);

// ── Init ──────────────────────────────────────────────────────
inputEl.focus();