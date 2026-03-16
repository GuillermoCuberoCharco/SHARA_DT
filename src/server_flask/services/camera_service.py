"""
services/camera_service.py

Face recognition service for SHARA_DT using the same recognition stack as the
physical robot: `face_recognition` encodings plus tolerance-based matching.

The browser is responsible only for face detection and sending cropped face
frames. Recognition and identity updates happen entirely in the backend.
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

import face_recognition
import numpy as np
from PIL import Image

logger = logging.getLogger("FaceRecognition")


FACE_RECOGNITION_TOLERANCE = 0.55
MAX_DESCRIPTOR_HISTORY = 5
CONFIRMATION_WINDOW_SIZE = 5
KNOWN_RECOGNITION_THRESHOLD = 3
UNKNOWN_RECOGNITION_THRESHOLD = 8
RECOGNITION_SESSION_TTL_SECONDS = 120
RECOGNITION_BACKEND_NAME = "face_recognition_v1"


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DB_FILE = os.path.join(BASE_DIR, "files", "face_database.json")


_db_lock = threading.Lock()
_face_db: Dict = {"nextId": 1, "users": []}
_recognition_sessions: Dict[str, Dict] = {}


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


def _is_valid_encoding(encoding) -> bool:
    if not isinstance(encoding, list):
        return False
    if len(encoding) != 128:
        return False
    for value in encoding:
        if not isinstance(value, (int, float)):
            return False
    return True


def _average_encodings(encodings: List[List[float]]) -> List[float]:
    mat = np.asarray(encodings, dtype=np.float32)
    avg = np.mean(mat, axis=0)
    return avg.astype(np.float32).tolist()


def _extract_face_encoding(image_bytes: bytes) -> Optional[List[float]]:
    if not image_bytes:
        return None

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.asarray(img, dtype=np.uint8)
        h, w = arr.shape[:2]
        if h == 0 or w == 0:
            return None

        # Match the physical robot: face detection already happened upstream,
        # so encode directly from the known crop instead of redetecting a face.
        full_crop_box = [(0, max(w - 1, 0), max(h - 1, 0), 0)]
        encodings = face_recognition.face_encodings(arr, known_face_locations=full_crop_box)
        if not encodings:
            # Fallback for crops where the full-frame box is not usable.
            encodings = face_recognition.face_encodings(arr)

        if not encodings:
            return None

        return encodings[0].astype(np.float32).tolist()
    except Exception as e:
        logger.warning(f"Face encoding extraction failed: {e}")
        return None


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
            "encodings": {},
            "lastSeenAt": now,
        },
    )
    session_state["lastSeenAt"] = now
    session_state.setdefault("history", {})
    session_state.setdefault("encodings", {})
    return session_state


def _find_user_by_id(user_id: str) -> Optional[Dict]:
    for user in _face_db["users"]:
        if user.get("userId") == user_id:
            return user
    return None


def _get_user_encodings(user: Dict) -> List[List[float]]:
    history = user.get("descriptorHistory") or []
    valid_history = [encoding for encoding in history if _is_valid_encoding(encoding)]
    if valid_history:
        return valid_history

    descriptor = user.get("descriptor")
    if _is_valid_encoding(descriptor):
        return [descriptor]

    return []


def _build_match_result(user: Dict, distance: float, user_id: Optional[str] = None) -> Dict:
    resolved_user_id = user_id or user.get("userId") or "unknown"
    return {
        "userId": resolved_user_id,
        "userName": user.get("userName") or "unknown",
        "distance": distance,
        "confidence": max(0.0, 1.0 - min(distance, 1.0)),
        "needsIdentification": not bool(user.get("userName")),
        "totalVisits": user.get("metadata", {}).get("visits", 0),
    }


def _find_best_match_for_encoding(encoding: List[float], known_user_id: Optional[str] = None) -> Dict:
    query = np.asarray(encoding, dtype=np.float32)

    if known_user_id and known_user_id != "unknown":
        known = _find_user_by_id(known_user_id)
        if known:
            known_encodings = _get_user_encodings(known)
            if known_encodings:
                matches = face_recognition.compare_faces(known_encodings, query, tolerance=FACE_RECOGNITION_TOLERANCE)
                if any(matches):
                    distances = face_recognition.face_distance(known_encodings, query)
                    matched_distances = [distance for matched, distance in zip(matches, distances) if matched]
                    return _build_match_result(known, float(min(matched_distances)), known_user_id)

    best_user = None
    best_match_count = 0
    best_distance = float("inf")

    for user in _face_db["users"]:
        user_encodings = _get_user_encodings(user)
        if not user_encodings:
            continue

        matches = face_recognition.compare_faces(user_encodings, query, tolerance=FACE_RECOGNITION_TOLERANCE)
        if not any(matches):
            continue

        distances = face_recognition.face_distance(user_encodings, query)
        matched_count = sum(1 for matched in matches if matched)
        matched_best_distance = min(float(distance) for matched, distance in zip(matches, distances) if matched)

        if matched_count > best_match_count or (matched_count == best_match_count and matched_best_distance < best_distance):
            best_user = user
            best_match_count = matched_count
            best_distance = matched_best_distance

    if best_user:
        return _build_match_result(best_user, best_distance)

    return {
        "userId": "unknown",
        "userName": "unknown",
        "distance": None,
        "confidence": 0.0,
        "needsIdentification": True,
    }


def _classify_encoding_batch(encodings: List[List[float]], known_user_id: Optional[str]) -> List[Dict]:
    detections = []

    for encoding in encodings:
        result = _find_best_match_for_encoding(encoding, known_user_id)
        detections.append({"encoding": encoding, "result": result})

    return detections


def _accumulate_session_detections_locked(session_id: str, detections: List[Dict]) -> Dict:
    session_state = _get_session_state_locked(session_id)
    history = session_state["history"]
    encoding_history = session_state["encodings"]
    latest_results: Dict[str, Dict] = {}

    for detection in detections:
        encoding = detection["encoding"]
        result = detection["result"]
        user_id = result["userId"]

        history[user_id] = history.get(user_id, 0) + 1
        latest_results[user_id] = result

        user_encodings = encoding_history.setdefault(user_id, [])
        user_encodings.append(encoding)
        encoding_history[user_id] = user_encodings[-UNKNOWN_RECOGNITION_THRESHOLD:]

    return {
        "session": session_state,
        "history": history,
        "encodingHistory": encoding_history,
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
    encoding_history = accumulated["encodingHistory"]
    latest_results = accumulated["latestResults"]

    known_candidates = {
        user_id: count for user_id, count in history.items() if user_id not in ("unknown", "uncertain")
    }

    if known_candidates:
        winner_user_id = max(known_candidates, key=known_candidates.get)
        winner_count = known_candidates[winner_user_id]
        if winner_count >= KNOWN_RECOGNITION_THRESHOLD:
            latest_result = latest_results.get(winner_user_id, {})
            confirmed = _confirm_user_identity_with_encodings(
                winner_user_id,
                encoding_history.get(winner_user_id, []),
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
        confirmed = _confirm_user_identity_with_encodings(
            "unknown",
            encoding_history.get("unknown", []),
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


def _confirm_user_identity_with_encodings(user_id: str, encodings: List[List[float]], result_data: Dict) -> Dict:
    valid = [encoding for encoding in encodings if _is_valid_encoding(encoding)]
    if not valid:
        return {"error": "No valid face encodings provided."}

    if user_id == "unknown":
        new_user_id = f"user{_face_db['nextId']}"
        _face_db["nextId"] += 1

        new_user = {
            "userId": new_user_id,
            "userName": None,
            "descriptor": _average_encodings(valid),
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

    history = _get_user_encodings(user)
    history.extend(valid)
    user["descriptorHistory"] = history[-MAX_DESCRIPTOR_HISTORY:]
    user["descriptor"] = _average_encodings(user["descriptorHistory"])

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
) -> Dict:
    """
    Main batch recognition entrypoint.
    The frontend sends cropped face images; the backend extracts encodings and
    applies the same face_recognition-based matching technique as the robot.
    """
    if not session_id:
        return {"error": "Session ID is required."}
    if not face_buffers:
        return {"error": "No images provided."}

    _ensure_db_loaded()

    # Refresh/create the session as soon as the request arrives so a slow
    # embedding extraction does not expire the accumulated history mid-batch.
    with _db_lock:
        _get_session_state_locked(session_id)

    extraction_started_at = time.perf_counter()
    batch_encodings: List[List[float]] = []
    for image_bytes in face_buffers[:CONFIRMATION_WINDOW_SIZE]:
        encoding = _extract_face_encoding(image_bytes)
        if encoding is not None:
            batch_encodings.append(encoding)
    extraction_elapsed_ms = (time.perf_counter() - extraction_started_at) * 1000

    logger.info(
        "Face batch encoding extraction: session_id=%s requested=%s valid=%s elapsed_ms=%.1f",
        session_id,
        min(len(face_buffers), CONFIRMATION_WINDOW_SIZE),
        len(batch_encodings),
        extraction_elapsed_ms,
    )

    if not batch_encodings:
        return {"error": "No valid face encodings extracted."}

    with _db_lock:
        classification_started_at = time.perf_counter()
        detections = _classify_encoding_batch(batch_encodings, known_user_id)
        classification_elapsed_ms = (time.perf_counter() - classification_started_at) * 1000
        if not detections:
            return {"error": "No recognition detections generated."}

        resolution_started_at = time.perf_counter()
        result = _resolve_session_recognition_locked(session_id, detections)
        resolution_elapsed_ms = (time.perf_counter() - resolution_started_at) * 1000
        if result.get("error"):
            return result

        logger.info(
            "Face batch recognition resolved: session_id=%s detections=%s classification_ms=%.1f resolution_ms=%.1f confirmed=%s pending=%s",
            session_id,
            len(detections),
            classification_elapsed_ms,
            resolution_elapsed_ms,
            bool(result.get("isConfirmed", False)),
            bool(result.get("pendingRecognition", False)),
        )

        return result

    return {"error": "Unexpected recognition state."}


def get_active_descriptor_model() -> str:
    return RECOGNITION_BACKEND_NAME
