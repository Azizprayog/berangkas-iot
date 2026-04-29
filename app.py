# ─── IMPORTS ─────────────────────────────────────────────
from flask import Flask, render_template, request, redirect, url_for, jsonify
from database import init_db, get_db
from mqtt_client import (
    start_mqtt,
    kunci_brankas,
    status_brankas,
    client,
    verify_status,
)
from face_engine import verify_face, clear_cache, register_face
import os
import base64
import uuid
import threading
from PIL import Image
import numpy as np
import io

app = Flask(__name__)
UPLOAD_FOLDER = "static/uploads/foto"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ================= STATE =================
enroll_status = {
    "status": "idle",
    "pesan": "Belum mulai"
}

# ================= MQTT HELPER =================
def publish_verify_result(hasil):
    if hasil["match"]:
        client.publish("brankas/wajah/result", "WAJAH_OK")
    else:
        client.publish("brankas/wajah/result", "WAJAH_FAIL")


def sync_wajah(data):
    # optional biar gak error
    print("[SYNC WAJAH]", data)


# ─── INDEX ───────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", status=status_brankas["keadaan"])


# ─── KUNCI BRANKAS ───────────────────────────────────────
@app.route("/kunci/<aksi>", methods=["POST"])
def kontrol_kunci(aksi):
    if aksi in ["LOCK", "UNLOCK"]:
        kunci_brankas(aksi)
        db = get_db()
        db.execute("INSERT INTO log_brankas (event) VALUES (?)", (aksi,))
        db.commit()
        return jsonify({"status": "ok", "aksi": aksi})
    return jsonify({"status": "error"}), 400


# ─── MANAJEMEN WAJAH ─────────────────────────────────────
@app.route("/wajah")
def halaman_wajah():
    db = get_db()
    data = db.execute("SELECT * FROM wajah ORDER BY created_at DESC").fetchall()
    return render_template("wajah.html", data=data)


@app.route("/wajah/tambah", methods=["POST"])
def tambah_wajah():
    nama = request.form["nama"]
    foto = request.files.get("foto")
    foto_base64 = request.form.get("foto_base64", "")

    if foto and foto.filename != "":
        filename = f"{nama}_{foto.filename}"
        path = os.path.join(UPLOAD_FOLDER, filename)
        foto.save(path)
    elif foto_base64:
        header, data = foto_base64.split(",", 1)
        img_data = base64.b64decode(data)
        filename = f"{nama}_{uuid.uuid4().hex[:8]}.jpg"
        path = os.path.join(UPLOAD_FOLDER, filename)
        with open(path, "wb") as f:
            f.write(img_data)
    else:
        return redirect(url_for("halaman_wajah"))

    db = get_db()
    db.execute("INSERT INTO wajah (nama, foto_path) VALUES (?, ?)", (nama, path))
    db.commit()

    register_face(nama, path)
    clear_cache()

    return redirect(url_for("halaman_wajah"))


@app.route("/wajah/hapus/<int:id>", methods=["POST"])
def hapus_wajah(id):
    db = get_db()
    row = db.execute("SELECT * FROM wajah WHERE id=?", (id,)).fetchone()
    if row:
        if os.path.exists(row["foto_path"]):
            os.remove(row["foto_path"])
        db.execute("DELETE FROM wajah WHERE id=?", (id,))
        db.commit()
        clear_cache()
    return redirect(url_for("halaman_wajah"))


# ─── VERIFY WAJAH ────────────────────────────────────────
@app.route("/api/wajah/verify", methods=["POST"])
def api_verify_wajah():
    foto = request.files.get("foto")
    if not foto:
        return jsonify({"error": "no image"}), 400

    img = Image.open(foto.stream).convert("RGB")
    img_array = np.array(img)

    hasil = verify_face(img_array=img_array)

    publish_verify_result(hasil)

    return jsonify(hasil)


@app.route("/api/wajah/verify/status")
def api_verify_status():
    return jsonify(verify_status)


# ─── MANAJEMEN SIDIK JARI ────────────────────────────────
@app.route("/sidik_jari")
def halaman_sidik_jari():
    db = get_db()
    data = db.execute("SELECT * FROM sidik_jari").fetchall()
    return render_template("sidik_jari.html", data=data)


@app.route("/sidik_jari/tambah", methods=["POST"])
def tambah_sidik_jari():
    nama = request.form["nama"]
    finger_id = request.form["finger_id"]

    db = get_db()
    db.execute(
        "INSERT INTO sidik_jari (nama, finger_id) VALUES (?, ?)",
        (nama, finger_id)
    )
    db.commit()

    # update status UI
    enroll_status["status"] = "proses"
    enroll_status["pesan"] = f"Tempelkan jari ID {finger_id}"

    # kirim ke ESP32
    client.publish("brankas/sidik/enroll", str(finger_id))

    return redirect(url_for("halaman_sidik_jari"))


@app.route("/sidik_jari/hapus/<int:id>", methods=["POST"])
def hapus_sidik_jari(id):
    db = get_db()
    row = db.execute("SELECT * FROM sidik_jari WHERE id=?", (id,)).fetchone()
    if row:
        finger_id = row["finger_id"]

        db.execute("DELETE FROM sidik_jari WHERE id=?", (id,))
        db.commit()

        client.publish("brankas/sidik/hapus", str(finger_id))

    return redirect(url_for("halaman_sidik_jari"))


@app.route("/api/sidik/status")
def api_sidik_status():
    return jsonify(enroll_status)


# ─── API ─────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    return jsonify(status_brankas)


# ─── AUTO DELETE LOG ─────────────────────────────────────
def auto_delete_log():
    while True:
        try:
            db = get_db()
            db.execute("DELETE FROM log_brankas WHERE timestamp < datetime('now','-7 days')")
            db.commit()
        except:
            pass
        threading.Event().wait(3600)


threading.Thread(target=auto_delete_log, daemon=True).start()


# ─── MAIN ────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    start_mqtt()
    app.run(debug=False, host="0.0.0.0", port=5000)