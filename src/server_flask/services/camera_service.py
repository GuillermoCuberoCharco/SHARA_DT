"""
services/camera_service.py

Face recognition service for SHARA_DT using the same persistence model as the
physical robot: a CSV file with repeated rows of username + 128D embedding.

The browser performs face detection and sends cropped face frames. The backend
extracts embeddings, matches them against the CSV database, and keeps temporary
in-memory encodings for unknown faces until the record_face action names them.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import face_recognition
import numpy as np
from PIL import Image

logger = logging.getLogger("FaceRecognition")


FACE_RECOGNITION_TOLERANCE = 0.55
CONFIRMATION_WINDOW_SIZE = 3
KNOWN_RECOGNITION_THRESHOLD = 3
UNKNOWN_RECOGNITION_THRESHOLD = 6
RECOGNITION_SESSION_TTL_SECONDS = 120
RECOGNITION_BACKEND_NAME = "face_recognition_v1"


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ENCODINGS_FILE = os.path.join(BASE_DIR, "files", "encodings.csv")
LEGACY_DB_FILE = os.path.join(BASE_DIR, "files", "face_database.json")


_db_lock = threading.Lock()
_face_db: Dict = {
    "loaded": False,
    "names": [],
    "encodings": np.empty((0, 128), dtype=np.float32),
}
_recognition_sessions: Dict[str, Dict] = {}
_pending_face_records: Dict[str, Dict] = {}


def _is_valid_encoding(encoding) -> bool:
    if not isinstance(encoding, list):
        return False
    if len(encoding) != 128:
        return False
    for value in encoding:
        if not isinstance(value, (int, float)):
            return False
    return True


def _normalize_face_box(face_box, image_shape) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(face_box, (list, tuple)) or len(face_box) != 4:
        return None

    try:
        top, right, bottom, left = [int(round(float(value))) for value in face_box]
    except (TypeError, ValueError):
        return None

    height, width = image_shape[:2]
    top = max(0, min(top, max(height - 1, 0)))
    right = max(0, min(right, max(width - 1, 0)))
    bottom = max(0, min(bottom, max(height - 1, 0)))
    left = max(0, min(left, max(width - 1, 0)))

    if bottom <= top or right <= left:
        return None

    return (top, right, bottom, left)


def _extract_face_encoding(
    image_bytes: bytes,
    face_box: Optional[List[int]] = None,
) -> Tuple[Optional[List[float]], bool]:
    if not image_bytes:
        return None, False

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.asarray(img, dtype=np.uint8)
        h, w = arr.shape[:2]
        if h == 0 or w == 0:
            return None, False

        known_face_box = _normalize_face_box(face_box, arr.shape)
        if known_face_box is None:
            known_face_box = (0, max(w - 1, 0), max(h - 1, 0), 0)

        encodings = face_recognition.face_encodings(arr, known_face_locations=[known_face_box])
        used_fallback = False
        if not encodings:
            used_fallback = True
            encodings = face_recognition.face_encodings(arr)

        if not encodings:
            return None, used_fallback

        return encodings[0].astype(np.float32).tolist(), used_fallback
    except Exception as exc:
        logger.warning("Face encoding extraction failed: %s", exc)
        return None, False


def _load_encodings_locked():
    names: List[str] = []
    encodings: List[List[float]] = []

    if os.path.exists(ENCODINGS_FILE):
        with open(ENCODINGS_FILE, "r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter=";")
            for row in reader:
                if len(row) < 129:
                    continue

                name = (row[0] or "").strip()
                if not name:
                    continue

                try:
                    encoding = [float(value) for value in row[1:129]]
                except ValueError:
                    continue

                if not _is_valid_encoding(encoding):
                    continue

                names.append(name)
                encodings.append(encoding)

    _face_db["names"] = names
    if encodings:
        _face_db["encodings"] = np.asarray(encodings, dtype=np.float32)
    else:
        _face_db["encodings"] = np.empty((0, 128), dtype=np.float32)


def _append_encoding_locked(user_name: str, encoding: List[float]):
    clean_name = (user_name or "").strip()
    if not clean_name or not _is_valid_encoding(encoding):
        return

    os.makedirs(os.path.dirname(ENCODINGS_FILE), exist_ok=True)
    with open(ENCODINGS_FILE, "a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow([clean_name, *encoding])

    _face_db["names"].append(clean_name)
    row = np.asarray([encoding], dtype=np.float32)
    if _face_db["encodings"].size == 0:
        _face_db["encodings"] = row
    else:
        _face_db["encodings"] = np.vstack((_face_db["encodings"], row))


def _migrate_legacy_face_db_locked():
    if not os.path.exists(LEGACY_DB_FILE):
        return

    try:
        with open(LEGACY_DB_FILE, "r", encoding="utf-8") as handle:
            legacy_db = json.load(handle)
    except Exception as exc:
        logger.warning("Could not load legacy face DB for migration: %s", exc)
        return

    migrated_users = 0
    migrated_encodings = 0

    for user in (legacy_db or {}).get("users", []):
        user_name = (user.get("userName") or "").strip()
        if not user_name or user_name == "unknown":
            continue

        history = [encoding for encoding in (user.get("descriptorHistory") or []) if _is_valid_encoding(encoding)]
        if not history:
            descriptor = user.get("descriptor")
            if _is_valid_encoding(descriptor):
                history = [descriptor]

        if not history:
            continue

        migrated_users += 1
        for encoding in history:
            _append_encoding_locked(user_name, encoding)
            migrated_encodings += 1

    if migrated_encodings:
        logger.info(
            "Migrated legacy face DB into encodings.csv: users=%s encodings=%s",
            migrated_users,
            migrated_encodings,
        )


def _ensure_db_loaded():
    with _db_lock:
        if _face_db["loaded"]:
            return

        os.makedirs(os.path.dirname(ENCODINGS_FILE), exist_ok=True)
        if os.path.exists(ENCODINGS_FILE):
            _load_encodings_locked()
            if _face_db["encodings"].size == 0 and os.path.exists(LEGACY_DB_FILE):
                _migrate_legacy_face_db_locked()
                _load_encodings_locked()
        else:
            open(ENCODINGS_FILE, "a", encoding="utf-8").close()
            _migrate_legacy_face_db_locked()
            _load_encodings_locked()

        _face_db["loaded"] = True


def _cleanup_expired_state_locked(now: Optional[datetime] = None):
    now = now or datetime.utcnow()

    expired_session_ids = []
    for session_id, session_data in _recognition_sessions.items():
        last_seen = session_data.get("lastSeenAt")
        if not isinstance(last_seen, datetime):
            expired_session_ids.append(session_id)
            continue

        if (now - last_seen).total_seconds() > RECOGNITION_SESSION_TTL_SECONDS:
            expired_session_ids.append(session_id)

    for session_id in expired_session_ids:
        _recognition_sessions.pop(session_id, None)

    expired_pending_ids = []
    for session_id, pending_data in _pending_face_records.items():
        last_seen = pending_data.get("lastSeenAt")
        if not isinstance(last_seen, datetime):
            expired_pending_ids.append(session_id)
            continue

        if (now - last_seen).total_seconds() > RECOGNITION_SESSION_TTL_SECONDS:
            expired_pending_ids.append(session_id)

    for session_id in expired_pending_ids:
        _pending_face_records.pop(session_id, None)


def _get_session_state_locked(session_id: str) -> Dict:
    now = datetime.utcnow()
    _cleanup_expired_state_locked(now)

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


def _build_match_result(user_name: Optional[str], distance: Optional[float] = None) -> Dict:
    if not user_name:
        return {
            "userName": "unknown",
            "distance": None,
            "confidence": 0.0,
            "needsIdentification": True,
        }

    confidence = 0.0 if distance is None else max(0.0, 1.0 - min(distance, 1.0))
    return {
        "userName": user_name,
        "distance": distance,
        "confidence": confidence,
        "needsIdentification": False,
    }


def _find_best_match_for_encoding(encoding: List[float]) -> Dict:
    known_encodings = _face_db["encodings"]
    if known_encodings.size == 0:
        return _build_match_result(None)

    query = np.asarray(encoding, dtype=np.float32)
    matches = face_recognition.compare_faces(
        known_encodings,
        query,
        tolerance=FACE_RECOGNITION_TOLERANCE,
    )
    if not any(matches):
        return _build_match_result(None)

    matched_indexes = [index for index, matched in enumerate(matches) if matched]
    if not matched_indexes:
        return _build_match_result(None)

    matched_encodings = known_encodings[matched_indexes]
    matched_distances = face_recognition.face_distance(matched_encodings, query)

    counts: Dict[str, int] = {}
    best_distance_by_name: Dict[str, float] = {}

    for position, index in enumerate(matched_indexes):
        user_name = _face_db["names"][index]
        counts[user_name] = counts.get(user_name, 0) + 1

        distance = float(matched_distances[position])
        previous_distance = best_distance_by_name.get(user_name, float("inf"))
        if distance < previous_distance:
            best_distance_by_name[user_name] = distance

    winner_name = max(counts, key=counts.get)
    return _build_match_result(winner_name, best_distance_by_name.get(winner_name))


def _accumulate_session_detections_locked(session_id: str, detections: List[Dict]) -> Dict:
    session_state = _get_session_state_locked(session_id)
    history = session_state["history"]
    encoding_history = session_state["encodings"]
    latest_results: Dict[str, Dict] = {}

    for detection in detections:
        encoding = detection["encoding"]
        result = detection["result"]
        user_name = result.get("userName") or "unknown"
        result_key = user_name if user_name != "unknown" else "unknown"

        history[result_key] = history.get(result_key, 0) + 1
        latest_results[result_key] = result

        user_encodings = encoding_history.setdefault(result_key, [])
        user_encodings.append(encoding)
        encoding_history[result_key] = user_encodings[-UNKNOWN_RECOGNITION_THRESHOLD:]

    return {
        "session": session_state,
        "history": history,
        "encodingHistory": encoding_history,
        "latestResults": latest_results,
    }


def _build_pending_result(history: Dict[str, int], latest_results: Dict[str, Dict]) -> Dict:
    known_candidates = {
        user_name: count for user_name, count in history.items() if user_name != "unknown"
    }
    unknown_count = history.get("unknown", 0)

    if known_candidates:
        lead_user_name = max(known_candidates, key=known_candidates.get)
        lead_count = known_candidates[lead_user_name]
        lead_result = latest_results.get(lead_user_name, {})

        return {
            "pendingRecognition": True,
            "userName": lead_result.get("userName", lead_user_name),
            "needsIdentification": False,
            "isNewUser": False,
            "historyCount": lead_count,
            "detectionProgress": lead_count,
            "totalRequired": KNOWN_RECOGNITION_THRESHOLD,
        }

    return {
        "pendingRecognition": True,
        "userName": "unknown",
        "needsIdentification": True,
        "isNewUser": True,
        "historyCount": unknown_count,
        "detectionProgress": unknown_count,
        "totalRequired": UNKNOWN_RECOGNITION_THRESHOLD,
    }


def _confirm_recognition_with_encodings(
    session_id: str,
    user_name: str,
    encodings: List[List[float]],
    result_data: Dict,
) -> Dict:
    valid = [encoding for encoding in encodings if _is_valid_encoding(encoding)]
    if not valid:
        return {"error": "No valid face encodings provided."}

    if user_name == "unknown":
        _pending_face_records[session_id] = {
            "encodings": valid[-UNKNOWN_RECOGNITION_THRESHOLD:],
            "lastSeenAt": datetime.utcnow(),
        }
        return {
            "userName": "unknown",
            "isNewUser": True,
            "needsIdentification": True,
            "distance": result_data.get("distance"),
            "confidence": result_data.get("confidence"),
        }

    return {
        "userName": user_name,
        "isNewUser": False,
        "needsIdentification": False,
        "distance": result_data.get("distance"),
        "confidence": result_data.get("confidence"),
    }


def _resolve_session_recognition_locked(session_id: str, detections: List[Dict]) -> Dict:
    accumulated = _accumulate_session_detections_locked(session_id, detections)
    history = accumulated["history"]
    encoding_history = accumulated["encodingHistory"]
    latest_results = accumulated["latestResults"]

    known_candidates = {
        user_name: count for user_name, count in history.items() if user_name != "unknown"
    }

    if known_candidates:
        winner_user_name = max(known_candidates, key=known_candidates.get)
        winner_count = known_candidates[winner_user_name]
        if winner_count >= KNOWN_RECOGNITION_THRESHOLD:
            latest_result = latest_results.get(winner_user_name, {})
            confirmed = _confirm_recognition_with_encodings(
                session_id,
                winner_user_name,
                encoding_history.get(winner_user_name, []),
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
        confirmed = _confirm_recognition_with_encodings(
            session_id,
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


def record_face_for_session(session_id: str, user_name: str) -> Dict:
    _ensure_db_loaded()

    clean_name = (user_name or "").strip()
    if not clean_name:
        return {"success": False, "error": "User name is required."}

    with _db_lock:
        _cleanup_expired_state_locked()
        pending = _pending_face_records.pop(session_id, None)
        if not pending:
            return {"success": False, "error": "No pending face record found for this session."}

        valid_encodings = [encoding for encoding in pending.get("encodings", []) if _is_valid_encoding(encoding)]
        if not valid_encodings:
            return {"success": False, "error": "No valid encodings available for recording."}

        for encoding in valid_encodings:
            _append_encoding_locked(clean_name, encoding)

    logger.info(
        "Recorded new face for session_id=%s username=%s encodings=%s",
        session_id,
        clean_name,
        len(valid_encodings),
    )
    return {"success": True, "userName": clean_name, "encodingsRecorded": len(valid_encodings)}


def recognize_face_with_batch(
    face_buffers: List[bytes],
    session_id: str,
    face_boxes: Optional[List[List[int]]] = None,
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

    with _db_lock:
        _get_session_state_locked(session_id)

    requested_count = min(len(face_buffers), CONFIRMATION_WINDOW_SIZE)
    extraction_elapsed_ms = 0.0
    classification_elapsed_ms = 0.0
    resolution_elapsed_ms = 0.0
    fallback_count = 0
    valid_encoding_count = 0
    detections_processed = 0
    result: Optional[Dict] = None

    for index, image_bytes in enumerate(face_buffers[:requested_count]):
        extraction_started_at = time.perf_counter()
        face_box = face_boxes[index] if face_boxes and index < len(face_boxes) else None
        encoding, used_fallback = _extract_face_encoding(image_bytes, face_box=face_box)
        extraction_elapsed_ms += (time.perf_counter() - extraction_started_at) * 1000

        if used_fallback:
            fallback_count += 1
        if encoding is None:
            continue

        valid_encoding_count += 1

        with _db_lock:
            classification_started_at = time.perf_counter()
            detection = {
                "encoding": encoding,
                "result": _find_best_match_for_encoding(encoding),
            }
            classification_elapsed_ms += (time.perf_counter() - classification_started_at) * 1000

            resolution_started_at = time.perf_counter()
            result = _resolve_session_recognition_locked(session_id, [detection])
            resolution_elapsed_ms += (time.perf_counter() - resolution_started_at) * 1000

        detections_processed += 1
        if result.get("error") or result.get("isConfirmed"):
            break

    logger.info(
        "Face batch encoding extraction: session_id=%s requested=%s valid=%s processed=%s fallback=%s elapsed_ms=%.1f",
        session_id,
        requested_count,
        valid_encoding_count,
        detections_processed,
        fallback_count,
        extraction_elapsed_ms,
    )

    if valid_encoding_count == 0:
        return {"error": "No valid face encodings extracted."}
    if not result:
        return {"error": "No recognition detections generated."}
    if result.get("error"):
        return result

    logger.info(
        "Face batch recognition resolved: session_id=%s detections=%s classification_ms=%.1f resolution_ms=%.1f confirmed=%s pending=%s",
        session_id,
        detections_processed,
        classification_elapsed_ms,
        resolution_elapsed_ms,
        bool(result.get("isConfirmed", False)),
        bool(result.get("pendingRecognition", False)),
    )

    return result


def get_active_descriptor_model() -> str:
    return RECOGNITION_BACKEND_NAME
