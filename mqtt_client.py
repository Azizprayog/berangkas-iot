import paho.mqtt.client as mqtt
import json
import sqlite3
import base64
import ssl

BROKER = "294542ce25054f91be349c2b99c45ebc.s1.eu.hivemq.cloud"
PORT = 8883

USERNAME = "Sentinel-box"
PASSWORD = "Sentinelbox123"

# Topics
TOPIC_KUNCI = "brankas/kunci"
TOPIC_STATUS = "brankas/status"
TOPIC_WAJAH = "brankas/wajah/sync"
TOPIC_CAM_FOTO = "brankas/cam/foto"
TOPIC_CAM_RESULT = "brankas/cam/result"

status_brankas = {"keadaan": "tidak diketahui"}


def on_message(client, userdata, msg):
    if msg.topic == TOPIC_STATUS:
        payload = msg.payload.decode().strip().lower()
        status_brankas["keadaan"] = payload
        print(f"[MQTT] Status brankas dari ESP32: {payload}")

    elif msg.topic == TOPIC_CAM_FOTO:
        print("[MQTT] Foto diterima dari ESP32-CAM, memproses...")
        try:
            from face_engine import verify_face

            cocok, nama = verify_face(msg.payload)
            if cocok:
                print(f"[FACE] Akses diberikan: {nama}")
                client.publish(TOPIC_KUNCI, "UNLOCK")
                client.publish(TOPIC_CAM_RESULT, f"GRANTED:{nama}")
                # FIX: update status_brankas langsung
                status_brankas["keadaan"] = "terbuka"
                conn = sqlite3.connect("brankas.db")
                conn.execute(
                    "INSERT INTO log_brankas (event) VALUES (?)",
                    (f"UNLOCK by face: {nama}",),
                )
                conn.commit()
                conn.close()
            else:
                print("[FACE] Akses ditolak")
                client.publish(TOPIC_CAM_RESULT, "DENIED")
        except Exception as e:
            print(f"[MQTT] Error proses foto: {e}")
            client.publish(TOPIC_CAM_RESULT, "ERROR")


def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected, rc={rc}")
    client.subscribe(TOPIC_STATUS)
    client.subscribe(TOPIC_CAM_FOTO)


client = mqtt.Client()

client.on_connect = on_connect
client.on_message = on_message


def start_mqtt():
    client.username_pw_set(USERNAME, PASSWORD)

    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.tls_insecure_set(False)

    client.connect(BROKER, PORT, 60)
    client.loop_start()


def kunci_brankas(aksi: str):
    client.publish(TOPIC_KUNCI, aksi)
    # FIX: langsung update status_brankas tanpa nunggu ESP32 reply
    # Kalau ESP32 connected, nanti on_message akan override dengan nilai dari hardware
    if aksi == "UNLOCK":
        status_brankas["keadaan"] = "terbuka"
    elif aksi == "LOCK":
        status_brankas["keadaan"] = "terkunci"
    print(f"[MQTT] Perintah {aksi} dikirim, status lokal → {status_brankas['keadaan']}")


def sync_wajah(data: dict):
    client.publish(TOPIC_WAJAH, json.dumps(data))
