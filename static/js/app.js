/* ============================================================
   DADARZZ AGENT — app.js
   Features: copy button, undo for mv, onboarding prompts
   ============================================================ */

const messagesEl   = document.getElementById("messages");
const inputEl      = document.getElementById("user-input");
const sendBtn      = document.getElementById("send-btn");
const sendLabel    = document.getElementById("send-label");
const statusDot    = document.getElementById("status-dot");
const statusText   = document.getElementById("status-text");
const clearBtn     = document.getElementById("clear-btn");
const changeKeyBtn = document.getElementById("change-key-btn");

const keyOverlay   = document.getElementById("key-overlay");
const apiKeyInput  = document.getElementById("api-key-input");
const saveKeyBtn   = document.getElementById("save-key-btn");

const confirmOverlay = document.getElementById("confirm-overlay");
const confirmCmd     = document.getElementById("confirm-cmd");
const confirmYes     = document.getElementById("confirm-yes");
const confirmNo      = document.getElementById("confirm-no");

const chooseOverlay = document.getElementById("choose-overlay");
const chooseLabel   = document.getElementById("choose-label");
const chooseOptions = document.getElementById("choose-options");

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

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ── Copy Button Helper ────────────────────────────────────────
function makeCopyBtn(textToCopy) {
  const btn = document.createElement("button");
  btn.className = "copy-btn";
  btn.title = "Copy to clipboard";
  btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
  btn.addEventListener("click", () => {
    navigator.clipboard.writeText(textToCopy).then(() => {
      btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
      btn.classList.add("copied");
      setTimeout(() => {
        btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
        btn.classList.remove("copied");
      }, 1800);
    });
  });
  return btn;
}

// ── Undo for mv ───────────────────────────────────────────────
/**
 * Parse a mv command and return {src, dst} if it's a simple two-arg mv.
 * Handles quoted paths and tilde expansion hints.
 */
function parseMvCommand(command) {
  // Strip leading 'mv ' and split remaining into tokens respecting quotes
  const raw = command.trim();
  if (!raw.startsWith("mv ")) return null;

  const args = [];
  let current = "";
  let inQuote = null;

  for (let i = 3; i < raw.length; i++) {
    const ch = raw[i];
    if (inQuote) {
      if (ch === inQuote) { inQuote = null; }
      else { current += ch; }
    } else if (ch === '"' || ch === "'") {
      inQuote = ch;
    } else if (ch === " ") {
      if (current) { args.push(current); current = ""; }
    } else {
      current += ch;
    }
  }
  if (current) args.push(current);

  // Only handle simple 2-arg mv (no flags, no glob)
  const cleanArgs = args.filter(a => !a.startsWith("-"));
  if (cleanArgs.length !== 2) return null;

  return { src: cleanArgs[0], dst: cleanArgs[1] };
}

function appendUndoBtn(src, dst) {
  const d = document.createElement("div");
  d.className = "msg undo-msg";
  d.innerHTML = `
    <span class="undo-icon">↩</span>
    <span class="undo-text">Moved <code>${escHtml(src)}</code> → <code>${escHtml(dst)}</code></span>
    <button class="undo-btn">Undo Move</button>
  `;

  const btn = d.querySelector(".undo-btn");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Undoing…";
    setStatus("Undoing…", "blue");

    // Reverse: mv dst src  (put it back)
    const reverseCmd = `mv "${dst}" "${src}"`;
    try {
      const res = await fetch("/api/confirm-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: reverseCmd, confirmed: true })
      });
      const data = await res.json();
      renderEvents(data.events || []);
      d.remove(); // Remove undo row after success
    } catch(e) {
      appendError("Undo failed: " + e.message);
    }
    setStatus("Ready", "green");
  });

  messagesEl.appendChild(d);
  scrollBottom();
}

// ── Onboarding Chips ──────────────────────────────────────────
const ONBOARDING_PROMPTS = [
  "Organize my Downloads folder",
  "What's taking up space on my Desktop?",
  "List files modified today in Documents",
  "How much free disk space do I have?",
  "Show me the largest files in Downloads",
];

let onboardingEl = null;

function appendOnboarding() {
  const d = document.createElement("div");
  d.id = "onboarding";
  d.className = "onboarding";
  d.innerHTML = `<p class="onboarding-hint">Try asking…</p><div class="onboarding-chips"></div>`;

  const chips = d.querySelector(".onboarding-chips");
  ONBOARDING_PROMPTS.forEach(prompt => {
    const chip = document.createElement("button");
    chip.className = "onboarding-chip";
    chip.textContent = prompt;
    chip.addEventListener("click", () => {
      inputEl.value = prompt;
      autoResize();
      removeOnboarding();
      sendMessage();
    });
    chips.appendChild(chip);
  });

  messagesEl.appendChild(d);
  onboardingEl = d;
  scrollBottom();
}

function removeOnboarding() {
  if (onboardingEl) {
    onboardingEl.remove();
    onboardingEl = null;
  }
}

// ── Message Renderers ─────────────────────────────────────────
function appendUser(text) {
  removeOnboarding();
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

  const copyText = [command, output ? output.trim() : ""].filter(Boolean).join("\n\n");
  const copyBtn = makeCopyBtn(copyText);

  d.innerHTML = `
    <div class="ran-header">
      <span class="ran-arrow">▶</span>
      <span class="ran-cmd-text">${escHtml(command)}</span>
    </div>
    ${output ? `<div class="ran-output">${escHtml(output.trim())}</div>` : ""}
  `;
  d.querySelector(".ran-header").appendChild(copyBtn);

  messagesEl.appendChild(d);
  scrollBottom();

  // Offer undo if this was an mv command
  const mv = parseMvCommand(command);
  if (mv && output && !output.toLowerCase().includes("error")) {
    appendUndoBtn(mv.src, mv.dst);
  }
}

function appendRecon(command, output) {
  const d = document.createElement("div");
  d.className = "msg recon-msg";

  const copyBtn = output ? makeCopyBtn(output.trim()) : null;

  d.innerHTML = `
    <div class="recon-header">
      <span>⟳</span> Scanning: ${escHtml(command)}
    </div>
    ${output ? `<div class="ran-output">${escHtml(output.trim())}</div>` : ""}
  `;
  if (copyBtn) d.querySelector(".recon-header").appendChild(copyBtn);

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
    } else if (ev.type === "choose") {
      showChoose(ev.content, ev.options);
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

// ── Choose Dialog ─────────────────────────────────────────────
function showChoose(label, options) {
  chooseLabel.textContent = label;
  chooseOptions.innerHTML = "";

  for (const option of options) {
    const btn = document.createElement("button");
    btn.className = "choose-btn";
    btn.textContent = option;
    btn.onclick = async () => {
      chooseOverlay.classList.add("hidden");
      setStatus("Processing…", "blue");
      try {
        const res = await fetch("/api/choose-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ folder: option })
        });
        const data = await res.json();
        renderEvents(data.events || []);
      } catch(e) {
        appendError(e.message);
      }
      setStatus("Ready", "green");
    };
    chooseOptions.appendChild(btn);
  }

  chooseOverlay.classList.remove("hidden");
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
  appendOnboarding();
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
appendOnboarding();
inputEl.focus();