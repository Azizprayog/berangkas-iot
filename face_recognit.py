import io
import json
import logging
import os
import sqlite3
import threading
import time

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import numpy as np
import paho.mqtt.client as mqtt

# ──────────────────────────────────────────
# Konfigurasi
# ──────────────────────────────────────────
DB_PATH       = "brankas.db"
UPLOAD_FOLDER = "static/uploads/foto"

MQTT_BROKER          = "192.168.1.10"
MQTT_PORT            = 1883
MQTT_TOPIC_REG_CMD   = "brankas/wajah/register"
MQTT_TOPIC_REG_IMAGE = "brankas/wajah/image"
MQTT_TOPIC_STATUS    = "brankas/wajah/status"
PENDING_TIMEOUT = 30  # detik — nama expired setelah N detik tanpa foto

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("face_recognit")

# ──────────────────────────────────────────
# Thread-safe Pending State
# ──────────────────────────────────────────
_lock    = threading.Lock()
_pending: dict = {"nama": None, "ts": 0}


# ──────────────────────────────────────────
# DB Helper
# ──────────────────────────────────────────
def init_db() -> None:
    """Buat tabel wajah kalau belum ada."""
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wajah (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama       TEXT    NOT NULL,
                    foto_path  TEXT    NOT NULL,
                    created_at TEXT    DEFAULT (datetime('now','localtime'))
                )
            """)
            conn.commit()
        logger.info("DB siap")
    except sqlite3.Error as e:
        logger.error(f"Gagal init DB: {e}")


def save_to_db(nama: str, foto_path: str) -> int:
    """Simpan data wajah ke DB, return id baru."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO wajah (nama, foto_path) VALUES (?, ?)",
            (nama, foto_path),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


# ──────────────────────────────────────────
# Register Face (Core)
# ──────────────────────────────────────────
def register_face_from_bytes(nama: str, image_bytes: bytes) -> dict:
    """
    Encode wajah dari raw JPEG bytes lalu simpan ke disk + DB.

    Args:
        nama        : nama pendaftar
        image_bytes : raw JPEG dari ESP32-CAM

    Returns:
        dict:
            success  (bool) — True jika berhasil
            pesan    (str)  — pesan status
            foto_path (str) — path foto yang disimpan (jika success)
            id       (int)  — row id DB (jika success)
    """
    try:
        import cv2

        nparr   = np.frombuffer(image_bytes, np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img_bgr is None:
            logger.warning("register_face_from_bytes: gagal decode JPEG")
            return {"success": False, "pesan": "Gagal decode gambar JPEG"}

        # ⚠️ WAJIB: face_recognition butuh RGB, bukan BGR
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    except ImportError:
        # Fallback tanpa OpenCV — pakai PIL via io.BytesIO
        logger.warning("OpenCV tidak tersedia, fallback ke io.BytesIO")
        try:
            import face_recognition as _fr
            img_rgb = _fr.load_image_file(io.BytesIO(image_bytes))
        except Exception as e:
            logger.error(f"Fallback decode error: {e}")
            return {"success": False, "pesan": f"Gagal decode gambar: {e}"}

    except Exception as e:
        logger.error(f"Decode error: {e}")
        return {"success": False, "pesan": f"Error decode: {e}"}

    # ── Deteksi & encode wajah ───────────────────────────
    try:
        import face_recognition

        encs = face_recognition.face_encodings(img_rgb)
    except Exception as e:
        logger.error(f"Encode error [{nama}]: {e}")
        return {"success": False, "pesan": f"Gagal encode wajah: {e}"}

    if not encs:
        logger.warning(f"Tidak ada wajah terdeteksi untuk '{nama}'")
        return {"success": False, "pesan": "Wajah tidak terdeteksi di foto"}

    if len(encs) > 1:
        logger.warning(f"Terdeteksi {len(encs)} wajah untuk '{nama}' — harus tepat 1")
        return {"success": False, "pesan": f"Terdeteksi {len(encs)} wajah — harus tepat 1 orang"}

    # ── Simpan foto ke disk ──────────────────────────────
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filename  = f"{nama.replace(' ', '_')}_{int(time.time())}.jpg"
    foto_path = os.path.join(UPLOAD_FOLDER, filename)

    try:
        with open(foto_path, "wb") as f:
            f.write(image_bytes)
        logger.info(f"Foto disimpan: {foto_path}")
    except OSError as e:
        logger.error(f"Gagal simpan foto [{nama}]: {e}")
        return {"success": False, "pesan": f"Gagal simpan foto: {e}"}

    # ── Simpan ke DB ─────────────────────────────────────
    try:
        row_id = save_to_db(nama, foto_path)
        logger.info(f"Tersimpan di DB id={row_id}: {nama} → {foto_path}")
    except sqlite3.Error as e:
        os.remove(foto_path)
        logger.error(f"Gagal simpan DB [{nama}]: {e}")
        return {"success": False, "pesan": f"Wajah ter-encode tapi gagal simpan DB: {e}"}

    logger.info(f"Wajah diregister: {nama} (id={row_id})")
    return {
        "success":   True,
        "pesan":     f"Wajah '{nama}' berhasil diregister",
        "foto_path": foto_path,
        "id":        row_id,
    }


# ──────────────────────────────────────────
# MQTT Callbacks
# ──────────────────────────────────────────
def on_connect(client: mqtt.Client, userdata, flags, rc: int) -> None:
    if rc == 0:
        logger.info(f"Terhubung ke broker MQTT {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC_REG_CMD)
        client.subscribe(MQTT_TOPIC_REG_IMAGE)
        logger.info(f"Subscribe: {MQTT_TOPIC_REG_CMD}")
        logger.info(f"Subscribe: {MQTT_TOPIC_REG_IMAGE}")
    else:
        logger.error(f"Gagal connect MQTT rc={rc}")


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    if msg.topic == MQTT_TOPIC_REG_CMD:
        _handle_cmd(client, msg.payload)
    elif msg.topic == MQTT_TOPIC_REG_IMAGE:
        _handle_image(client, msg.payload)


def _handle_cmd(client: mqtt.Client, payload: bytes) -> None:
    """
    Terima nama pendaftar sebelum foto dikirim.
    Payload: JSON {"nama": "Budi"} atau plain text "Budi"
    """
    try:
        data = json.loads(payload.decode("utf-8"))
        nama = str(data.get("nama", "")).strip()
    except (json.JSONDecodeError, UnicodeDecodeError):
        nama = payload.decode("utf-8", errors="replace").strip()

    if not nama:
        logger.warning("CMD diterima tapi nama kosong")
        _publish_status(client, False, "Nama tidak boleh kosong")
        return

    with _lock:
        _pending["nama"] = nama
        _pending["ts"]   = time.time()

    logger.info(f"Pending registrasi: '{nama}' — tunggu foto dalam {PENDING_TIMEOUT}s")
    _publish_status(client, None, f"Siap terima foto untuk '{nama}'. Kirim dalam {PENDING_TIMEOUT}s.")


def _handle_image(client: mqtt.Client, payload: bytes) -> None:
    """
    Terima raw JPEG dari ESP32-CAM lalu proses registrasi.
    """
    with _lock:
        nama = _pending.get("nama")
        ts   = _pending.get("ts", 0)

    if not nama:
        logger.warning("Foto diterima tapi tidak ada nama pending")
        _publish_status(client, False, "Kirim nama dulu via topic cmd sebelum foto")
        return

    if time.time() - ts > PENDING_TIMEOUT:
        logger.warning(f"Nama '{nama}' sudah expired")
        with _lock:
            _pending["nama"] = None
        _publish_status(client, False, f"Timeout — nama '{nama}' expired, ulangi dari CMD")
        return

    logger.info(f"Foto diterima ({len(payload)} bytes) untuk '{nama}'")

    # ── Proses registrasi ────────────────────────────────
    result = register_face_from_bytes(nama, payload)

    if not result["success"]:
        logger.warning(f"Registrasi gagal: {result['pesan']}")
        _publish_status(client, False, result["pesan"])
        return

    # ── Reset pending setelah berhasil ───────────────────
    with _lock:
        _pending["nama"] = None
        _pending["ts"]   = 0

    _publish_status(client, True, result["pesan"])


# ──────────────────────────────────────────
# Publish Status Helper
# ──────────────────────────────────────────
def _publish_status(client: mqtt.Client, success, pesan: str) -> None:
    """
    Publish feedback ke topic status.
    success: True / False / None (info/pending)
    """
    payload = json.dumps({
        "success": success,
        "pesan":   pesan,
        "ts":      int(time.time()),
    })
    client.publish(MQTT_TOPIC_STATUS, payload)
    logger.info(f"[STATUS] {payload}")


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────
def main() -> None:
    init_db()

    client = mqtt.Client(client_id="face-register-service")
    client.on_connect = on_connect
    client.on_message = on_message

    logger.info(f"Menghubungkan ke {MQTT_BROKER}:{MQTT_PORT} ...")
    client.username_pw_set("sentinel", "Tes12345")
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    logger.info("Service berjalan. Ctrl+C untuk stop.")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("Service dihentikan")
        client.disconnect()


if __name__ == "__main__":
    main()