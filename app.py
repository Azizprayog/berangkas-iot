from flask import Flask, render_template, request, redirect, url_for, jsonify
from database import init_db, get_db
from mqtt_client import start_mqtt, kunci_brankas, sync_wajah, status_brankas
from face_engine import clear_cache
import os
import base64
import uuid
import threading

app = Flask(__name__)
UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


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
    return redirect(url_for("index"))


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
    sync_wajah({"aksi": "tambah", "nama": nama, "path": path})
    clear_cache()
    return redirect(url_for("halaman_wajah") + "?success=Wajah+berhasil+ditambahkan")


@app.route("/wajah/update/<int:id>", methods=["POST"])
def update_wajah(id):
    nama = request.form["nama"]
    foto = request.files.get("foto")
    db = get_db()
    row = db.execute("SELECT * FROM wajah WHERE id=?", (id,)).fetchone()
    if row:
        if foto and foto.filename != "":
            if os.path.exists(row["foto_path"]):
                os.remove(row["foto_path"])
            filename = f"{nama}_{foto.filename}"
            path = os.path.join(UPLOAD_FOLDER, filename)
            foto.save(path)
            db.execute(
                "UPDATE wajah SET nama=?, foto_path=? WHERE id=?", (nama, path, id)
            )
        else:
            db.execute("UPDATE wajah SET nama=? WHERE id=?", (nama, id))
        db.commit()
        sync_wajah({"aksi": "update", "nama": nama})
        clear_cache()
    return redirect(url_for("halaman_wajah") + "?success=Wajah+berhasil+diupdate")


@app.route("/wajah/hapus/<int:id>", methods=["POST"])
def hapus_wajah(id):
    db = get_db()
    row = db.execute("SELECT * FROM wajah WHERE id=?", (id,)).fetchone()
    if row:
        if os.path.exists(row["foto_path"]):
            os.remove(row["foto_path"])
        db.execute("DELETE FROM wajah WHERE id=?", (id,))
        db.commit()
        sync_wajah({"aksi": "hapus", "nama": row["nama"]})
        clear_cache()
    return redirect(url_for("halaman_wajah") + "?success=Wajah+berhasil+dihapus")


# ─── MANAJEMEN SIDIK JARI ────────────────────────────────
@app.route("/sidik_jari")
def halaman_sidik_jari():
    db = get_db()
    data = db.execute("SELECT * FROM sidik_jari ORDER BY created_at DESC").fetchall()
    return render_template("sidik_jari.html", data=data)


@app.route("/sidik_jari/tambah", methods=["POST"])
def tambah_sidik_jari():
    nama = request.form["nama"]
    finger_id = request.form["finger_id"]
    db = get_db()
    db.execute(
        "INSERT INTO sidik_jari (nama, finger_id) VALUES (?, ?)", (nama, finger_id)
    )
    db.commit()
    return redirect(
        url_for("halaman_sidik_jari") + "?success=Sidik+jari+berhasil+ditambahkan"
    )


@app.route("/sidik_jari/hapus/<int:id>", methods=["POST"])
def hapus_sidik_jari(id):
    db = get_db()
    db.execute("DELETE FROM sidik_jari WHERE id=?", (id,))
    db.commit()
    return redirect(
        url_for("halaman_sidik_jari") + "?success=Sidik+jari+berhasil+dihapus"
    )


# ─── API STATUS ──────────────────────────────────────────
@app.route("/api/status")
def api_status():
    return jsonify(status_brankas)


# ─── LOG AKTIVITAS ───────────────────────────────────────
@app.route("/api/log")
def api_log():
    db = get_db()
    logs = db.execute(
        "SELECT * FROM log_brankas ORDER BY timestamp DESC LIMIT 50"
    ).fetchall()
    return jsonify([dict(row) for row in logs])


# ─── SETTINGS ────────────────────────────────────────────
@app.route("/api/settings", methods=["GET"])
def get_settings():
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    return jsonify({row["key"]: row["value"] for row in rows})


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json()
    db = get_db()
    for key, value in data.items():
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
    db.commit()
    return jsonify({"status": "ok"})


@app.route("/api/log/hapus-semua", methods=["POST"])
def hapus_semua_log():
    db = get_db()
    db.execute("DELETE FROM log_brankas")
    db.commit()
    return jsonify({"status": "ok"})


# ─── AUTO DELETE LOG ─────────────────────────────────────
def auto_delete_log():
    while True:
        try:
            db = get_db()
            row = db.execute(
                "SELECT value FROM settings WHERE key='log_retensi_hari'"
            ).fetchone()
            hari = int(row["value"]) if row else 7
            db.execute(
                "DELETE FROM log_brankas WHERE timestamp < datetime('now', ? || ' days')",
                (f"-{hari}",),
            )
            db.commit()
            db.close()
            print(f"[LOG] Auto-delete: hapus log lebih dari {hari} hari")
        except Exception as e:
            print(f"[LOG] Error auto-delete: {e}")
        threading.Event().wait(3600)


t = threading.Thread(target=auto_delete_log, daemon=True)
t.start()

if __name__ == "__main__":
    init_db()
    start_mqtt()
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
