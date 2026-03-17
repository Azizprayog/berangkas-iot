import face_recognition
import numpy as np
import os
import sqlite3
import io

DB_PATH = 'brankas.db'
UPLOAD_FOLDER = 'static/uploads'

# Cache
_cache = {"encodings": None, "names": None}

def load_known_faces(force_reload=False):
    if not force_reload and _cache["encodings"] is not None:
        return _cache["encodings"], _cache["names"]

    known_encodings = []
    known_names = []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT nama, foto_path FROM wajah").fetchall()
    conn.close()

    for row in rows:
        path = row['foto_path']
        if not os.path.exists(path):
            continue
        try:
            img = face_recognition.load_image_file(path)
            encodings = face_recognition.face_encodings(img)
            if encodings:
                known_encodings.append(encodings[0])
                known_names.append(row['nama'])
                print(f"[FACE] Loaded: {row['nama']}")
        except Exception as e:
            print(f"[FACE] Error loading {path}: {e}")

    _cache["encodings"] = known_encodings # type: ignore
    _cache["names"] = known_names  # type: ignore
    return known_encodings, known_names

def clear_cache():
    _cache["encodings"] = None
    _cache["names"] = None
    print("[FACE] Cache cleared")

def verify_face(image_bytes, tolerance=0.5):
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

        matches = face_recognition.compare_faces(known_encodings, face_enc, tolerance=tolerance)
        distances = face_recognition.face_distance(known_encodings, face_enc)

        best_idx = np.argmin(distances)
        if matches[best_idx]:
            nama = known_names[best_idx]  # type: ignore
            print(f"[FACE] Cocok: {nama} (distance: {distances[best_idx]:.3f})")
            return True, nama
        else:
            print(f"[FACE] Tidak cocok (distance: {distances[best_idx]:.3f})")
            return False, None

    except Exception as e:
        print(f"[FACE] Error: {e}")
        return False, None