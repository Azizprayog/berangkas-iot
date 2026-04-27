import face_recognition
import numpy as np
import os
import sqlite3
import io

DB_PATH = "brankas.db"
UPLOAD_FOLDER = "static/uploads"

# Cache
_cache: dict = {"encodings": [], "names": []}


def load_known_faces(force_reload=False):
    if not force_reload and _cache["encodings"]:
        return _cache["encodings"], _cache["names"]

    known_encodings = []
    known_names = []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT nama, foto_path FROM wajah").fetchall()
    conn.close()

    for row in rows:
        path = row["foto_path"]
        if not os.path.exists(path):
            continue
        try:
            img = face_recognition.load_image_file(path)
            encodings = face_recognition.face_encodings(img)
            if encodings:
                known_encodings.append(encodings[0])
                known_names.append(row["nama"])
                print(f"[FACE] Loaded: {row['nama']}")
        except Exception as e:
            print(f"[FACE] Error loading {path}: {e}")

    _cache["encodings"] = known_encodings
    _cache["names"] = known_names
    return known_encodings, known_names


def clear_cache():
    _cache["encodings"] = []
    _cache["names"] = []
    print("[FACE] Cache cleared")


def register_face(nama: str, foto_path: str) -> dict:
    """Encode wajah dari foto dan simpan ke cache known faces."""
    if not os.path.exists(foto_path):
        return {"success": False, "pesan": "File foto tidak ditemukan"}
    try:
        img = face_recognition.load_image_file(foto_path)
        encs = face_recognition.face_encodings(img)
        if not encs:
            return {"success": False, "pesan": "Wajah tidak terdeteksi di foto"}

        _cache["encodings"].append(encs[0])
        _cache["names"].append(nama)
        print(f"[FACE] Register: {nama}")
        return {"success": True, "pesan": f"Wajah '{nama}' berhasil diregister"}
    except Exception as e:
        return {"success": False, "pesan": f"Error: {e}"}


def verify_face_bytes(image_bytes, tolerance=0.5):
    """Versi lama — dipanggil dari kode lama jika masih ada."""
    try:
        img = face_recognition.load_image_file(io.BytesIO(image_bytes))
        encodings = face_recognition.face_encodings(img)

        if not encodings:
            print("[FACE] Tidak ada wajah terdeteksi")
            return False, None

        face_enc = encodings[0]
        known_encodings, known_names = load_known_faces()

        if not known_encodings:
            print("[FACE] Database wajah kosong")
            return False, None

        matches = face_recognition.compare_faces(
            known_encodings, face_enc, tolerance=tolerance
        )
        distances = face_recognition.face_distance(known_encodings, face_enc)

        best_idx = np.argmin(distances)
        if matches[best_idx]:
            nama = known_names[best_idx]
            print(f"[FACE] Cocok: {nama} (distance: {distances[best_idx]:.3f})")
            return True, nama
        else:
            print(f"[FACE] Tidak cocok (distance: {distances[best_idx]:.3f})")
            return False, None

    except Exception as e:
        print(f"[FACE] Error: {e}")
        return False, None


def verify_face(img_array=None, foto_path=None, threshold=0.5):
    try:
        if img_array is not None:
            unknown_img = img_array
        elif foto_path and os.path.exists(foto_path):
            unknown_img = face_recognition.load_image_file(foto_path)
        else:
            return {"match": False, "nama": None, "confidence": 0.0, "pesan": "Invalid image"}

        unknown_encs = face_recognition.face_encodings(unknown_img)

        if len(unknown_encs) != 1:
            return {"match": False, "nama": None, "confidence": 0.0, "pesan": "Wajah harus 1 orang"}

        unknown_enc = unknown_encs[0]

        known_encodings, known_names = load_known_faces()

        if not known_encodings:
            return {"match": False, "nama": None, "confidence": 0.0, "pesan": "DB kosong"}

        distances = face_recognition.face_distance(known_encodings, unknown_enc)
        best_idx = int(np.argmin(distances))
        best_distance = float(distances[best_idx])
        confidence = max(0.0, 1.0 - best_distance)

        best_nama = known_names[best_idx] if known_names else None

        if best_distance <= threshold:
            return {
                "match": True,
                "nama": best_nama,
                "confidence": confidence,
                "pesan": f"Cocok: {best_nama}"
            }
        else:
            return {
                "match": False,
                "nama": None,
                "confidence": confidence,
                "pesan": "Tidak dikenali"
            }

    except Exception as e:
        return {"match": False, "nama": None, "confidence": 0.0, "pesan": f"Error: {e}"}