import sqlite3
import json
from datetime import datetime

DB_PATH = "accidents.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            severity TEXT,
            confidence REAL,
            location TEXT,
            frame_path TEXT,
            alerts_sent TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_accident(severity: str, confidence: float, location: str, frame_path: str, alerts_sent: list):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO accidents (timestamp, severity, confidence, location, frame_path, alerts_sent) VALUES (?,?,?,?,?,?)",
        (datetime.utcnow().isoformat(), severity, confidence, location, frame_path, json.dumps(alerts_sent))
    )
    conn.commit()
    conn.close()

def get_accidents(limit: int = 50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM accidents ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
