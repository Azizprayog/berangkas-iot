import paho.mqtt.client as mqtt
import json
import ssl

BROKER = "294542ce25054f91be349c2b99c45ebc.s1.eu.hivemq.cloud"
PORT = 8883
USERNAME = "sentinel"
PASSWORD = "Tes12345"

# ─── TOPICS ──────────────────────────────────────────────
TOPIC_KUNCI = "brankas/kunci"
TOPIC_STATUS = "brankas/status"
TOPIC_WAJAH = "brankas/wajah/sync"
TOPIC_SIDIK_RESULT = "brankas/sidik/result"

# ─── SHARED STATE ────────────────────────────────────────
status_brankas = {"keadaan": "tidak diketahui"}
enroll_status = {"status": "idle", "pesan": ""}


# ─── CALLBACKS ───────────────────────────────────────────
def on_message(client, userdata, msg):

    # Status brankas dari ESP32
    if msg.topic == TOPIC_STATUS:
        payload = msg.payload.decode().strip().lower()
        status_brankas["keadaan"] = payload
        print(f"[MQTT] Status brankas dari ESP32: {payload}")

    # Hasil enroll sidik jari dari ESP32
    elif msg.topic == TOPIC_SIDIK_RESULT:
        payload = msg.payload.decode().strip()
        print(f"[MQTT] Enroll result: {payload}")
        if payload.startswith("ENROLL_STEP1"):
            enroll_status["status"] = "step1"
            enroll_status["pesan"] = "Tempelkan jari pertama"
        elif payload.startswith("ENROLL_STEP2"):
            enroll_status["status"] = "step2"
            enroll_status["pesan"] = "Tempelkan jari yang sama lagi"
        elif payload.startswith("SUCCESS"):
            enroll_status["status"] = "success"
            enroll_status["pesan"] = "Berhasil"
        elif payload.startswith("ERROR"):
            enroll_status["status"] = "error"
            enroll_status["pesan"] = payload.replace("ERROR:", "").strip()


def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected, rc={rc}")
    client.subscribe(TOPIC_STATUS)
    client.subscribe(TOPIC_SIDIK_RESULT)


# ─── CLIENT SETUP ────────────────────────────────────────
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message


# ─── FUNCTIONS ───────────────────────────────────────────
def start_mqtt():
    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.tls_insecure_set(False)
    client.connect(BROKER, PORT, 60)
    client.loop_start()


def kunci_brankas(aksi: str):
    """Kirim perintah LOCK / UNLOCK ke ESP32."""
    client.publish(TOPIC_KUNCI, aksi)
    if aksi == "UNLOCK":
        status_brankas["keadaan"] = "terbuka"
    elif aksi == "LOCK":
        status_brankas["keadaan"] = "terkunci"
    print(f"[MQTT] Perintah {aksi} dikirim, status lokal → {status_brankas['keadaan']}")


def sync_wajah(data: dict):
    """Sinkronisasi data wajah ke ESP32."""
    client.publish(TOPIC_WAJAH, json.dumps(data))
