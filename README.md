# AI-Powered Multi-Level Accident Detection and Response System

## Setup

### 1. Configure environment
```bash
cp .env.example backend/.env
# Edit backend/.env with your Twilio, SMTP, and recipient details
```

### 2. Install & run backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Open the app
Visit `http://localhost:8000` in your browser.

---

## How it works

| Component | Detail |
|-----------|--------|
| Detection | YOLOv8n (auto-downloaded on first run) detects vehicles in each frame |
| Temporal analysis | Tracks bounding box overlap across a 10-frame sliding window |
| Severity | Hybrid score: IOU magnitude (60%) + overlap duration (40%) → minor / major / critical |
| Alerts | Ambulance always notified; owner notified for major+; emergency contact for critical only |
| Database | SQLite `accidents.db` auto-created in `backend/` |

## Alert levels

| Severity | Ambulance | Vehicle Owner | Emergency Contact |
|----------|-----------|---------------|-------------------|
| Minor    | ✅ SMS + Email | ❌ | ❌ |
| Major    | ✅ SMS + Email | ✅ SMS + Email | ❌ |
| Critical | ✅ SMS + Email | ✅ SMS + Email | ✅ SMS + Email |

## Swap YOLO model
Set `YOLO_MODEL=yolov8m.pt` in `.env` for better accuracy (slower).

## Notes
- Twilio and SMTP credentials are required for alerts; without them alerts are skipped (logged only).
- For production, replace the static `LOCATION` env var with GPS data from the client.
