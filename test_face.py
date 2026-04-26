import paho.mqtt.client as mqtt
import time

BROKER = "localhost"
PORT = 1883
TOPIC_CAM_FOTO = "brankas/cam/foto"
TOPIC_CAM_RESULT = "brankas/cam/result"


def on_message(client, userdata, msg):
    if msg.topic == TOPIC_CAM_RESULT:
        result = msg.payload.decode()
        print(f"\n[RESULT] → {result}")
        if result.startswith("GRANTED"):
            print("✅ AKSES DIBERIKAN - Brankas terbuka!")
        elif result == "DENIED":
            print("❌ AKSES DITOLAK - Wajah tidak dikenal!")
        elif result == "ERROR":
            print("⚠️  ERROR saat proses gambar")


def on_connect(client, userdata, flags, rc):
    client.subscribe(TOPIC_CAM_RESULT)
    print("[MQTT] Terhubung, menunggu hasil...")


client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_start()

# Kirim foto test
foto_path = input("Masukkan path foto yang mau ditest: ").strip()

try:
    with open(foto_path, "rb") as f:
        image_bytes = f.read()
    print(f"\n[TEST] Mengirim foto: {foto_path}")
    client.publish(TOPIC_CAM_FOTO, image_bytes)
    time.sleep(10)  # tunggu hasil
except FileNotFoundError:
    print(f"❌ File tidak ditemukan: {foto_path}")

client.loop_stop()
