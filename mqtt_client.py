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
BROKER = "10.42.0.32"   # 🔥 ganti IP Laptop
PORT   = 1883

# ─── ESP32 CAM ───────────────────────────────────────────
ESP32_CAM_URL = "http://192.168.1.10/capture"  # 🔥 ganti IP cam

# ─── TOPICS ──────────────────────────────────────────────
TOPIC_KUNCI        = "brankas/kunci"
TOPIC_STATUS       = "brankas/status"
TOPIC_WAJAH        = "brankas/wajah/sync"
TOPIC_SIDIK_RESULT = "brankas/sidik/result"
TOPIC_WAJAH_VERIFY = "brankas/wajah/verify"
TOPIC_WAJAH_RESULT = "brankas/wajah/result"

# ─── FOLDER ──────────────────────────────────────────────
UPLOAD_FOLDER = "static/uploads/foto"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─── SHARED STATE ────────────────────────────────────────
status_brankas = {"keadaan": "tidak diketahui"}
enroll_status  = {"status": "idle", "pesan": ""}

verify_status  = {
    "match"     : False,
    "nama"      : None,
    "confidence": 0.0,
    "pesan"     : "Menunggu..."
}

# ─── THREAD SAFETY ───────────────────────────────────────
_verify_lock = threading.Lock()
is_verifying = False

# ─── FACE VERIFY (THREAD) ────────────────────────────────
def do_verify(client):
    global is_verifying

    # 🔐 anti race condition
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

        # ── Simpan file
        filename = f"{UPLOAD_FOLDER}/{int(time.time())}.jpg"
        with open(filename, "wb") as f:
            f.write(res.content)
        print(f"[INFO] Foto disimpan: {filename}")

        # ── Convert ke numpy
        img = Image.open(io.BytesIO(res.content)).convert("RGB")
        img_array = np.array(img)

        print("[PROCESS] Running face recognition...")
        hasil = verify_face(img_array=img_array)

        verify_status.update(hasil)
        print(f"[RESULT] {hasil}")

        # ── Publish hasil
        client.publish(TOPIC_WAJAH_RESULT, json.dumps(hasil))

    except Exception as e:
        print(f"[ERROR] Verify gagal: {e}")

    finally:
        # 🔓 release lock
        with _verify_lock:
            is_verifying = False

# ─── CALLBACKS ───────────────────────────────────────────
def on_message(client, userdata, msg):
    print(f"[MQTT] Topic masuk: {msg.topic}")

    if msg.topic == TOPIC_STATUS:
        payload = msg.payload.decode().strip().lower()
        status_brankas["keadaan"] = payload
        print(f"[MQTT] Status brankas: {payload}")

    elif msg.topic == TOPIC_SIDIK_RESULT:
        payload = msg.payload.decode().strip()
        print(f"[MQTT] Sidik result: {payload}")

        if payload.startswith("ENROLL_STEP1"):
            enroll_status.update({"status": "step1", "pesan": "Tempelkan jari pertama"})
        elif payload.startswith("ENROLL_STEP2"):
            enroll_status.update({"status": "step2", "pesan": "Tempelkan jari yang sama lagi"})
        elif payload.startswith("SUCCESS"):
            enroll_status.update({"status": "success", "pesan": "Berhasil"})
        elif payload.startswith("ERROR"):
            enroll_status.update({"status": "error", "pesan": payload.replace("ERROR:", "").strip()})

    elif msg.topic == TOPIC_WAJAH_VERIFY:
        print("[MQTT] Trigger VERIFY diterima")
        threading.Thread(target=do_verify, args=(client,), daemon=True).start()

# ─── CONNECT (kompatibel semua versi paho) ───────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connected ke Mosquitto")

        client.subscribe(TOPIC_STATUS)
        client.subscribe(TOPIC_SIDIK_RESULT)
        client.subscribe(TOPIC_WAJAH_VERIFY)

    else:
        print(f"[MQTT] Gagal connect, rc={rc}")

def on_disconnect(client, userdata, rc):
    print(f"[MQTT] Disconnected rc={rc} (auto reconnect by loop_start)")

# ─── CLIENT SETUP ────────────────────────────────────────
client = mqtt.Client()
client.on_connect    = on_connect
client.on_message    = on_message
client.on_disconnect = on_disconnect

# ─── START MQTT ──────────────────────────────────────────
def start_mqtt():
    print("[SYSTEM] Connecting ke MQTT...")
    client.connect(BROKER, PORT, 60)
    client.loop_start()

# ─── CONTROL FUNCTIONS ───────────────────────────────────
def kunci_brankas(aksi: str):
    client.publish(TOPIC_KUNCI, aksi)

    if aksi == "UNLOCK":
        status_brankas["keadaan"] = "terbuka"
    elif aksi == "LOCK":
        status_brankas["keadaan"] = "terkunci"

    print(f"[MQTT] {aksi} dikirim")

def sync_wajah(data: dict):
    client.publish(TOPIC_WAJAH, json.dumps(data))

def publish_verify_result(hasil: dict):
    client.publish(TOPIC_WAJAH_RESULT, json.dumps(hasil))

# ─── RUN MANUAL TEST ─────────────────────────────────────
if __name__ == "__main__":
    start_mqtt()
    print("[SYSTEM] MQTT client running...")

    while True:
        time.sleep(1)