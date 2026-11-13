// Kitchen Coach - user interface and cooking engine.
import { parseRecipeFile, RecipeError, formatSeconds } from "./parser.js";

const VERSION = "1.0.0";
const RING = 2 * Math.PI * 96;
const ALARM_REPEAT_MS = 20000;
const ALARM_WINDOW_MS = 120000;

// ---------------------------------------------------------------- helpers
const $ = (sel) => document.querySelector(sel);
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode / storage full */ }
  },
  remove(key) { try { localStorage.removeItem(key); } catch { /* ignore */ } },
};
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v !== null && v !== undefined) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c);
  return node;
}
const newId = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
function mmss(ms) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}
function spokenDuration(sec) {
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const part = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const out = [];
  if (h) out.push(part(h, "hour"));
  if (m) out.push(part(m, "minute"));
  if (s || !out.length) out.push(part(s, "second"));
  return out.join(" ");
}
function speakable(text) {
  return text
    .replace(/(\d)\s*½/g, "$1 and a half").replace(/½/g, "half").replace(/(\d)\s*¼/g, "$1 and a quarter")
    .replace(/(\d)\s*¾/g, "$1 and three quarters")
    .replace(/\btbsps?\b/gi, "tablespoons").replace(/\btsps?\b/gi, "teaspoons")
    .replace(/(\d)\s*g\b/g, "$1 grams").replace(/(\d)\s*kg\b/gi, "$1 kilos").replace(/(\d)\s*ml\b/gi, "$1 millilitres")
    .replace(/\bmins?\b/gi, "minutes").replace(/\bhrs?\b/gi, "hours").replace(/\bsecs?\b/gi, "seconds")
    .replace(/(\d)\s*°?\s*C\b/g, "$1 degrees").replace(/(\d)\s*°?\s*F\b/g, "$1 degrees Fahrenheit")
    .replace(/\bgas\s*(\d)/gi, "gas mark $1");
}
let toastTimer;
function toast(msg, ms = 3200) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}
function confirmBox(message, okLabel = "OK") {
  const dlg = $("#confirmDialog");
  $("#confirmText").textContent = message;
  $("#confirmYes").textContent = okLabel;
  return new Promise((resolve) => {
    dlg.addEventListener("close", () => resolve(dlg.returnValue === "yes"), { once: true });
    dlg.returnValue = "";
    dlg.showModal();
  });
}

// ---------------------------------------------------------------- settings
const DEFAULT_SETTINGS = { voice: true, voiceName: "", rate: 1, autoStart: false, chime: true, repeatAlarm: true, wake: true };
let settings = { ...DEFAULT_SETTINGS, ...store.get("kc.settings", {}) };
const saveSettings = () => store.set("kc.settings", settings);

// ---------------------------------------------------------------- speech & sound
let voices = [];
function loadVoices() {
  if (!("speechSynthesis" in window)) return;
  voices = speechSynthesis.getVoices();
  const select = $("#setVoiceName");
  const english = voices.filter((v) => /^en/i.test(v.lang));
  const sorted = [...english.filter((v) => /GB/i.test(v.lang)), ...english.filter((v) => !/GB/i.test(v.lang))];
  select.replaceChildren(el("option", { value: "", text: "Default voice" }),
    ...sorted.map((v) => el("option", { value: v.voiceURI, text: `${v.name} (${v.lang})` })));
  select.value = settings.voiceName;
}
function say(text) {
  if (!settings.voice || !("speechSynthesis" in window) || !text) return;
  const u = new SpeechSynthesisUtterance(speakable(text));
  const v = voices.find((x) => x.voiceURI === settings.voiceName);
  if (v) { u.voice = v; u.lang = v.lang; } else u.lang = "en-GB";
  u.rate = Number(settings.rate) || 1;
  const busy = speechSynthesis.speaking || speechSynthesis.pending;
  speechSynthesis.cancel();
  if (busy) setTimeout(() => speechSynthesis.speak(u), 80); // Chrome drops speak() straight after cancel()
  else speechSynthesis.speak(u);
}
function primeSpeech() { // iOS only allows speech after a tap has started it once
  if ("speechSynthesis" in window && settings.voice) {
    const u = new SpeechSynthesisUtterance(" ");
    u.volume = 0;
    speechSynthesis.speak(u);
  }
}
let audioCtx = null;
function unlockAudio() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
  } catch { audioCtx = null; }
}
function chime() {
  if (!settings.chime || !audioCtx) return;
  if (audioCtx.state === "suspended") audioCtx.resume();
  const now = audioCtx.currentTime;
  [0, 0.28, 0.56].forEach((offset, i) => {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.frequency.value = [880, 1175, 1568][i];
    gain.gain.setValueAtTime(0.0001, now + offset);
    gain.gain.exponentialRampToValueAtTime(0.5, now + offset + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.5);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(now + offset);
    osc.stop(now + offset + 0.55);
  });
  if (navigator.vibrate) navigator.vibrate([250, 120, 250]);
}

let wakeLock = null;
async function requestWake() {
  if (!settings.wake || !("wakeLock" in navigator) || wakeLock) return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
    wakeLock.addEventListener("release", () => { wakeLock = null; });
  } catch { wakeLock = null; }
}
function releaseWake() { if (wakeLock) { wakeLock.release().catch(() => {}); wakeLock = null; } }

// ---------------------------------------------------------------- server (Windows) mode
let serverMode = false;
async function detectServer() {
  if (location.protocol === "file:") return false;
  try {
    const r = await fetch("api/health", { cache: "no-store" });
    if (!r.ok) return false;
    const j = await r.json();
    return j.app === "kitchen-coach";
  } catch { return false; }
}
async function parseOnServer(file) {
  const fd = new FormData();
  fd.append("recipe", file, file.name);
  const r = await fetch("api/parse", { method: "POST", body: fd });
  let body;
  try { body = await r.json(); } catch { throw new Error(`Server replied ${r.status}`); }
  if (r.status === 400 || r.status === 413 || r.status === 422) {
    throw new RecipeError(body.error || "That file couldn't be read.");
  }
  if (!r.ok) throw new Error(body.error || `Server replied ${r.status}`); // falls back to in-app reading
  return body;
}

// ---------------------------------------------------------------- library
let library = store.get("kc.recipes", []);
const saveLibrary = () => store.set("kc.recipes", library);
function upsertRecipe(r) {
  const copy = JSON.parse(JSON.stringify({ ...r, savedAt: Date.now() }));
  const i = library.findIndex((x) => x.id === r.id);
  if (i >= 0) library[i] = copy; else library.unshift(copy);
  saveLibrary();
  renderLibrary();
}
function renderLibrary() {
  const list = $("#library");
  $("#emptyLibrary").hidden = library.length > 0;
  list.replaceChildren(...library.map((r) => {
    const timers = r.steps.filter((s) => s.seconds > 0).length;
    return el("li", {},
      el("div", { class: "meta" },
        el("strong", { text: r.title || "Untitled recipe" }),
        el("span", { text: `${r.steps.length} steps · ${timers} timer${timers === 1 ? "" : "s"}` })),
      el("button", { class: "btn ghost", text: "Open", onclick: () => openReview(JSON.parse(JSON.stringify(r))) }),
      el("button", { class: "btn primary", text: "Cook", onclick: () => startCooking(JSON.parse(JSON.stringify(r))) }),
      el("button", {
        class: "mini", "aria-label": `Delete ${r.title}`, title: "Delete", text: "✕",
        onclick: async () => {
          if (await confirmBox(`Delete “${r.title}” from your recipes?`, "Delete")) {
            library = library.filter((x) => x.id !== r.id);
            saveLibrary();
            renderLibrary();
          }
        },
      }));
  }));
}

// ---------------------------------------------------------------- views
function showView(name) {
  $("#homeView").hidden = name !== "home";
  $("#reviewView").hidden = name !== "review";
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------- upload
function setBusy(on) { $("#busy").hidden = !on; $("#dropzone").style.pointerEvents = on ? "none" : ""; }
function showError(msg) { const e = $("#homeError"); e.textContent = msg; e.hidden = !msg; }

async function handleFile(file) {
  if (!file) return;
  showError("");
  setBusy(true);
  try {
    let result;
    if (serverMode) {
      try { result = await parseOnServer(file); } catch (err) {
        if (err instanceof RecipeError) throw err;
        console.warn("Local engine unavailable, reading in the app instead", err);
        result = await parseRecipeFile(file);
      }
    } else {
      result = await parseRecipeFile(file);
    }
    openReview({ id: newId(), fileName: file.name, ...result });
  } catch (err) {
    if (!(err instanceof RecipeError)) console.error(err);
    showError(err instanceof RecipeError ? err.message
      : `Sorry - something went wrong reading that file (${err && err.message ? err.message : err}).`);
  } finally {
    setBusy(false);
    $("#fileInput").value = "";
  }
}

// ---------------------------------------------------------------- review / edit
let current = null;

function openReview(r) {
  current = r;
  current.steps = current.steps.map((s) => ({ text: s.text, seconds: s.seconds || 0, note: s.note || "" }));
  $("#titleInput").value = r.title || "";
  const chips = $("#infoChips");
  const labels = { serves: "Serves", prep: "Prep", cook: "Cook", total: "Total" };
  chips.replaceChildren(...Object.entries(r.info || {}).filter(([k]) => labels[k])
    .map(([k, v]) => el("span", { class: "chip" }, el("b", { text: labels[k] }), v)));
  if (r.source) chips.append(el("span", { class: "chip" }, el("b", { text: "From" }), r.source.toUpperCase()));
  const warn = $("#warnings");
  warn.hidden = !(r.warnings && r.warnings.length);
  warn.textContent = (r.warnings || []).join(" ");
  renderIngredients($("#ingredientList"), r.ingredients || []);
  $("#ingCount").textContent = r.ingredients && r.ingredients.length ? `(${r.ingredients.length})` : "(none found)";
  $("#ingredientsBox").open = false;
  renderSteps();
  showView("review");
}

function renderIngredients(list, items) {
  list.replaceChildren(...items.map((text) => (text.endsWith(":")
    ? el("li", { class: "group", text: text.replace(/:$/, "") })
    : el("li", {}, el("label", {}, el("input", { type: "checkbox" }), el("span", { text }))))));
}

function renderSteps() {
  const list = $("#stepList");
  list.replaceChildren(...current.steps.map((step, i) => {
    const mins = Math.floor(step.seconds / 60), secs = step.seconds % 60;
    return el("li", { class: "step-item", "data-i": i },
      el("div", { class: "step-head" },
        el("span", { class: "step-num", text: String(i + 1) }),
        el("span", { class: step.seconds ? "has-timer" : "muted", text: step.seconds ? `⏱ ${formatSeconds(step.seconds)}` : "No timer" }),
        el("span", { class: "spacer" }),
        el("button", { class: "mini", "data-act": "up", title: "Move up", "aria-label": "Move step up", disabled: i === 0, text: "↑" }),
        el("button", { class: "mini", "data-act": "down", title: "Move down", "aria-label": "Move step down", disabled: i === current.steps.length - 1, text: "↓" }),
        el("button", { class: "mini", "data-act": "del", title: "Delete step", "aria-label": "Delete step", text: "✕" })),
      el("textarea", { "data-field": "text", rows: 2, "aria-label": `Step ${i + 1} instructions` }, step.text),
      el("div", { class: "timer-edit" },
        el("span", { text: "Timer" }),
        el("input", { type: "number", inputmode: "numeric", min: 0, max: 1440, value: mins, "data-field": "min", "aria-label": "Minutes" }),
        el("span", { text: "min" }),
        el("input", { type: "number", inputmode: "numeric", min: 0, max: 59, value: secs, "data-field": "sec", "aria-label": "Seconds" }),
        el("span", { text: "sec" })),
      step.note ? el("p", { class: "step-note-edit", text: `⚠ ${step.note}` }) : null);
  }));
  requestAnimationFrame(() => list.querySelectorAll("textarea").forEach(autosize));
  updateTotal();
}

function autosize(ta) {
  ta.style.height = "auto";
  ta.style.height = `${ta.scrollHeight + 2}px`;
}

function updateTotal() {
  const total = current.steps.reduce((a, s) => a + (s.seconds || 0), 0);
  const timed = current.steps.filter((s) => s.seconds > 0).length;
  $("#totalTime").textContent = `${current.steps.length} steps · ${timed} timers${total ? ` · ${formatSeconds(total)} of timers` : ""}`;
}

function bindReview() {
  const list = $("#stepList");
  list.addEventListener("input", (e) => {
    const li = e.target.closest(".step-item");
    if (!li) return;
    const step = current.steps[Number(li.dataset.i)];
    const field = e.target.dataset.field;
    if (field === "text") { step.text = e.target.value; autosize(e.target); }
    if (field === "min" || field === "sec") {
      const min = clamp(Math.floor(Number(li.querySelector('[data-field="min"]').value) || 0), 0, 1440);
      const sec = clamp(Math.floor(Number(li.querySelector('[data-field="sec"]').value) || 0), 0, 59);
      step.seconds = min * 60 + sec;
      const badge = li.querySelector(".step-head span:nth-child(2)");
      badge.className = step.seconds ? "has-timer" : "muted";
      badge.textContent = step.seconds ? `⏱ ${formatSeconds(step.seconds)}` : "No timer";
      updateTotal();
    }
  });
  list.addEventListener("change", (e) => { // tidy the number boxes once the cook leaves them
    if (e.target.dataset.field === "min" || e.target.dataset.field === "sec") renderSteps();
  });
  list.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const i = Number(btn.closest(".step-item").dataset.i);
    const s = current.steps;
    if (btn.dataset.act === "up" && i > 0) [s[i - 1], s[i]] = [s[i], s[i - 1]];
    if (btn.dataset.act === "down" && i < s.length - 1) [s[i + 1], s[i]] = [s[i], s[i + 1]];
    if (btn.dataset.act === "del") s.splice(i, 1);
    renderSteps();
  });
  $("#addStep").addEventListener("click", () => {
    current.steps.push({ text: "", seconds: 0, note: "" });
    renderSteps();
    const areas = document.querySelectorAll("#stepList textarea");
    areas[areas.length - 1].focus();
  });
  $("#titleInput").addEventListener("input", (e) => { current.title = e.target.value; });
  $("#saveRecipe").addEventListener("click", () => {
    if (validate()) { upsertRecipe(current); toast("Recipe saved"); }
  });
  $("#startCooking").addEventListener("click", () => {
    if (!validate()) return;
    upsertRecipe(current);
    startCooking(JSON.parse(JSON.stringify(current)));
  });
  $("#reviewBack").addEventListener("click", () => { showView("home"); renderLibrary(); });
}

function validate() {
  current.title = ($("#titleInput").value || "").trim() || "My recipe";
  current.steps = current.steps.map((s) => ({ ...s, text: s.text.trim() }));
  const blank = current.steps.findIndex((s) => !s.text);
  if (!current.steps.length) { toast("Add at least one step first."); return false; }
  if (blank >= 0) {
    toast(`Step ${blank + 1} is empty - type the instruction or delete it.`);
    document.querySelectorAll("#stepList textarea")[blank].focus();
    return false;
  }
  return true;
}

// ---------------------------------------------------------------- cooking engine
let cook = null;   // { recipe, index, timers: Map<stepIndex, Timer> }
// Timer: { step, total(ms), remaining(ms), endAt, state: idle|running|paused|done|finished, doneAt, lastChime }

function newTimer(step, seconds) {
  return { step, total: seconds * 1000, remaining: seconds * 1000, endAt: 0, state: "idle", doneAt: 0, lastChime: 0 };
}
const left = (t) => (t.state === "running" ? Math.max(0, t.endAt - Date.now()) : t.state === "idle" || t.state === "paused" ? t.remaining : 0);
function startTimer(t) { t.endAt = Date.now() + t.remaining; t.state = "running"; }
function pauseTimer(t) { t.remaining = Math.max(0, t.endAt - Date.now()); t.state = "paused"; }
function finishTimer(t) { t.state = "finished"; }

function startCooking(r, resume = null) {
  unlockAudio();
  primeSpeech();
  cook = { recipe: r, index: 0, timers: new Map() };
  if (resume) {
    cook.index = clamp(resume.index, 0, r.steps.length);
    for (const t of resume.timers || []) cook.timers.set(t.step, { ...t });
  }
  $("#cookRecipeTitle").textContent = r.title;
  renderIngredients($("#cookIngredients"), r.ingredients || []);
  $("#cookView").hidden = false;
  document.body.style.overflow = "hidden";
  requestWake();
  showStep(true);
  if (resume) {
    const overdue = [...cook.timers.values()].filter((t) => t.state === "done");
    if (overdue.length) { chime(); toast(`${overdue.length} timer${overdue.length > 1 ? "s" : ""} finished while the app was closed`); }
  }
}

function stepTimer() { return cook.timers.get(cook.index) || null; }

function showStep(speak) {
  const steps = cook.recipe.steps;
  const n = steps.length;
  $("#progressBar").style.width = `${(Math.min(cook.index, n) / n) * 100}%`;
  // forget timers that were never started on steps we have left
  for (const [k, t] of cook.timers) if (k !== cook.index && t.state === "idle") cook.timers.delete(k);

  if (cook.index >= n) {
    $("#cookPosition").textContent = "Finished";
    $("#stepLabel").textContent = "All done";
    $("#stepText").textContent = "Recipe complete - enjoy your meal!";
    $("#stepNote").hidden = true;
    $("#timerWrap").hidden = true;
    $("#repeatBtn").disabled = $("#plusBtn").disabled = $("#restartBtn").disabled = true;
    $("#nextBtn").disabled = true;
    if (speak) say("Recipe complete. Enjoy your meal!");
    render();
    saveSession();
    return;
  }
  const step = steps[cook.index];
  $("#timerWrap").hidden = false;
  $("#repeatBtn").disabled = $("#plusBtn").disabled = false;
  $("#nextBtn").disabled = false;
  $("#cookPosition").textContent = `Step ${cook.index + 1} of ${n}`;
  $("#stepLabel").textContent = `Step ${cook.index + 1}`;
  $("#stepText").textContent = step.text;
  $("#stepNote").hidden = !step.note;
  $("#stepNote").textContent = step.note ? `⚠ ${step.note}` : "";

  let t = stepTimer();
  if (!t && step.seconds > 0) {
    t = newTimer(cook.index, step.seconds);
    cook.timers.set(cook.index, t);
    if (settings.autoStart) startTimer(t);
  }
  if (speak) say(stepSpeech(step, t));
  render();
  saveSession();
}

function stepSpeech(step, t) {
  let msg = `Step ${cook.index + 1}. ${step.text}`;
  if (!t) return msg;
  if (t.state === "running") msg += ` The timer is running, ${spokenDuration(left(t) / 1000)} left.`;
  else if (t.state === "idle") {
    msg += settings.autoStart ? ` Timer started for ${spokenDuration(t.total / 1000)}.`
      : ` There is a ${spokenDuration(t.total / 1000)} timer. Tap start timer when you're ready.`;
  } else if (t.state === "paused") msg += " The timer is paused.";
  return msg;
}

function render() {
  if (!cook) return;
  const t = cook.index < cook.recipe.steps.length ? stepTimer() : null;
  const wrap = $("#timerWrap");
  const primary = $("#primaryBtn");
  primary.classList.remove("pause", "alarm");
  wrap.classList.remove("running", "done", "none");
  $("#restartBtn").disabled = !t;
  if (cook.index >= cook.recipe.steps.length) {
    primary.textContent = "Finish";
  } else if (!t) {
    wrap.classList.add("none");
    $("#clock").textContent = "--:--";
    $("#timerState").textContent = "No timer for this step";
    $("#ringFg").style.strokeDashoffset = RING;
    primary.textContent = "Next step";
  } else {
    const ms = left(t);
    $("#clock").textContent = mmss(ms);
    $("#ringFg").style.strokeDashoffset = RING * (1 - (t.total ? ms / t.total : 0));
    const labels = { idle: ["Ready", "Start timer"], running: ["Running", "Pause"], paused: ["Paused", "Resume"],
      done: ["Time's up!", "Stop alarm"], finished: ["Finished", "Next step"] };
    $("#timerState").textContent = labels[t.state][0];
    primary.textContent = labels[t.state][1];
    if (t.state === "running") { wrap.classList.add("running"); primary.classList.add("pause"); }
    if (t.state === "done") { wrap.classList.add("done"); primary.classList.add("alarm"); }
  }
  renderTray();
}

const trayButtons = new Map(); // step -> button, reused so taps aren't lost between ticks
function renderTray() {
  const tray = $("#tray");
  const others = [...cook.timers.values()]
    .filter((t) => t.step !== cook.index && ["running", "paused", "done"].includes(t.state))
    .sort((a, b) => a.step - b.step);
  const wanted = new Set(others.map((t) => t.step));
  for (const [step, btn] of trayButtons) if (!wanted.has(step)) { btn.remove(); trayButtons.delete(step); }
  for (const t of others) {
    let btn = trayButtons.get(t.step);
    if (!btn) {
      btn = el("button", { class: "pill" }, el("b", { text: `Step ${t.step + 1}` }), el("span"));
      btn.addEventListener("click", () => {
        const timer = cook && cook.timers.get(t.step);
        if (!timer) return;
        if (timer.state === "done") { finishTimer(timer); render(); saveSession(); } else goTo(timer.step);
      });
      trayButtons.set(t.step, btn);
      tray.append(btn);
    }
    btn.className = `pill ${t.state}`;
    btn.title = t.state === "done" ? "Stop alarm" : "Go to this step";
    btn.lastChild.textContent = t.state === "done" ? "done - tap to stop" : `${t.state === "paused" ? "⏸ " : ""}${mmss(left(t))}`;
  }
}

function goTo(index) {
  cook.index = clamp(index, 0, cook.recipe.steps.length);
  showStep(true);
}
function next() {
  const t = stepTimer();
  if (t && t.state === "done") finishTimer(t);
  if (t && t.state === "running") toast(`Step ${cook.index + 1} timer keeps running below`);
  if (cook.index < cook.recipe.steps.length) goTo(cook.index + 1);
}
function back() { if (cook.index > 0) goTo(cook.index - 1); }

function primaryAction() {
  unlockAudio();
  if (cook.index >= cook.recipe.steps.length) { exitCooking(); return; }
  const t = stepTimer();
  if (!t || t.state === "finished") { next(); return; }
  if (t.state === "idle") { startTimer(t); say(`Timer started. ${spokenDuration(t.total / 1000)}.`); }
  else if (t.state === "running") { pauseTimer(t); say("Timer paused."); }
  else if (t.state === "paused") { startTimer(t); say("Timer resumed."); }
  else if (t.state === "done") { finishTimer(t); if ("speechSynthesis" in window) speechSynthesis.cancel(); }
  render();
  saveSession();
}
function addMinute() {
  unlockAudio();
  if (cook.index >= cook.recipe.steps.length) return;
  let t = stepTimer();
  if (!t) { t = newTimer(cook.index, 60); cook.timers.set(cook.index, t); startTimer(t); }
  else if (t.state === "running") { t.endAt += 60000; t.total += 60000; }
  else if (t.state === "done" || t.state === "finished") { t.total = t.remaining = 60000; startTimer(t); }
  else { t.remaining += 60000; t.total += 60000; }
  toast("Added one minute");
  render();
  saveSession();
}
function restartTimer() {
  const t = stepTimer();
  if (!t) return;
  const step = cook.recipe.steps[cook.index];
  t.total = t.remaining = step.seconds ? step.seconds * 1000 : 60000;
  startTimer(t);
  say(`Timer restarted. ${spokenDuration(t.total / 1000)}.`);
  render();
  saveSession();
}

function onTimerDone(t) {
  t.state = "done";
  t.doneAt = t.endAt;
  t.lastChime = Date.now();
  chime();
  const steps = cook.recipe.steps;
  if (t.step === cook.index) {
    const nxt = steps[t.step + 1];
    say(`Time's up for step ${t.step + 1}. ` + (nxt ? `When you're ready, the next step is: ${nxt.text}` : "That was the last step."));
  } else {
    const short = steps[t.step].text.split(/[.!?]/)[0].slice(0, 80);
    say(`Time's up for step ${t.step + 1}: ${short}.`);
    toast(`Step ${t.step + 1} timer finished`);
  }
}

async function exitCooking() {
  const live = cook && [...cook.timers.values()].some((t) => ["running", "paused", "done"].includes(t.state));
  if (live && !(await confirmBox("Stop cooking? Any running timers will be cancelled.", "Stop cooking"))) return;
  cook = null;
  trayButtons.forEach((b) => b.remove());
  trayButtons.clear();
  store.remove("kc.session");
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  releaseWake();
  $("#cookView").hidden = true;
  document.body.style.overflow = "";
  showView("home");
  renderLibrary();
  checkSession();
}

// ---------------------------------------------------------------- session (survives reloads)
let lastSave = 0;
function saveSession() {
  if (!cook) return;
  lastSave = Date.now();
  store.set("kc.session", { recipe: cook.recipe, index: cook.index, timers: [...cook.timers.values()], savedAt: Date.now() });
}
function checkSession() {
  const s = store.get("kc.session", null);
  const banner = $("#resumeBanner");
  if (!s || !s.recipe || Date.now() - s.savedAt > 24 * 3600 * 1000) { banner.hidden = true; return; }
  banner.hidden = false;
  $("#resumeText").textContent = ` ${s.recipe.title} - step ${Math.min(s.index + 1, s.recipe.steps.length)} of ${s.recipe.steps.length}`;
}

// ---------------------------------------------------------------- ticker (runs in a worker so timers stay accurate)
let lastBeat = 0;
function tick() {
  const now = Date.now();
  if (serverMode && now - lastBeat > 20000) {
    lastBeat = now;
    fetch("api/heartbeat", { method: "POST", keepalive: true }).catch(() => {});
  }
  if (!cook) return;
  let changed = false;
  for (const t of cook.timers.values()) {
    if (t.state === "running" && t.endAt <= now) { onTimerDone(t); changed = true; }
    else if (t.state === "done" && settings.repeatAlarm && now - t.doneAt < ALARM_WINDOW_MS && now - t.lastChime >= ALARM_REPEAT_MS) {
      t.lastChime = now;
      chime();
    }
  }
  render();
  if (changed || now - lastSave > 5000) saveSession();
}
function startTicker() {
  try {
    const src = URL.createObjectURL(new Blob(["setInterval(() => postMessage(0), 250);"], { type: "text/javascript" }));
    const worker = new Worker(src);
    worker.onmessage = tick;
  } catch {
    setInterval(tick, 250);
  }
}

// ---------------------------------------------------------------- settings dialog
function bindSettings() {
  const dlg = $("#settingsDialog");
  const fields = { setVoice: "voice", setAutoStart: "autoStart", setChime: "chime", setRepeatAlarm: "repeatAlarm", setWake: "wake" };
  $("#settingsBtn").addEventListener("click", () => {
    for (const [id, key] of Object.entries(fields)) $("#" + id).checked = !!settings[key];
    $("#setRate").value = settings.rate;
    $("#rateOut").textContent = Number(settings.rate).toFixed(1);
    loadVoices();
    dlg.showModal();
  });
  for (const [id, key] of Object.entries(fields)) {
    $("#" + id).addEventListener("change", (e) => {
      settings[key] = e.target.checked;
      saveSettings();
      if (key === "wake") { if (settings.wake && cook) requestWake(); else releaseWake(); }
    });
  }
  $("#setRate").addEventListener("input", (e) => {
    settings.rate = Number(e.target.value);
    $("#rateOut").textContent = settings.rate.toFixed(1);
    saveSettings();
  });
  $("#setVoiceName").addEventListener("change", (e) => { settings.voiceName = e.target.value; saveSettings(); });
  $("#testVoice").addEventListener("click", () => {
    unlockAudio();
    if (!("speechSynthesis" in window)) { toast("This browser can't speak - timers will still chime."); return; }
    const was = settings.voice;
    settings.voice = true;
    say("Preheat the oven to 200C. Bake for 25 minutes.");
    settings.voice = was;
    chime();
  });
}

// ---------------------------------------------------------------- start-up
async function init() {
  bindReview();
  bindSettings();

  const input = $("#fileInput");
  input.addEventListener("change", () => handleFile(input.files[0]));
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, () => dz.classList.remove("drag")));
  dz.addEventListener("drop", (e) => { e.preventDefault(); handleFile(e.dataTransfer.files[0]); });
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  $("#sampleBtn").addEventListener("click", async () => {
    try {
      const blob = await (await fetch("samples/beef_ragu.pdf")).blob();
      handleFile(new File([blob], "beef_ragu.pdf", { type: "application/pdf" }));
    } catch { showError("The sample recipe couldn't be loaded."); }
  });
  $("#homeLink").addEventListener("click", (e) => { e.preventDefault(); if (!cook) { showView("home"); renderLibrary(); } });

  $("#primaryBtn").addEventListener("click", primaryAction);
  $("#nextBtn").addEventListener("click", () => { unlockAudio(); next(); });
  $("#backBtn").addEventListener("click", () => { unlockAudio(); back(); });
  $("#repeatBtn").addEventListener("click", () => {
    unlockAudio();
    if (cook && cook.index < cook.recipe.steps.length) say(stepSpeech(cook.recipe.steps[cook.index], stepTimer()));
  });
  $("#plusBtn").addEventListener("click", addMinute);
  $("#restartBtn").addEventListener("click", restartTimer);
  $("#exitCook").addEventListener("click", exitCooking);
  $("#showIngredients").addEventListener("click", () => $("#ingredientsDialog").showModal());
  document.addEventListener("keydown", (e) => {
    if (!cook || $("#cookView").hidden || document.querySelector("dialog[open]")) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    const k = e.key;
    if (k === " " || k === "Enter") { e.preventDefault(); primaryAction(); }
    else if (k === "ArrowRight" || k === "n") next();
    else if (k === "ArrowLeft" || k === "b") back();
    else if (k === "r" || k === "R") $("#repeatBtn").click();
    else if (k === "+" || k === "=") addMinute();
    else if (k === "Escape") exitCooking();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && cook) { requestWake(); tick(); }
  });

  $("#resumeSession").addEventListener("click", () => {
    const s = store.get("kc.session", null);
    if (s) startCooking(s.recipe, s);
  });
  $("#discardSession").addEventListener("click", () => { store.remove("kc.session"); checkSession(); });

  if ("speechSynthesis" in window) {
    loadVoices();
    speechSynthesis.addEventListener?.("voiceschanged", loadVoices);
  }

  serverMode = await detectServer();
  $("#versionLine").textContent = `Kitchen Coach v${VERSION} · ${serverMode ? "Windows desktop (local recipe engine)" : "Offline app - recipes are read on this device"}`;
  if (serverMode) {
    window.addEventListener("pagehide", () => navigator.sendBeacon && navigator.sendBeacon("api/bye"));
  } else if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch((err) => console.warn("Offline mode unavailable", err));
  }

  renderLibrary();
  checkSession();
  showView("home");
  startTicker();
  document.documentElement.dataset.ready = "1";
}

init();
