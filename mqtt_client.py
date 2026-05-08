# mqtt_client.py - COMPLETE VERSION
import paho.mqtt.client as mqtt
import json
import requests
import time
import os
import threading
import numpy as np
from PIL import Image
import io
from face_engine import verify_face

# ─── MQTT CONFIG ─────────────────────────────────────────
BROKER = "10.4.0.160"  # Ganti dengan IP MQTT broker Anda
PORT = 1883

# ─── ESP32 CAM ───────────────────────────────────────────
ESP32_CAM_URL = "http://10.42.0.13/capture"  # Ganti IP ESP32-CAM

# ─── TOPICS ──────────────────────────────────────────────
TOPIC_STATUS = "brankas/status"
TOPIC_KUNCI  = "brankas/kunci"
TOPIC_RFID   = "brankas/rfid"
TOPIC_FINGER = "brankas/sidikjari"
TOPIC_ENROLL = "brankas/sidik/enroll"
TOPIC_DELETE = "brankas/sidik/hapus"
TOPIC_RELAY  = "brankas/relay"

# ─── FOLDER ──────────────────────────────────────────────
UPLOAD_FOLDER = "static/uploads/foto"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─── SHARED STATE ────────────────────────────────────────
status_brankas = {
    "keadaan": "tidak diketahui",
    "updated": 0.0
}
enroll_status = {"status": "idle", "pesan": ""}

verify_status = {
    "match": False,
    "nama": None,
    "confidence": 0.0,
    "pesan": "Menunggu...",
}

# ─── THREAD SAFETY ───────────────────────────────────────
_verify_lock = threading.Lock()
is_verifying = False


# ─── STATUS LOG ───────────────────────────────────────
def kirim_log(status):
    print(f"[LOG] Kirim: {status}")
    try:
        res = requests.post(
            "http://127.0.0.1:5000/api/log/fingerprint", json={"status": status}
        )
        print(f"[LOG] Response: {res.status_code}")
    except Exception as e:
        print(f"[LOG ERROR] {e}")


# ─── FACE VERIFY (THREAD) ────────────────────────────────
def do_verify(client):
    global is_verifying

    with _verify_lock:
        if is_verifying:
            print("[INFO] Masih proses sebelumnya, skip")
            return
        is_verifying = True

    try:
        print("[PROCESS] Ambil gambar dari ESP32-CAM...")

        try:
            res = requests.get(ESP32_CAM_URL, timeout=5)
        except requests.exceptions.Timeout:
            print("[ERROR] Timeout ke ESP32-CAM")
            return
        except requests.exceptions.ConnectionError:
            print("[ERROR] Tidak bisa connect ke ESP32-CAM")
            return

        if res.status_code != 200:
            print(f"[ERROR] HTTP status {res.status_code}")
            return

        filename = f"{UPLOAD_FOLDER}/{int(time.time())}.jpg"
        with open(filename, "wb") as f:
            f.write(res.content)
        print(f"[INFO] Foto disimpan: {filename}")

        img = Image.open(io.BytesIO(res.content)).convert("RGB")
        img_array = np.array(img)

        print("[PROCESS] Running face recognition...")
        hasil = verify_face(img_array=img_array)

        verify_status.update(hasil)
        print(f"[RESULT] {hasil}")

    except Exception as e:
        print(f"[ERROR] Verify gagal: {e}")

    finally:
        with _verify_lock:
            is_verifying = False


# ─── CALLBACKS MQTT ──────────────────────────────────────
def on_message(client, userdata, msg):
    payload = msg.payload.decode().strip()

    print(f"[MQTT] Topic: {msg.topic} → {payload}")

    # ================= STATUS =================
    if msg.topic == TOPIC_STATUS:
        status_brankas["keadaan"] = payload.lower()
        status_brankas["updated"] = time.time()

        print(f"[STATUS] {payload}")

    # ================= RFID =================
    elif msg.topic == TOPIC_RFID:
        payload = payload.upper()

        print(f"[RFID] {payload}")

        if payload != "UNKNOWN":
            kirim_log(f"RFID {payload}")

    # ================= FINGER =================
    elif msg.topic == TOPIC_FINGER:

        print(f"[FINGER] {payload}")

        if payload.startswith("MATCH:"):
            finger_id = payload.split(":")[1]

            status_brankas["keadaan"] = "terbuka"
            status_brankas["updated"] = time.time()

            kirim_log(f"FINGERPRINT ID {finger_id}")

        elif payload == "PROCESS":
            enroll_status.update({
                "status": "proses",
                "pesan": "🔄 Sidik jari sedang diproses..."
            })

        elif payload == "SUCCESS":
            enroll_status.update({
                "status": "success",
                "pesan": "✅ Sidik berhasil"
            })

        elif payload == "ERROR":
            enroll_status.update({
                "status": "error",
                "pesan": "❌ Sidik gagal"
            })

    # ================= RELAY =================
    elif msg.topic == TOPIC_RELAY:
        payload = payload.upper()

        if payload == "OPEN":
            status_brankas["keadaan"] = "terbuka"
            status_brankas["updated"] = time.time()

            kirim_log("BRANKAS TERBUKA")

            print("[RELAY] TERBUKA")

        elif payload == "CLOSED":
            status_brankas["keadaan"] = "terkunci"
            status_brankas["updated"] = time.time()

            kirim_log("BRANKAS TERKUNCI")

            print("[RELAY] TERKUNCI")

    # ================= DELETE =================
    elif msg.topic == TOPIC_DELETE:
        print(f"[DELETE] {payload}")


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] ✅ Connected ke Mosquitto")
        client.subscribe(TOPIC_STATUS)
        client.subscribe(TOPIC_FINGER)
        client.subscribe(TOPIC_DELETE)
        client.subscribe(TOPIC_RFID)
        client.subscribe(TOPIC_RELAY)
    else:
        print(f"[MQTT] ❌ Gagal connect, rc={rc}")


def on_disconnect(client, userdata, rc):
    print(f"[MQTT] Disconnected rc={rc}")


# ─── CLIENT SETUP ────────────────────────────────────────
client = mqtt.Client()
client.username_pw_set("sentinel", "Tes12345")

client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect


# ─── START MQTT ──────────────────────────────────────────
def start_mqtt():
    print("[SYSTEM] Starting MQTT client...")
    client.connect(BROKER, PORT, 60)
    client.loop_start()


# ─── CONTROL FUNCTIONS ───────────────────────────────────
def kunci_brankas(aksi: str):
    client.publish(TOPIC_KUNCI, aksi)

    print(f"[MQTT] {aksi} dikirim")


def enroll_fingerprint(finger_id: int):
    client.publish(TOPIC_ENROLL, str(finger_id))
    enroll_status.update({"status": "mulai", "pesan": f"Enroll ID {finger_id} dimulai"})
    print(f"[MQTT] Enroll ID {finger_id} dikirim")


def hapus_fingerprint(finger_id: int):
    client.publish("brankas/sidik/hapus", str(finger_id))
    print(f"[MQTT] Hapus ID {finger_id} dikirim")


# ─── FUNGSI UNTUK KOMPATIBILITAS DENGAN APP.PY ───────────
def sync_wajah(data: dict):
    """Sinkronisasi data wajah (kompatibilitas)"""
    print(f"[MQTT] Sync wajah: {data}")
    # client.publish(TOPIC_WAJAH_SYNC, json.dumps(data))
    pass


# ─── RUN ─────────────────────────────────────────────────
if __name__ == "__main__":
    start_mqtt()
    print("[SYSTEM] MQTT client running...")

    while True:
        time.sleep(1)