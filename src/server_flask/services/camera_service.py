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

try:
    import face_recognition
except ImportError:  # pragma: no cover - optional dependency in current deployment
    face_recognition = None

logger = logging.getLogger("FaceRecognition")


# Keep parity with previous batch logic
LIGHTWEIGHT_DISTANCE_THRESHOLD = 0.45
FACE_RECOGNITION_DISTANCE_THRESHOLD = 0.55
MAX_DESCRIPTOR_HISTORY = 5
CONFIRMATION_WINDOW_SIZE = 5
KNOWN_RECOGNITION_THRESHOLD = 3
UNKNOWN_RECOGNITION_THRESHOLD = 8
RECOGNITION_SESSION_TTL_SECONDS = 20

DESCRIPTOR_MODEL_LIGHTWEIGHT = "lightweight_v1"
DESCRIPTOR_MODEL_FACE_RECOGNITION = "face_recognition_v1"


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DB_FILE = os.path.join(BASE_DIR, "files", "face_database.json")


_db_lock = threading.Lock()
_face_db: Dict = {"nextId": 1, "users": []}
_recognition_sessions: Dict[str, Dict] = {}


def _resolve_active_descriptor_model() -> str:
    requested_backend = os.getenv("FACE_DESCRIPTOR_BACKEND", "lightweight").strip().lower()

    if requested_backend == "face_recognition":
        if face_recognition is None:
            logger.warning(
                "FACE_DESCRIPTOR_BACKEND=face_recognition requested but face_recognition is not installed. "
                "Falling back to lightweight descriptors."
            )
            return DESCRIPTOR_MODEL_LIGHTWEIGHT
        return DESCRIPTOR_MODEL_FACE_RECOGNITION

    if requested_backend not in ("", "lightweight"):
        logger.warning(
            "Unknown FACE_DESCRIPTOR_BACKEND=%s. Falling back to lightweight descriptors.",
            requested_backend,
        )

    return DESCRIPTOR_MODEL_LIGHTWEIGHT


ACTIVE_DESCRIPTOR_MODEL = _resolve_active_descriptor_model()


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


def _get_user_descriptor_model(user: Dict) -> str:
    model = user.get("descriptorModel")
    if isinstance(model, str) and model.strip():
        return model
    return DESCRIPTOR_MODEL_LIGHTWEIGHT


def _is_descriptor_model_compatible(user: Dict) -> bool:
    return _get_user_descriptor_model(user) == ACTIVE_DESCRIPTOR_MODEL


def _descriptor_distance_threshold(descriptor_model: Optional[str] = None) -> float:
    model = descriptor_model or ACTIVE_DESCRIPTOR_MODEL
    if model == DESCRIPTOR_MODEL_FACE_RECOGNITION:
        return FACE_RECOGNITION_DISTANCE_THRESHOLD
    return LIGHTWEIGHT_DISTANCE_THRESHOLD


def _prepare_descriptor(descriptor, descriptor_model: Optional[str] = None) -> List[float]:
    model = descriptor_model or ACTIVE_DESCRIPTOR_MODEL
    arr = np.asarray(descriptor, dtype=np.float32)
    if model == DESCRIPTOR_MODEL_LIGHTWEIGHT:
        arr = _normalize_descriptor(arr)
    return arr.astype(np.float32).tolist()


def _extract_lightweight_descriptor(image_bytes: bytes) -> Optional[List[float]]:
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
        return _prepare_descriptor(arr, DESCRIPTOR_MODEL_LIGHTWEIGHT)
    except Exception as e:
        logger.warning(f"Descriptor extraction failed: {e}")
        return None


def _extract_face_recognition_descriptor(image_bytes: bytes) -> Optional[List[float]]:
    if not image_bytes or face_recognition is None:
        return None

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.asarray(img, dtype=np.uint8)

        encodings = face_recognition.face_encodings(arr)
        if not encodings:
            h, w = arr.shape[:2]
            fallback_box = [(0, max(w - 1, 0), max(h - 1, 0), 0)]
            encodings = face_recognition.face_encodings(arr, known_face_locations=fallback_box)

        if not encodings:
            return None

        return _prepare_descriptor(encodings[0], DESCRIPTOR_MODEL_FACE_RECOGNITION)
    except Exception as e:
        logger.warning(f"face_recognition descriptor extraction failed: {e}")
        return None


def _extract_backend_descriptor(image_bytes: bytes) -> Optional[List[float]]:
    if ACTIVE_DESCRIPTOR_MODEL == DESCRIPTOR_MODEL_FACE_RECOGNITION:
        descriptor = _extract_face_recognition_descriptor(image_bytes)
        if descriptor is not None:
            return descriptor

        logger.warning(
            "face_recognition backend could not extract a descriptor for one frame. "
            "Falling back to lightweight descriptor extraction for availability."
        )

    return _extract_lightweight_descriptor(image_bytes)


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


def _average_descriptors(descriptors: List[List[float]], descriptor_model: Optional[str] = None) -> List[float]:
    mat = np.asarray(descriptors, dtype=np.float32)
    avg = np.mean(mat, axis=0)
    return _prepare_descriptor(avg, descriptor_model)


def _cleanup_expired_sessions_locked(now: Optional[datetime] = None):
    now = now or datetime.utcnow()
    expired_ids = []

    for session_id, session_data in _recognition_sessions.items():
        last_seen = session_data.get("lastSeenAt")
        if not isinstance(last_seen, datetime):
            expired_ids.append(session_id)
            continue

        elapsed = (now - last_seen).total_seconds()
        if elapsed > RECOGNITION_SESSION_TTL_SECONDS:
            expired_ids.append(session_id)

    for session_id in expired_ids:
        _recognition_sessions.pop(session_id, None)


def _get_session_state_locked(session_id: str) -> Dict:
    now = datetime.utcnow()
    _cleanup_expired_sessions_locked(now)

    session_state = _recognition_sessions.setdefault(
        session_id,
        {
            "history": {},
            "descriptors": {},
            "lastSeenAt": now,
        },
    )
    session_state["lastSeenAt"] = now
    session_state.setdefault("history", {})
    session_state.setdefault("descriptors", {})
    return session_state


def _find_user_by_id(user_id: str) -> Optional[Dict]:
    for user in _face_db["users"]:
        if user.get("userId") == user_id:
            return user
    return None


def _find_best_match_for_descriptor(descriptor: List[float], known_user_id: Optional[str] = None) -> Dict:
    threshold = _descriptor_distance_threshold()

    # Fast path: previously known user
    if known_user_id and known_user_id != "unknown":
        known = _find_user_by_id(known_user_id)
        if known and known.get("descriptor") and _is_descriptor_model_compatible(known):
            distance = _euclidean_distance(descriptor, known["descriptor"])
            if distance < threshold:
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
        if not _is_descriptor_model_compatible(user):
            continue

        user_desc = user.get("descriptor")
        if not isinstance(user_desc, list) or len(user_desc) != 128:
            continue

        distance = _euclidean_distance(descriptor, user_desc)
        if distance < threshold and distance < best_distance:
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


def _classify_descriptor_batch(descriptors: List[List[float]], known_user_id: Optional[str]) -> List[Dict]:
    detections = []

    for descriptor in descriptors:
        result = _find_best_match_for_descriptor(descriptor, known_user_id)
        detections.append({"descriptor": descriptor, "result": result})

    return detections


def _accumulate_session_detections_locked(session_id: str, detections: List[Dict]) -> Dict:
    session_state = _get_session_state_locked(session_id)
    history = session_state["history"]
    descriptor_history = session_state["descriptors"]
    latest_results: Dict[str, Dict] = {}

    for detection in detections:
        descriptor = detection["descriptor"]
        result = detection["result"]
        user_id = result["userId"]

        history[user_id] = history.get(user_id, 0) + 1
        latest_results[user_id] = result

        user_descriptors = descriptor_history.setdefault(user_id, [])
        user_descriptors.append(descriptor)
        descriptor_history[user_id] = user_descriptors[-UNKNOWN_RECOGNITION_THRESHOLD:]

    return {
        "session": session_state,
        "history": history,
        "descriptorHistory": descriptor_history,
        "latestResults": latest_results,
    }


def _build_pending_result(history: Dict[str, int], latest_results: Dict[str, Dict]) -> Dict:
    known_candidates = {
        user_id: count for user_id, count in history.items() if user_id not in ("unknown", "uncertain")
    }
    unknown_count = history.get("unknown", 0)

    if known_candidates:
        lead_user_id = max(known_candidates, key=known_candidates.get)
        lead_count = known_candidates[lead_user_id]
        lead_result = latest_results.get(lead_user_id, {})

        return {
            "pendingRecognition": True,
            "userId": lead_user_id,
            "userName": lead_result.get("userName", "unknown"),
            "needsIdentification": bool(lead_result.get("needsIdentification", False)),
            "isNewUser": False,
            "historyCount": lead_count,
            "detectionProgress": lead_count,
            "totalRequired": KNOWN_RECOGNITION_THRESHOLD,
        }

    return {
        "pendingRecognition": True,
        "userId": "unknown",
        "userName": "unknown",
        "needsIdentification": True,
        "isNewUser": True,
        "historyCount": unknown_count,
        "detectionProgress": unknown_count,
        "totalRequired": UNKNOWN_RECOGNITION_THRESHOLD,
    }


def _resolve_session_recognition_locked(session_id: str, detections: List[Dict]) -> Dict:
    accumulated = _accumulate_session_detections_locked(session_id, detections)
    history = accumulated["history"]
    descriptor_history = accumulated["descriptorHistory"]
    latest_results = accumulated["latestResults"]

    known_candidates = {
        user_id: count for user_id, count in history.items() if user_id not in ("unknown", "uncertain")
    }

    if known_candidates:
        winner_user_id = max(known_candidates, key=known_candidates.get)
        winner_count = known_candidates[winner_user_id]
        if winner_count >= KNOWN_RECOGNITION_THRESHOLD:
            latest_result = latest_results.get(winner_user_id, {})
            confirmed = _confirm_user_identity_with_descriptors(
                winner_user_id,
                descriptor_history.get(winner_user_id, []),
                latest_result,
            )
            _recognition_sessions.pop(session_id, None)
            return {
                **confirmed,
                "isConfirmed": True,
                "historyCount": winner_count,
                "detectionProgress": winner_count,
                "totalRequired": KNOWN_RECOGNITION_THRESHOLD,
            }

    unknown_count = history.get("unknown", 0)
    if unknown_count >= UNKNOWN_RECOGNITION_THRESHOLD:
        latest_result = latest_results.get("unknown", {})
        confirmed = _confirm_user_identity_with_descriptors(
            "unknown",
            descriptor_history.get("unknown", []),
            latest_result,
        )
        _recognition_sessions.pop(session_id, None)
        return {
            **confirmed,
            "isConfirmed": True,
            "historyCount": unknown_count,
            "detectionProgress": unknown_count,
            "totalRequired": UNKNOWN_RECOGNITION_THRESHOLD,
        }

    return _build_pending_result(history, latest_results)


def _confirm_user_identity_with_descriptors(user_id: str, descriptors: List[List[float]], result_data: Dict) -> Dict:
    valid = [d for d in descriptors if isinstance(d, list) and len(d) == 128]
    if not valid:
        return {"error": "No valid descriptors provided."}

    descriptor_model = ACTIVE_DESCRIPTOR_MODEL

    if user_id == "unknown":
        new_user_id = f"user{_face_db['nextId']}"
        _face_db["nextId"] += 1

        new_user = {
            "userId": new_user_id,
            "userName": None,
            "descriptorModel": descriptor_model,
            "descriptor": _average_descriptors(valid, descriptor_model),
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
    if _get_user_descriptor_model(user) != descriptor_model:
        return {
            "error": (
                f"User {user_id} was enrolled with descriptor model "
                f"{_get_user_descriptor_model(user)} and is incompatible with active backend {descriptor_model}."
            )
        }

    history = user.get("descriptorHistory") or []
    history.extend(valid)
    user["descriptorHistory"] = history[-MAX_DESCRIPTOR_HISTORY:]
    user["descriptorModel"] = descriptor_model
    user["descriptor"] = _average_descriptors(user["descriptorHistory"], descriptor_model)

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
    _ensure_db_loaded()

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

    # Legacy path: descriptors extracted in frontend (face-api.js 128D).
    # When using the robot-like backend, the server must compute descriptors from images.
    if descriptors and ACTIVE_DESCRIPTOR_MODEL == DESCRIPTOR_MODEL_LIGHTWEIGHT:
        for descriptor in descriptors[:CONFIRMATION_WINDOW_SIZE]:
            if _is_valid_descriptor(descriptor):
                batch_descriptors.append(_prepare_descriptor(descriptor, DESCRIPTOR_MODEL_LIGHTWEIGHT))

    # Primary backend path: compute descriptors from image bytes using the active backend.
    if not batch_descriptors:
        for image_bytes in face_buffers[:CONFIRMATION_WINDOW_SIZE]:
            descriptor = _extract_backend_descriptor(image_bytes)
            if descriptor is not None:
                batch_descriptors.append(descriptor)

    if not batch_descriptors:
        return {"error": "No valid face descriptors extracted."}

    with _db_lock:
        detections = _classify_descriptor_batch(batch_descriptors, known_user_id)
        if not detections:
            return {"error": "No recognition detections generated."}

        result = _resolve_session_recognition_locked(session_id, detections)
        if result.get("error"):
            return result

        return result

    return {"error": "Unexpected recognition state."}


def get_active_descriptor_model() -> str:
    return ACTIVE_DESCRIPTOR_MODEL
