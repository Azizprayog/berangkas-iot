import face_recognition
import numpy as np
import os
import sqlite3
import io

DB_PATH = "brankas.db"

# ================= CACHE =================
_cache = {"encodings": [], "names": []}


# ================= LOAD FACE DATA =================
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
            encs = face_recognition.face_encodings(img)

            if encs:
                known_encodings.append(encs[0])
                known_names.append(row["nama"])
                print(f"[FACE] Loaded: {row['nama']}")

        except Exception as e:
            print(f"[FACE] Error loading {path}: {e}")

    _cache["encodings"] = known_encodings
    _cache["names"] = known_names

    return known_encodings, known_names


# ================= CLEAR CACHE =================
def clear_cache():
    _cache["encodings"] = []
    _cache["names"] = []
    print("[FACE] Cache cleared")


# ================= REGISTER FACE =================
def register_face(nama: str, foto_path: str) -> dict:
    if not os.path.exists(foto_path):
        return {"success": False, "pesan": "File foto tidak ditemukan"}

    try:
        img = face_recognition.load_image_file(foto_path)
        encs = face_recognition.face_encodings(img)

        if not encs:
            return {"success": False, "pesan": "Wajah tidak terdeteksi"}

        encoding = encs[0]

        # simpan ke cache
        _cache["encodings"].append(encoding)
        _cache["names"].append(nama)

        # simpan ke database juga (WAJIB FIX INI)
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO wajah (nama, foto_path) VALUES (?, ?)",
            (nama, foto_path)
        )
        conn.commit()
        conn.close()

        print(f"[FACE] Register: {nama}")

        return {"success": True, "pesan": f"Wajah {nama} berhasil diregister"}

    except Exception as e:
        return {"success": False, "pesan": f"Error: {e}"}


# ================= VERIFY FACE (MAIN FUNCTION) =================
def verify_face(img_array=None, foto_path=None, threshold=0.48):
    try:
        # pilih sumber gambar
        if img_array is not None:
            unknown_img = img_array
        elif foto_path and os.path.exists(foto_path):
            unknown_img = face_recognition.load_image_file(foto_path)
        else:
            return {
                "match": False,
                "nama": None,
                "confidence": 0.0,
                "pesan": "Invalid image"
            }

        # detect wajah
        unknown_encs = face_recognition.face_encodings(unknown_img)

        if len(unknown_encs) != 1:
            return {
                "match": False,
                "nama": None,
                "confidence": 0.0,
                "pesan": "Wajah harus 1 orang saja"
            }

        unknown_enc = unknown_encs[0]

        # load database
        known_encodings, known_names = load_known_faces()

        if not known_encodings:
            return {
                "match": False,
                "nama": None,
                "confidence": 0.0,
                "pesan": "Database kosong"
            }

        # hitung jarak
        distances = face_recognition.face_distance(known_encodings, unknown_enc)

        if len(distances) == 0:
            return {
                "match": False,
                "nama": None,
                "confidence": 0.0,
                "pesan": "No match data"
            }

        best_idx = int(np.argmin(distances))
        best_distance = float(distances[best_idx])

        # confidence (simple tapi stabil untuk demo)
        confidence = max(0.0, 1.0 - best_distance)

        best_name = known_names[best_idx]

        # keputusan
        if best_distance <= threshold:
            return {
                "match": True,
                "nama": best_name,
                "confidence": round(confidence, 3),
                "pesan": f"Cocok: {best_name}"
            }
        else:
            return {
                "match": False,
                "nama": None,
                "confidence": round(confidence, 3),
                "pesan": "Tidak dikenali"
            }

    except Exception as e:
        return {
            "match": False,
            "nama": None,
            "confidence": 0.0,
            "pesan": f"Error: {e}"
        }