import paho.mqtt.client as mqtt
import json
import sqlite3
import base64

BROKER = "localhost"
PORT = 1883

# Topics
TOPIC_KUNCI = "brankas/kunci"
TOPIC_STATUS = "brankas/status"
TOPIC_WAJAH = "brankas/wajah/sync"
TOPIC_CAM_FOTO = "brankas/cam/foto"
TOPIC_CAM_RESULT = "brankas/cam/result"

status_brankas = {"keadaan": "tidak diketahui"}

def on_message(client, userdata, msg):
    if msg.topic == TOPIC_STATUS:
        payload = msg.payload.decode()
        status_brankas["keadaan"] = payload
        print(f"[MQTT] Status brankas: {payload}")

    elif msg.topic == TOPIC_CAM_FOTO:
        print("[MQTT] Foto diterima dari ESP32-CAM, memproses...")
        try:
            from face_engine import verify_face
            cocok, nama = verify_face(msg.payload)

            if cocok:
                print(f"[FACE] Akses diberikan: {nama}")
                client.publish(TOPIC_KUNCI, "UNLOCK")
                client.publish(TOPIC_CAM_RESULT, f"GRANTED:{nama}")
                conn = sqlite3.connect('brankas.db')
                conn.execute("INSERT INTO log_brankas (event) VALUES (?)",
                             (f"UNLOCK by face: {nama}",))
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
    client.connect(BROKER, PORT, 60)
    client.loop_start()

def kunci_brankas(aksi: str):
    client.publish(TOPIC_KUNCI, aksi)

def sync_wajah(data: dict):
    client.publish(TOPIC_WAJAH, json.dumps(data))