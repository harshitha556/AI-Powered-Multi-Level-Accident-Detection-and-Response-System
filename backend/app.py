import asyncio
import base64
import cv2
import json
import numpy as np
import os
import time
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from detector import detect_frame, frame_history
from alerts import send_alerts
from database import init_db, log_accident, get_accidents

load_dotenv()
init_db()

app = FastAPI(title="Accident Detection API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SNAPSHOTS_DIR = Path("snapshots")
SNAPSHOTS_DIR.mkdir(exist_ok=True)

# Cooldown: don't re-alert for same accident within N seconds
ALERT_COOLDOWN = 30
_last_alert_time: float = 0


def _maybe_alert(accident: dict, frame: np.ndarray) -> list[str]:
    global _last_alert_time
    now = time.time()
    if now - _last_alert_time < ALERT_COOLDOWN:
        return []
    _last_alert_time = now

    # Save snapshot
    snap_path = SNAPSHOTS_DIR / f"accident_{int(now)}.jpg"
    cv2.imwrite(str(snap_path), frame)
    _, buf = cv2.imencode(".jpg", frame)
    image_bytes = buf.tobytes()

    sent = send_alerts(accident["severity"], accident["confidence"], image_bytes)
    log_accident(
        severity=accident["severity"],
        confidence=accident["confidence"],
        location=os.getenv("LOCATION", "Unknown"),
        frame_path=str(snap_path),
        alerts_sent=sent,
    )
    return sent


@app.post("/api/detect")
async def detect_video(file: UploadFile = File(...)):
    """Process an uploaded video file frame by frame, return single worst accident."""
    contents = await file.read()
    tmp_path = f"tmp_{file.filename}"
    with open(tmp_path, "wb") as f:
        f.write(contents)

    cap = cv2.VideoCapture(tmp_path)
    frame_count = 0
    best_accident = None
    best_frame = None
    severity_rank = {"minor": 1, "major": 2, "critical": 3}

    # Reset frame history for new video
    frame_history.clear()

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_count += 1
        if frame_count % 3 != 0:
            continue

        result = detect_frame(frame)
        if result["accident"]:
            acc = result["accident"]
            # Keep only the worst accident detected across all frames
            if best_accident is None or \
               severity_rank.get(acc["severity"], 0) > severity_rank.get(best_accident["severity"], 0) or \
               (acc["severity"] == best_accident["severity"] and acc["confidence"] > best_accident["confidence"]):
                best_accident = acc
                best_frame = frame

    cap.release()
    os.remove(tmp_path)

    accidents = []
    if best_accident:
        sent = _maybe_alert(best_accident, best_frame)
        best_accident["alerts_sent"] = sent
        accidents.append(best_accident)

    return JSONResponse({"total_frames": frame_count, "accidents": accidents})


@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    """
    WebSocket endpoint for live video streaming.
    Client sends base64-encoded JPEG frames; server responds with
    annotated frame + accident info.
    """
    await websocket.accept()
    frame_history.clear()
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            img_b64 = msg.get("frame", "")
            if not img_b64:
                continue

            img_bytes = base64.b64decode(img_b64)
            np_arr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            result = detect_frame(frame)
            _, buf = cv2.imencode(".jpg", result["annotated_frame"], [cv2.IMWRITE_JPEG_QUALITY, 70])
            annotated_b64 = base64.b64encode(buf).decode()

            accident_info = None
            if result["accident"]:
                acc = result["accident"]
                sent = _maybe_alert(acc, result["annotated_frame"])
                accident_info = {**acc, "alerts_sent": sent}

            await websocket.send_text(json.dumps({
                "frame": annotated_b64,
                "vehicles": len(result["vehicles"]),
                "accident": accident_info,
            }))
    except WebSocketDisconnect:
        pass


@app.get("/api/history")
def get_history(limit: int = 50):
    return get_accidents(limit)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve frontend static files
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
