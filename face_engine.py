import io
import logging
import os
import sqlite3
import threading

import face_recognition
import numpy as np

# ──────────────────────────────────────────
# Konfigurasi
# ──────────────────────────────────────────
DB_PATH = "brankas.db"
UPLOAD_FOLDER = "static/uploads/foto"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("face_utils")

# ──────────────────────────────────────────
# Thread-safe Cache
# ──────────────────────────────────────────
_lock = threading.Lock()
_cache: dict = {"encodings": [], "names": []}


# ──────────────────────────────────────────
# Load Known Faces
# ──────────────────────────────────────────
def load_known_faces(force_reload: bool = False) -> tuple[list, list]:
    """
    Muat encoding wajah dari DB ke cache.
    Thread-safe. Hanya reload jika cache kosong atau force_reload=True.
    """
    with _lock:
        if not force_reload and _cache["encodings"]:
            logger.debug("Cache hit — skip reload dari DB")
            return list(_cache["encodings"]), list(_cache["names"])

        known_encodings: list = []
        known_names: list = []

        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT nama, foto_path FROM wajah").fetchall()
        except sqlite3.Error as e:
            logger.error(f"Gagal baca DB: {e}")
            return [], []

        for row in rows:
            path = row["foto_path"]
            if not os.path.exists(path):
                logger.warning(f"File tidak ditemukan, skip: {path}")
                continue
            try:
                img = face_recognition.load_image_file(path)
                encodings = face_recognition.face_encodings(img)
                if encodings:
                    known_encodings.append(encodings[0])
                    known_names.append(row["nama"])
                    logger.info(f"Loaded wajah: {row['nama']}")
                else:
                    logger.warning(f"Tidak ada wajah di foto: {path}")
            except Exception as e:
                logger.error(f"Error loading {path}: {e}")

        _cache["encodings"] = known_encodings
        _cache["names"] = known_names
        logger.info(f"Cache diperbarui — total {len(known_names)} wajah")
        return list(known_encodings), list(known_names)


# ──────────────────────────────────────────
# Clear Cache
# ──────────────────────────────────────────
def clear_cache() -> None:
    """Kosongkan cache (paksa reload dari DB pada call berikutnya)."""
    with _lock:
        _cache["encodings"] = []
        _cache["names"] = []
    logger.info("Cache dikosongkan")


# ──────────────────────────────────────────
# Register Face
# ──────────────────────────────────────────
def register_face(nama: str, foto_path: str) -> dict:
    """
    Encode wajah dari foto dan tambahkan ke cache.
    Tidak menyimpan ke DB — itu tanggung jawab caller.
    """
    if not os.path.exists(foto_path):
        logger.warning(f"Register gagal — file tidak ditemukan: {foto_path}")
        return {"success": False, "pesan": "File foto tidak ditemukan"}

    try:
        img = face_recognition.load_image_file(foto_path)
        encs = face_recognition.face_encodings(img)

        if not encs:
            logger.warning(f"Register gagal — wajah tidak terdeteksi: {foto_path}")
            return {"success": False, "pesan": "Wajah tidak terdeteksi di foto"}

        with _lock:
            _cache["encodings"].append(encs[0])
            _cache["names"].append(nama)

        logger.info(f"Wajah diregister: {nama}")
        return {"success": True, "pesan": f"Wajah '{nama}' berhasil diregister"}

    except Exception as e:
        logger.error(f"Register error [{nama}]: {e}")
        return {"success": False, "pesan": f"Error: {e}"}


# ──────────────────────────────────────────
# Verify Face (Core)
# ──────────────────────────────────────────
def verify_face(
    img_array: np.ndarray | None = None,
    foto_path: str | None = None,
    threshold: float = 0.5,
) -> dict:
    """
    Verifikasi wajah terhadap database.

    Args:
        img_array : numpy array RGB (dari OpenCV/ESP32-CAM setelah konversi BGR→RGB)
        foto_path : path ke file gambar (alternatif img_array)
        threshold : jarak maksimum untuk dianggap match (default 0.5)

    Returns:
        dict:
            match      (bool)  — True jika cocok
            nama       (str)   — nama yang cocok, None jika tidak
            confidence (float) — 0.0–1.0
            distance   (float) — raw face distance
            pesan      (str)   — pesan status
    """
    # ── 1. Load gambar ──────────────────────────────────
    try:
        if img_array is not None:
            unknown_img = img_array
        elif foto_path and os.path.exists(foto_path):
            unknown_img = face_recognition.load_image_file(foto_path)
        else:
            logger.warning("verify_face: input tidak valid")
            return _result(False, None, 0.0, 1.0, "Input gambar tidak valid")
    except Exception as e:
        logger.error(f"verify_face: gagal load gambar — {e}")
        return _result(False, None, 0.0, 1.0, f"Gagal load gambar: {e}")

    # ── 2. Deteksi wajah ────────────────────────────────
    try:
        unknown_encs = face_recognition.face_encodings(unknown_img)
    except Exception as e:
        logger.error(f"verify_face: gagal encode — {e}")
        return _result(False, None, 0.0, 1.0, f"Gagal encode wajah: {e}")

    n = len(unknown_encs)
    if n == 0:
        logger.info("verify_face: tidak ada wajah terdeteksi")
        return _result(False, None, 0.0, 1.0, "Tidak ada wajah terdeteksi")
    if n > 1:
        logger.info(f"verify_face: {n} wajah terdeteksi, harus tepat 1")
        return _result(
            False, None, 0.0, 1.0, f"Terdeteksi {n} wajah — harus tepat 1 orang"
        )

    unknown_enc = unknown_encs[0]

    # ── 3. Bandingkan dengan database ───────────────────
    known_encodings, known_names = load_known_faces()

    if not known_encodings:
        logger.warning("verify_face: database wajah kosong")
        return _result(False, None, 0.0, 1.0, "Database wajah kosong")

    distances = face_recognition.face_distance(known_encodings, unknown_enc)
    best_idx = int(np.argmin(distances))
    best_distance = float(distances[best_idx])
    confidence = round(max(0.0, 1.0 - best_distance), 4)
    best_nama = known_names[best_idx]

    # ── 4. Evaluasi hasil ────────────────────────────────
    if best_distance <= threshold:
        logger.info(
            f"MATCH: {best_nama} | distance={best_distance:.4f} | confidence={confidence:.4f}"
        )
        return _result(
            True, best_nama, confidence, best_distance, f"Cocok: {best_nama}"
        )
    else:
        logger.info(
            f"NO MATCH | closest={best_nama} | distance={best_distance:.4f} | confidence={confidence:.4f}"
        )
        return _result(False, None, confidence, best_distance, "Wajah tidak dikenali")


# ──────────────────────────────────────────
# Verify dari Bytes (MQTT / ESP32-CAM)
# ──────────────────────────────────────────
def verify_face_bytes(image_bytes: bytes, tolerance: float = 0.5) -> dict:
    """
    Verifikasi wajah dari raw bytes (JPEG dari ESP32-CAM via MQTT).

    Otomatis konversi BGR → RGB menggunakan OpenCV.
    Return sama dengan verify_face().
    """
    try:
        import cv2

        nparr = np.frombuffer(image_bytes, np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img_bgr is None:
            logger.warning("verify_face_bytes: gagal decode JPEG")
            return _result(False, None, 0.0, 1.0, "Gagal decode gambar JPEG")

        # ⚠️ WAJIB: face_recognition butuh RGB, bukan BGR
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        return verify_face(img_array=img_rgb, threshold=tolerance)

    except ImportError:
        # Fallback tanpa OpenCV — pakai PIL via io.BytesIO
        logger.warning("OpenCV tidak tersedia, fallback ke io.BytesIO")
        try:
            img = face_recognition.load_image_file(io.BytesIO(image_bytes))
            return verify_face(img_array=img, threshold=tolerance)
        except Exception as e:
            logger.error(f"verify_face_bytes fallback error: {e}")
            return _result(False, None, 0.0, 1.0, f"Error: {e}")

    except Exception as e:
        logger.error(f"verify_face_bytes error: {e}")
        return _result(False, None, 0.0, 1.0, f"Error: {e}")


# ──────────────────────────────────────────
# Helper
# ──────────────────────────────────────────
def _result(
    match: bool,
    nama: str | None,
    confidence: float,
    distance: float,
    pesan: str,
) -> dict:
    return {
        "match": match,
        "nama": nama,
        "confidence": confidence,
        "distance": round(distance, 4),
        "pesan": pesan,
    }
