"""
services/camera_service.py

Addaptation of file camera_service.py from real robot SHARA
Lightweight face recognition service for SHARA_DT.

Design goals:
- Keep the same API contract used by the previous batch recognition flow.
- Avoid heavy native dependencies that are difficult to build on Render.
- Preserve the robot-like decision semantics (window consensus + user memory).
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

logger = logging.getLogger("FaceRecognition")


# Keep parity with previous batch logic
EUCLIDEAN_DISTANCE_THRESHOLD = 0.45
MAX_DESCRIPTOR_HISTORY = 5
CONFIRMATION_WINDOW_SIZE = 5
MIN_CONSENSUS_THRESHOLD = 0.6  # 3/5


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DB_FILE = os.path.join(BASE_DIR, "files", "face_database.json")


_db_lock = threading.Lock()
_face_db: Dict = {"nextId": 1, "users": []}


def _ensure_db_loaded():
    with _db_lock:
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    _face_db["nextId"] = int(loaded.get("nextId", 1))
                    _face_db["users"] = loaded.get("users", []) or []
                    return
            except Exception as e:
                logger.warning(f"Could not load face DB, starting fresh: {e}")

        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        _save_db_locked()


def _save_db_locked():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(_face_db, f, ensure_ascii=False, indent=2)


def _normalize_descriptor(descriptor: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(descriptor)
    if norm == 0:
        return descriptor
    return descriptor / norm


def _extract_descriptor(image_bytes: bytes) -> Optional[List[float]]:
    """
    Converts an image into a stable 128-d descriptor.
    Descriptor shape is kept compatible with previous face DB format.
    """
    if not image_bytes:
        return None

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")

        # Center-crop to square to reduce framing variance
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))

        # 16 x 8 = 128 dimensions
        img = img.resize((16, 8), Image.Resampling.BILINEAR)
        arr = np.asarray(img, dtype=np.float32).flatten() / 255.0
        arr = _normalize_descriptor(arr)
        return arr.astype(np.float32).tolist()
    except Exception as e:
        logger.warning(f"Descriptor extraction failed: {e}")
        return None


def _is_valid_descriptor(descriptor) -> bool:
    if not isinstance(descriptor, list):
        return False
    if len(descriptor) != 128:
        return False
    for value in descriptor:
        if not isinstance(value, (int, float)):
            return False
    return True


def _euclidean_distance(a: List[float], b: List[float]) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    if va.shape != vb.shape:
        return float("inf")
    return float(np.linalg.norm(va - vb))


def _average_descriptors(descriptors: List[List[float]]) -> List[float]:
    mat = np.asarray(descriptors, dtype=np.float32)
    avg = np.mean(mat, axis=0)
    avg = _normalize_descriptor(avg)
    return avg.astype(np.float32).tolist()


def _find_user_by_id(user_id: str) -> Optional[Dict]:
    for user in _face_db["users"]:
        if user.get("userId") == user_id:
            return user
    return None


def _find_best_match_for_descriptor(descriptor: List[float], known_user_id: Optional[str] = None) -> Dict:
    # Fast path: previously known user
    if known_user_id and known_user_id != "unknown":
        known = _find_user_by_id(known_user_id)
        if known and known.get("descriptor"):
            distance = _euclidean_distance(descriptor, known["descriptor"])
            if distance < EUCLIDEAN_DISTANCE_THRESHOLD:
                return {
                    "userId": known_user_id,
                    "userName": known.get("userName") or "unknown",
                    "distance": distance,
                    "confidence": max(0.0, 1.0 - min(distance, 1.0)),
                    "needsIdentification": not bool(known.get("userName")),
                    "totalVisits": known.get("metadata", {}).get("visits", 0),
                }

    best = None
    best_distance = float("inf")

    for user in _face_db["users"]:
        user_desc = user.get("descriptor")
        if not isinstance(user_desc, list) or len(user_desc) != 128:
            continue

        distance = _euclidean_distance(descriptor, user_desc)
        if distance < EUCLIDEAN_DISTANCE_THRESHOLD and distance < best_distance:
            best = user
            best_distance = distance

    if best:
        return {
            "userId": best.get("userId"),
            "userName": best.get("userName") or "unknown",
            "distance": best_distance,
            "confidence": max(0.0, 1.0 - min(best_distance, 1.0)),
            "needsIdentification": not bool(best.get("userName")),
            "totalVisits": best.get("metadata", {}).get("visits", 0),
        }

    return {
        "userId": "unknown",
        "userName": "unknown",
        "distance": None,
        "confidence": 0.0,
        "needsIdentification": True,
    }


def _analyze_descriptor_batch(descriptors: List[List[float]], known_user_id: Optional[str]) -> Dict:
    detections = []
    votes: Dict[str, Dict] = {}

    for descriptor in descriptors:
        result = _find_best_match_for_descriptor(descriptor, known_user_id)
        detections.append({"descriptor": descriptor, "result": result})

        user_id = result["userId"]
        if user_id not in votes:
            votes[user_id] = {"count": 0, "detections": []}
        votes[user_id]["count"] += 1
        votes[user_id]["detections"].append({"descriptor": descriptor, "result": result})

    winner_user_id = max(votes.keys(), key=lambda uid: votes[uid]["count"])
    winner_count = votes[winner_user_id]["count"]
    consensus_ratio = winner_count / max(1, len(descriptors))

    if consensus_ratio < MIN_CONSENSUS_THRESHOLD:
        return {
            "isUncertain": True,
            "consensusRatio": consensus_ratio,
            "userId": "uncertain",
            "userName": "unknown",
            "needsIdentification": True,
        }

    winner_detections = votes[winner_user_id]["detections"]
    winner_result = winner_detections[0]["result"]
    winner_descriptors = [d["descriptor"] for d in winner_detections]

    avg_distance_values = [
        d["result"]["distance"] for d in winner_detections if d["result"]["distance"] is not None
    ]
    avg_distance = (
        sum(avg_distance_values) / len(avg_distance_values) if avg_distance_values else None
    )

    return {
        "isConfirmed": True,
        "consensusRatio": consensus_ratio,
        "userId": winner_user_id,
        "userName": winner_result.get("userName", "unknown"),
        "needsIdentification": winner_result.get("needsIdentification", True),
        "distance": avg_distance,
        "confidence": winner_result.get("confidence", 0.0),
        "isNewUser": winner_user_id == "unknown",
        "descriptorsForUpdate": winner_descriptors,
        "totalVisits": winner_result.get("totalVisits"),
    }


def _confirm_user_identity_with_descriptors(user_id: str, descriptors: List[List[float]], result_data: Dict) -> Dict:
    valid = [d for d in descriptors if isinstance(d, list) and len(d) == 128]
    if not valid:
        return {"error": "No valid descriptors provided."}

    if user_id == "unknown":
        new_user_id = f"user{_face_db['nextId']}"
        _face_db["nextId"] += 1

        new_user = {
            "userId": new_user_id,
            "userName": None,
            "descriptor": _average_descriptors(valid),
            "descriptorHistory": valid[-MAX_DESCRIPTOR_HISTORY:],
            "metadata": {
                "createdAt": datetime.utcnow().isoformat(),
                "lastSeen": datetime.utcnow().isoformat(),
                "visits": 1,
                "isTemporary": False,
            },
        }
        _face_db["users"].append(new_user)
        _save_db_locked()

        return {
            "userId": new_user_id,
            "userName": "unknown",
            "isNewUser": True,
            "needsIdentification": True,
            "distance": result_data.get("distance"),
            "confidence": result_data.get("confidence"),
        }

    user = _find_user_by_id(user_id)
    if not user:
        return {"error": "User not found in database."}

    history = user.get("descriptorHistory") or []
    history.extend(valid)
    user["descriptorHistory"] = history[-MAX_DESCRIPTOR_HISTORY:]
    user["descriptor"] = _average_descriptors(user["descriptorHistory"])

    metadata = user.setdefault("metadata", {})
    metadata["lastSeen"] = datetime.utcnow().isoformat()
    metadata["visits"] = int(metadata.get("visits", 0)) + 1

    _save_db_locked()

    return {
        "userId": user_id,
        "userName": user.get("userName") or "unknown",
        "isNewUser": False,
        "needsIdentification": not bool(user.get("userName")),
        "distance": result_data.get("distance"),
        "confidence": result_data.get("confidence"),
        "totalVisits": metadata.get("visits"),
    }


def update_user_name(user_id: str, user_name: str) -> Dict:
    """Allows state machine/tool layer to set username for a known userId."""
    with _db_lock:
        user = _find_user_by_id(user_id)
        if not user:
            return {"success": False, "error": "User not found."}

        user["userName"] = user_name.strip() if user_name else None
        metadata = user.setdefault("metadata", {})
        metadata["identifiedAt"] = datetime.utcnow().isoformat()
        _save_db_locked()

    return {"success": True, "userId": user_id, "userName": user.get("userName")}


def recognize_face_with_batch(
    face_buffers: List[bytes],
    session_id: str,
    known_user_id: Optional[str] = None,
    descriptors: Optional[List[List[float]]] = None,
) -> Dict:
    """
    Main batch recognition entrypoint.
    Returns a payload compatible with existing frontend handling.
    """
    if not session_id:
        return {"error": "Session ID is required."}
    if not face_buffers:
        return {"error": "No images provided."}

    _ensure_db_loaded()

    batch_descriptors: List[List[float]] = []

    # Preferred path for fidelity: descriptors extracted in frontend (face-api.js 128D)
    if descriptors:
        for descriptor in descriptors[:CONFIRMATION_WINDOW_SIZE]:
            if _is_valid_descriptor(descriptor):
                normalized = _normalize_descriptor(np.asarray(descriptor, dtype=np.float32)).tolist()
                batch_descriptors.append(normalized)

    # Fallback path: backend lightweight descriptor extraction from image bytes
    if not batch_descriptors:
        for image_bytes in face_buffers[:CONFIRMATION_WINDOW_SIZE]:
            descriptor = _extract_descriptor(image_bytes)
            if descriptor is not None:
                batch_descriptors.append(descriptor)

    if not batch_descriptors:
        return {"error": "No valid face descriptors extracted."}

    with _db_lock:
        result = _analyze_descriptor_batch(batch_descriptors, known_user_id)

        if result.get("isUncertain"):
            return {
                **result,
                "detectionProgress": len(batch_descriptors),
                "totalRequired": CONFIRMATION_WINDOW_SIZE,
            }

        if result.get("isConfirmed"):
            confirmed = _confirm_user_identity_with_descriptors(
                result["userId"],
                result.get("descriptorsForUpdate", []),
                result,
            )
            if confirmed.get("error"):
                return confirmed

            return {
                **confirmed,
                "isConfirmed": True,
                "consensusRatio": result.get("consensusRatio", 0.0),
                "detectionProgress": len(batch_descriptors),
                "totalRequired": CONFIRMATION_WINDOW_SIZE,
            }

    return {"error": "Unexpected recognition state."}
