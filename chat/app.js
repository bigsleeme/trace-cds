"use strict";

const $ = (id) => document.getElementById(id);
const app = $("app");
const messagesEl = $("messages");
const threadEl = $("thread");
const inputEl = $("input");
const sendBtn = $("send");

const state = {
  answerMode: null,
  sourceMode: null,
  history: [],      // prior user questions (for follow-up rewriting)
  busy: false,
};

// -------------------------------------------------------------- boot
async function boot() {
  let cfg;
  try {
    cfg = await (await fetch("api/config")).json();
  } catch (e) {
    cfg = { answer_modes: ["Quoted from label"], default_answer_mode: "Quoted from label",
            source_modes: ["FDA labels only"], default_source_mode: "FDA labels only",
            drugs: [], examples: [], version: "", home_url: "https://tracecds.com" };
  }
  state.answerMode = cfg.default_answer_mode;
  state.sourceMode = cfg.default_source_mode;

  $("ver").textContent = cfg.version ? "v" + cfg.version : "";
  $("home-link").href = cfg.home_url || "https://tracecds.com";
  $("drugs").textContent = (cfg.drugs || []).join(", ");

  buildSeg($("answer-modes"), cfg.answer_modes, cfg.default_answer_mode, (v) => state.answerMode = v);
  buildSeg($("source-modes"), cfg.source_modes, cfg.default_source_mode, (v) => state.sourceMode = v);

  const ex = $("examples");
  (cfg.examples || []).forEach((q) => {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = q;
    b.onclick = () => { if (!state.busy) submit(q); };
    ex.appendChild(b);
  });

  // local dev convenience: point Home at the local homepage if running on localhost
  if (["localhost", "127.0.0.1"].includes(location.hostname)) {
    $("home-link").href = "http://localhost:8008";
  }
}

function buildSeg(container, options, selected, onChange) {
  container.innerHTML = "";
  options.forEach((opt) => {
    const b = document.createElement("button");
    b.className = "seg-opt" + (opt === selected ? " on" : "");
    b.innerHTML = `<span class="rad"></span><span>${escapeHtml(opt)}</span>`;
    b.onclick = () => {
      [...container.children].forEach((c) => c.classList.remove("on"));
      b.classList.add("on");
      onChange(opt);
    };
    container.appendChild(b);
  });
}

// -------------------------------------------------------------- send flow
async function submit(text) {
  text = (text || "").trim();
  if (!text || state.busy) return;
  app.classList.remove("empty");
  addUserMessage(text);
  inputEl.value = "";
  autoGrow();
  setBusy(true);

  const thinking = addThinking();

  let data;
  try {
    const res = await fetch("api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: text,
        answer_mode: state.answerMode,
        source_mode: state.sourceMode,
        history: state.history,
      }),
    });
    data = await res.json();
  } catch (e) {
    data = { html: '<p class="muted">Sorry — something went wrong reaching the server. Please try again.</p>' };
  }

  thinking.remove();
  addBotMessage(data.html || '<p class="muted">No response.</p>');
  state.history.push(text);
  setBusy(false);
  scrollToBottom();
}

function addUserMessage(text) {
  const row = document.createElement("div");
  row.className = "msg user";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  row.appendChild(bubble);
  messagesEl.appendChild(row);
  scrollToBottom();
}

function botRow() {
  const row = document.createElement("div");
  row.className = "msg bot";
  row.innerHTML = '<div class="avatar">T</div><div class="bot-body"></div>';
  messagesEl.appendChild(row);
  return row.querySelector(".bot-body");
}

function addThinking() {
  const body = botRow();
  body.innerHTML = '<div class="thinking"><span></span><span></span><span></span></div>';
  scrollToBottom();
  return body.parentElement; // the row, so caller can .remove()
}

function addBotMessage(htmlStr) {
  const body = botRow();
  body.innerHTML = htmlStr;
}

// -------------------------------------------------------------- ui bits
function setBusy(b) {
  state.busy = b;
  updateSend();
  inputEl.disabled = false; // keep typeable
}
function updateSend() {
  sendBtn.disabled = state.busy || inputEl.value.trim() === "";
}
function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + "px";
}
function scrollToBottom() {
  requestAnimationFrame(() => { threadEl.scrollTop = threadEl.scrollHeight; });
}
function newChat() {
  messagesEl.innerHTML = "";
  state.history = [];
  app.classList.add("empty");
  inputEl.value = "";
  autoGrow();
  updateSend();
  inputEl.focus();
}
function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// -------------------------------------------------------------- events
$("composer").addEventListener("submit", (e) => { e.preventDefault(); submit(inputEl.value); });
inputEl.addEventListener("input", () => { autoGrow(); updateSend(); });
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(inputEl.value); }
});
$("new-chat").addEventListener("click", newChat);
$("toggle").addEventListener("click", () => app.classList.toggle("collapsed"));
$("scrim").addEventListener("click", () => app.classList.add("collapsed"));

// start collapsed on small screens
if (window.matchMedia("(max-width:820px)").matches) app.classList.add("collapsed");

boot();
inputEl.focus();
