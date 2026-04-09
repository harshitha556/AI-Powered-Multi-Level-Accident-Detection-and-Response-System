const API_BASE = window.location.origin;
const WS_BASE  = API_BASE.replace(/^http/, "ws");

// DOM refs
const videoInput   = document.getElementById("video-input");
const uploadVideo  = document.getElementById("upload-video");
const annotatedImg = document.getElementById("annotated-img");
const liveCanvas   = document.getElementById("live-canvas");
const webcamVideo  = document.getElementById("webcam-video");
const placeholder  = document.getElementById("placeholder");
const analyzeBtn   = document.getElementById("analyze-btn");
const liveBtn      = document.getElementById("live-btn");
const stopBtn      = document.getElementById("stop-btn");
const modeLabel    = document.getElementById("mode-label");
const overlay      = document.getElementById("processing-overlay");
const procLabel    = document.getElementById("processing-label");
const alertFeed    = document.getElementById("alert-feed");
const alertCount   = document.getElementById("alert-count");
const historyBody  = document.getElementById("history-body");

// Stats
const statTotal    = document.getElementById("stat-total");
const statMajor    = document.getElementById("stat-major");
const statCritical = document.getElementById("stat-critical");

let ws = null;
let webcamStream = null;
let liveInterval = null;
let sessionStats  = { total: 0, major: 0, critical: 0 };
let alertItems    = [];

// ── Health check ──────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const r = await fetch(`${API_BASE}/api/health`);
    if (r.ok) {
      setDot("api-dot", "green");
      document.getElementById("api-status").textContent = "API: Connected";
    }
  } catch {
    setDot("api-dot", "red");
    document.getElementById("api-status").textContent = "API: Unreachable";
  }
}

function setDot(id, color) {
  const el = document.getElementById(id);
  el.className = `dot dot-${color}`;
}

// ── File upload ───────────────────────────────────────────────────────────────
videoInput.addEventListener("change", () => {
  const file = videoInput.files[0];
  if (!file) return;
  const url = URL.createObjectURL(file);
  uploadVideo.src = url;
  uploadVideo.style.display = "block";
  placeholder.style.display = "none";
  annotatedImg.style.display = "none";
  analyzeBtn.disabled = false;
  modeLabel.textContent = `— ${file.name}`;
});

analyzeBtn.addEventListener("click", async () => {
  const file = videoInput.files[0];
  if (!file) return;

  setMode("analyzing");
  overlay.classList.add("active");
  procLabel.textContent = "Uploading & analyzing video...";
  analyzeBtn.disabled = true;

  const form = new FormData();
  form.append("file", file);

  try {
    const r = await fetch(`${API_BASE}/api/detect`, { method: "POST", body: form });
    const data = await r.json();
    overlay.classList.remove("active");
    setMode("done");
    data.accidents.forEach(acc => addAlert(acc));
    modeLabel.textContent = `— Done (${data.total_frames} frames, ${data.accidents.length} events)`;
  } catch (e) {
    overlay.classList.remove("active");
    addAlert({ severity: "error", confidence: 0, alerts_sent: [], error: e.message });
  }
  analyzeBtn.disabled = false;
});

// ── Live stream ───────────────────────────────────────────────────────────────
liveBtn.addEventListener("click", async () => {
  try {
    webcamStream = await navigator.mediaDevices.getUserMedia({ video: true });
    webcamVideo.srcObject = webcamStream;
    await webcamVideo.play();

    liveCanvas.width  = webcamVideo.videoWidth  || 640;
    liveCanvas.height = webcamVideo.videoHeight || 480;
    liveCanvas.style.display = "block";
    placeholder.style.display = "none";
    uploadVideo.style.display = "none";

    ws = new WebSocket(`${WS_BASE}/ws/stream`);
    ws.onopen = () => {
      setDot("stream-dot", "green");
      document.getElementById("stream-status").textContent = "Stream: Live";
      setDot("detect-dot", "yellow");
      document.getElementById("detect-status").textContent = "Detection: Running";
      startCapture();
    };
    ws.onmessage = handleWsMessage;
    ws.onclose = stopLive;

    liveBtn.disabled = true;
    stopBtn.disabled = false;
    setMode("live");
  } catch (e) {
    alert("Camera access denied or unavailable: " + e.message);
  }
});

stopBtn.addEventListener("click", stopLive);

function startCapture() {
  const ctx = liveCanvas.getContext("2d");
  liveInterval = setInterval(() => {
    if (!webcamVideo.videoWidth) return;
    liveCanvas.width  = webcamVideo.videoWidth;
    liveCanvas.height = webcamVideo.videoHeight;
    ctx.drawImage(webcamVideo, 0, 0);
    liveCanvas.toBlob(blob => {
      if (!blob || !ws || ws.readyState !== WebSocket.OPEN) return;
      const reader = new FileReader();
      reader.onload = () => {
        const b64 = reader.result.split(",")[1];
        ws.send(JSON.stringify({ frame: b64 }));
      };
      reader.readAsDataURL(blob);
    }, "image/jpeg", 0.7);
  }, 200); // ~5fps to server
}

function handleWsMessage(event) {
  const data = JSON.parse(event.data);
  // Draw annotated frame
  const img = new Image();
  img.onload = () => {
    const ctx = liveCanvas.getContext("2d");
    ctx.drawImage(img, 0, 0, liveCanvas.width, liveCanvas.height);
  };
  img.src = "data:image/jpeg;base64," + data.frame;

  if (data.accident) {
    addAlert(data.accident);
    flashOverlay(data.accident.severity);
  }
}

function stopLive() {
  clearInterval(liveInterval);
  if (ws) { ws.close(); ws = null; }
  if (webcamStream) { webcamStream.getTracks().forEach(t => t.stop()); webcamStream = null; }
  liveBtn.disabled = false;
  stopBtn.disabled = true;
  setDot("stream-dot", "gray");
  document.getElementById("stream-status").textContent = "Stream: Idle";
  setDot("detect-dot", "gray");
  document.getElementById("detect-status").textContent = "Detection: Standby";
  setMode("idle");
}

// ── Alert feed ────────────────────────────────────────────────────────────────
function addAlert(acc) {
  if (acc.severity === "error") {
    console.error("Detection error:", acc.error);
    return;
  }

  sessionStats.total++;
  if (acc.severity === "major")    sessionStats.major++;
  if (acc.severity === "critical") sessionStats.critical++;
  updateStats();

  const time = new Date().toLocaleTimeString();
  const item = document.createElement("div");
  item.className = "alert-item";
  item.innerHTML = `
    <span class="severity-badge sev-${acc.severity}">${acc.severity}</span>
    <div>
      <div>Confidence: ${(acc.confidence * 100).toFixed(0)}% | IOU: ${acc.iou ?? "—"}</div>
      <div class="alert-meta">${time} · Alerts: ${(acc.alerts_sent || []).join(", ") || "none"}</div>
    </div>
  `;

  if (alertFeed.querySelector("div[style]")) alertFeed.innerHTML = "";
  alertFeed.prepend(item);
  alertItems.push(item);
  alertCount.textContent = `${alertItems.length} alert${alertItems.length !== 1 ? "s" : ""}`;
}

function flashOverlay(severity) {
  const colors = { minor: "#1f6feb", major: "#d29922", critical: "#f85149" };
  const color = colors[severity] || "#f85149";
  const flash = document.createElement("div");
  flash.style.cssText = `position:fixed;inset:0;background:${color}22;pointer-events:none;z-index:999;animation:fadeFlash 0.6s ease forwards`;
  document.body.appendChild(flash);
  setTimeout(() => flash.remove(), 700);
}

// ── Stats ─────────────────────────────────────────────────────────────────────
function updateStats() {
  statTotal.textContent    = sessionStats.total;
  statMajor.textContent    = sessionStats.major;
  statCritical.textContent = sessionStats.critical;
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
  try {
    const r = await fetch(`${API_BASE}/api/history`);
    const rows = await r.json();
    if (!rows.length) return;
    historyBody.innerHTML = rows.map(row => `
      <tr>
        <td>${new Date(row.timestamp).toLocaleString()}</td>
        <td><span class="severity-badge sev-${row.severity}">${row.severity}</span></td>
        <td>${(row.confidence * 100).toFixed(0)}%</td>
        <td>${row.location}</td>
        <td>${JSON.parse(row.alerts_sent || "[]").length} sent</td>
      </tr>
    `).join("");
  } catch (e) {
    console.warn("History load failed:", e);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setMode(mode) {
  const labels = { idle: "— Idle", live: "— Live", analyzing: "— Analyzing...", done: "— Complete" };
  modeLabel.textContent = labels[mode] || mode;
  modeLabel.style.color = mode === "live" ? "#f85149" : mode === "done" ? "#3fb950" : "#8b949e";
}

// Flash animation
const style = document.createElement("style");
style.textContent = `@keyframes fadeFlash { from { opacity:1 } to { opacity:0 } }`;
document.head.appendChild(style);

// Init
checkHealth();
loadHistory();
setInterval(loadHistory, 30000);
