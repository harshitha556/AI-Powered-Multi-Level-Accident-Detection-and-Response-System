import cv2
import numpy as np
from collections import deque
from ultralytics import YOLO
import os

# Load YOLOv8 model (nano for speed; swap to yolov8m.pt for accuracy)
MODEL_PATH = os.environ.get("YOLO_MODEL", "yolov8n.pt")
model = YOLO(MODEL_PATH)

# Vehicle class IDs in COCO dataset
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

# Temporal buffer: stores bounding boxes per tracked object over N frames
FRAME_BUFFER_SIZE = 15
frame_history: deque = deque(maxlen=FRAME_BUFFER_SIZE)

# Proximity/IOU threshold to trigger collision detection
COLLISION_IOU_THRESHOLD = 0.15
# Minimum frames with overlap to confirm accident
COLLISION_FRAME_THRESHOLD = 4

# Track previous box positions to detect if vehicles stopped moving
prev_boxes: list = []


def compute_iou(boxA, boxB):
    """Compute Intersection over Union for two [x1,y1,x2,y2] boxes."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    inter = max(0, xB - xA) * max(0, yB - yA)
    if inter == 0:
        return 0.0
    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    return inter / float(areaA + areaB - inter)


def compute_proximity(boxA, boxB) -> float:
    """
    Compute proximity score between two boxes using centroid distance
    normalized by average vehicle size.
    Returns 0.0 (far apart) to 1.0 (centers touching).
    """
    cxA = (boxA[0] + boxA[2]) / 2
    cyA = (boxA[1] + boxA[3]) / 2
    cxB = (boxB[0] + boxB[2]) / 2
    cyB = (boxB[1] + boxB[3]) / 2

    dist = ((cxA - cxB) ** 2 + (cyA - cyB) ** 2) ** 0.5

    # Average half-diagonal of both boxes as reference size
    diagA = ((boxA[2]-boxA[0])**2 + (boxA[3]-boxA[1])**2)**0.5 / 2
    diagB = ((boxB[2]-boxB[0])**2 + (boxB[3]-boxB[1])**2)**0.5 / 2
    ref = (diagA + diagB) / 2

    if ref == 0:
        return 0.0

    # Proximity: 1.0 when centers are touching, 0.0 when far away
    proximity = max(0.0, 1.0 - (dist / (ref * 2.5)))
    return round(proximity, 3)


def box_center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def vehicles_stopped(current_boxes: list, history: deque, check_frames: int = 6) -> bool:
    """
    Returns True if the colliding vehicles have barely moved
    over the last `check_frames` frames — i.e. they are stuck/immobile.
    """
    if len(history) < check_frames:
        return False

    recent = list(history)[-check_frames:]
    # For each vehicle in current frame, check if its center barely moved
    stopped_count = 0
    for cur_box in current_boxes:
        cx, cy = box_center(cur_box)
        movements = []
        for past_frame_boxes in recent:
            for past_box in past_frame_boxes:
                px, py = box_center(past_box)
                dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                movements.append(dist)
        if movements and min(movements) < 8:  # less than 8px movement = stopped
            stopped_count += 1

    return stopped_count >= 2  # both vehicles stopped


def classify_severity(iou: float, overlap_frames: int, vehicles_are_stopped: bool = False) -> tuple[str, float]:
    """
    MINOR    — light touch, vehicles keep moving, brief overlap
    MAJOR    — real collision, significant overlap, vehicles slow down
    CRITICAL — full crash, vehicles fully overlapped AND stopped moving
    """
    duration = min(overlap_frames, FRAME_BUFFER_SIZE) / FRAME_BUFFER_SIZE
    score = round((iou * 0.6) + (duration * 0.4), 2)

    # Critical ONLY if vehicles are actually stopped after impact
    if vehicles_are_stopped and iou >= 0.20 and duration >= 0.4:
        return "critical", score
    elif iou >= 0.15 and duration >= 0.3:
        return "major", score
    else:
        return "minor", score


def detect_frame(frame: np.ndarray) -> dict:
    """
    Run YOLO detection on a single frame.
    Returns dict with:
      - annotated_frame: frame with bounding boxes drawn
      - vehicles: list of detected vehicle boxes
      - accident: dict or None if accident detected
    """
    results = model(frame, verbose=False)[0]
    vehicles = []

    for box in results.boxes:
        cls_id = int(box.cls[0])
        if cls_id not in VEHICLE_CLASSES:
            continue
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        conf = float(box.conf[0])
        label = VEHICLE_CLASSES[cls_id]
        vehicles.append({"box": [x1, y1, x2, y2], "label": label, "conf": conf})

    # Push current vehicle boxes to temporal buffer
    frame_history.append([v["box"] for v in vehicles])

    # Temporal collision analysis
    accident = _analyze_collision(vehicles)

    # Draw annotations
    annotated = _draw_annotations(frame.copy(), vehicles, accident)

    return {"annotated_frame": annotated, "vehicles": vehicles, "accident": accident}


def _analyze_collision(vehicles: list) -> dict | None:
    """Check if any two vehicles have actual box overlap across recent frames."""
    if len(vehicles) < 2:
        return None

    best_iou = 0.0
    best_pair = None

    for i in range(len(vehicles)):
        for j in range(i + 1, len(vehicles)):
            iou = compute_iou(vehicles[i]["box"], vehicles[j]["box"])
            if iou > best_iou:
                best_iou = iou
                best_pair = (i, j)

    if best_iou < COLLISION_IOU_THRESHOLD:
        return None

    # Count frames with actual box overlap
    overlap_count = 0
    for past_boxes in frame_history:
        if len(past_boxes) >= 2:
            for a in range(len(past_boxes)):
                for b in range(a + 1, len(past_boxes)):
                    if compute_iou(past_boxes[a], past_boxes[b]) >= COLLISION_IOU_THRESHOLD:
                        overlap_count += 1
                        break

    if overlap_count < COLLISION_FRAME_THRESHOLD:
        return None

    # Check if colliding vehicles have stopped moving
    colliding = [vehicles[best_pair[0]], vehicles[best_pair[1]]]
    stopped = vehicles_stopped([v["box"] for v in colliding], frame_history)

    severity, confidence = classify_severity(best_iou, overlap_count, stopped)
    return {
        "severity": severity,
        "confidence": confidence,
        "iou": round(best_iou, 3),
        "overlap_frames": overlap_count,
        "stopped": stopped,
        "pair": best_pair,
    }


def _draw_annotations(frame: np.ndarray, vehicles: list, accident: dict | None) -> np.ndarray:
    COLORS = {"car": (0, 255, 0), "truck": (255, 165, 0), "bus": (0, 165, 255), "motorcycle": (255, 0, 255)}
    SEVERITY_COLORS = {"minor": (0, 255, 255), "major": (0, 165, 255), "critical": (0, 0, 255)}

    for i, v in enumerate(vehicles):
        x1, y1, x2, y2 = v["box"]
        color = COLORS.get(v["label"], (200, 200, 200))
        # Highlight colliding pair
        if accident and i in accident["pair"]:
            color = SEVERITY_COLORS.get(accident["severity"], (0, 0, 255))
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
        else:
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, f"{v['label']} {v['conf']:.2f}", (x1, y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    if accident:
        label = f"ACCIDENT: {accident['severity'].upper()} ({accident['confidence']})"
        cv2.putText(frame, label, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                    SEVERITY_COLORS[accident["severity"]], 3)

    return frame
