import os
import sys
import sqlite3
import json
import math
import time
from datetime import datetime
from flask import Flask, request, jsonify

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

app = Flask(__name__)

# ── Paths & Storage Setup ────────────────────────────────────────────────────
DATA_DIR = "data"
BACKEND_STORAGE_DIR = os.path.join(DATA_DIR, "backend_storage")
BACKEND_AUDIO_DIR = os.path.join(BACKEND_STORAGE_DIR, "audio")
DB_PATH = os.path.join(DATA_DIR, "backend_safety.db")
PAST_LOCATIONS_FILE = os.path.join(DATA_DIR, "past_locations.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKEND_AUDIO_DIR, exist_ok=True)

ROUTE_FILE = os.path.join(DATA_DIR, "planned_route.json")


def load_planned_route():
    if os.path.exists(ROUTE_FILE):
        try:
            with open(ROUTE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


PLANNED_ROUTE = load_planned_route()


# ── Database Initialization ──────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Emergency Events Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emergency_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE,
            timestamp TEXT,
            threat_type TEXT,
            latitude REAL,
            longitude REAL,
            maps_link TEXT,
            audio_filename TEXT,
            contacts_notified TEXT,
            call_status TEXT,
            sms_status TEXT,
            sync_status TEXT DEFAULT 'SYNCED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Audio Evidence Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audio_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            filename TEXT,
            filepath TEXT,
            file_size_bytes INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Geofence Events Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS geofence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            zone_name TEXT,
            event_type TEXT,
            latitude REAL,
            longitude REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Location History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS location_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            latitude REAL,
            longitude REAL,
            speed_kmh REAL,
            is_deviated INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Battery Log Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS battery_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            level REAL,
            source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

init_db()


# ── Mathematical & Route Helpers ─────────────────────────────────────────────
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0  # Earth radius in KM
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def save_location(lat, lon, speed_kmh=0.0, is_deviated=False):
    # Save to SQLite
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO location_history (timestamp, latitude, longitude, speed_kmh, is_deviated)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), lat, lon, speed_kmh, 1 if is_deviated else 0))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[Backend DB Error] {exc}")

    # Also keep JSON history for backward compatibility
    data = []
    try:
        if os.path.exists(PAST_LOCATIONS_FILE):
            with open(PAST_LOCATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lat": lat,
        "lon": lon
    }
    data.append(entry)
    if len(data) > 500:
        data = data[-500:]

    with open(PAST_LOCATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def predict_next_location():
    try:
        if os.path.exists(PAST_LOCATIONS_FILE):
            with open(PAST_LOCATIONS_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
                if len(history) >= 2:
                    last = history[-1]
                    prev = history[-2]

                    d_lat = last['lat'] - prev['lat']
                    d_lon = last['lon'] - prev['lon']

                    predicted_lat = round(last['lat'] + d_lat, 6)
                    predicted_lon = round(last['lon'] + d_lon, 6)

                    return {
                        "predicted_lat": predicted_lat,
                        "predicted_lon": predicted_lon,
                        "method": "linear_velocity_vector"
                    }
    except Exception as e:
        print("[Backend Prediction Error]:", e)
    return None


def check_route_deviation(current_lat, current_lon, max_dev_km=1.5):
    if not PLANNED_ROUTE:
        return False, 0.0
    min_dist = float('inf')
    for point in PLANNED_ROUTE:
        dist = calculate_distance(current_lat, current_lon, point[0], point[1])
        if dist < min_dist:
            min_dist = dist

    if min_dist > max_dev_km:
        return True, min_dist
    return False, min_dist


# ── REST API Endpoints ────────────────────────────────────────────────────────

@app.route('/api/route', methods=['GET', 'POST'])
def api_manage_route():
    """Dynamically get or update the planned corridor."""
    global PLANNED_ROUTE
    if request.method == 'POST':
        data = request.json or {}
        route = data.get("route", [])
        if isinstance(route, list):
            PLANNED_ROUTE = route
            try:
                with open(ROUTE_FILE, "w", encoding="utf-8") as f:
                    json.dump(PLANNED_ROUTE, f, indent=2)
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500
            return jsonify({
                "status": "success",
                "message": f"Planned route updated with {len(PLANNED_ROUTE)} waypoints.",
                "route": PLANNED_ROUTE
            })
        return jsonify({"status": "error", "message": "Expected list of [lat, lon] waypoints"}), 400

    return jsonify({"status": "success", "route": PLANNED_ROUTE})

@app.route('/api/status', methods=['GET'])
def get_status():
    """Health check and backend metrics."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM emergency_events")
        events_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM audio_evidence")
        audio_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM geofence_events")
        geofence_count = cursor.fetchone()[0]
        conn.close()
    except Exception:
        events_count = audio_count = geofence_count = 0

    return jsonify({
        "status": "online",
        "service": "AURA Women Safety Backend",
        "timestamp": datetime.now().isoformat(),
        "database": {
            "emergency_events": events_count,
            "audio_recordings": audio_count,
            "geofence_events": geofence_count
        }
    })


@app.route('/update_location', methods=['POST'])
def update_location():
    data = request.json or {}
    lat = float(data.get('lat', 0.0))
    lon = float(data.get('lon', 0.0))
    speed = float(data.get('speed', 0.0))

    is_deviated, dev_dist = check_route_deviation(lat, lon)
    save_location(lat, lon, speed, is_deviated)
    prediction = predict_next_location()

    response = {
        "status": "success",
        "route_deviated": is_deviated,
        "deviation_distance_km": round(dev_dist, 2),
        "prediction": prediction
    }

    if is_deviated:
        print(f"⚠️ [BACKEND ALERT] User deviated from route by {round(dev_dist, 2)} km!")

    return jsonify(response)


@app.route('/fall_detected', methods=['POST'])
def fall_detected():
    data = request.json or {}
    lat = data.get('lat', 0.0)
    lon = data.get('lon', 0.0)
    print(f"🚨 [BACKEND EMERGENCY] Phone Fall Detected! (Lat: {lat}, Lon: {lon})")

    # Save to emergency events
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        event_id = f"FALL_{int(time.time())}"
        cursor.execute("""
            INSERT INTO emergency_events (event_id, timestamp, threat_type, latitude, longitude, maps_link)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            datetime.now().isoformat(),
            "PHONE_FALL_DETECTED",
            lat,
            lon,
            f"https://maps.google.com/?q={lat},{lon}"
        ))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[Backend DB Error on fall]: {exc}")

    return jsonify({"status": "Fall Alert Received", "action": "Triggering SOS", "event_id": event_id})


@app.route('/battery_status', methods=['POST'])
def battery_status():
    data = request.json or {}
    level = data.get('level', 100)
    source = data.get('source', 'Unknown Device')
    print(f"🔋 [BACKEND] Battery Status: {level}% from {source}")

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO battery_logs (timestamp, level, source)
            VALUES (?, ?, ?)
        """, (datetime.now().isoformat(), level, source))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[Backend DB Error]: {exc}")

    return jsonify({"status": "Battery Logged", "level": level})


@app.route('/api/emergency/event', methods=['POST'])
def record_emergency_event():
    """Receives complete emergency dispatch details from the safety controller."""
    data = request.json or {}
    event_id = data.get("event_id", f"SOS_{int(time.time() * 1000)}")
    timestamp = data.get("timestamp", datetime.now().isoformat())
    threat_type = data.get("threat_type", "EMERGENCY_TRIGGER")
    lat = float(data.get("latitude", 0.0))
    lon = float(data.get("longitude", 0.0))
    maps_link = data.get("maps_link", f"https://maps.google.com/?q={lat},{lon}")
    audio_filename = data.get("audio_filename", "")
    contacts = json.dumps(data.get("contacts_notified", []))
    call_status = data.get("call_status", "UNKNOWN")
    sms_status = data.get("sms_status", "UNKNOWN")

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO emergency_events 
            (event_id, timestamp, threat_type, latitude, longitude, maps_link, audio_filename, contacts_notified, call_status, sms_status, sync_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SYNCED')
        """, (event_id, timestamp, threat_type, lat, lon, maps_link, audio_filename, contacts, call_status, sms_status))
        conn.commit()
        conn.close()

        print(f"💾 [BACKEND] Saved Emergency Event: {event_id} ({threat_type})")
        return jsonify({"status": "success", "event_id": event_id, "saved": True}), 201
    except Exception as exc:
        print(f"[Backend Emergency Save Error]: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route('/api/emergency/upload_audio', methods=['POST'])
def upload_audio():
    """Uploads recorded emergency audio evidence to backend storage."""
    if 'audio' not in request.files:
        return jsonify({"status": "error", "message": "No audio file part in request"}), 400

    file = request.files['audio']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    event_id = request.form.get("event_id", "UNKNOWN_EVENT")
    filename = file.filename
    save_path = os.path.join(BACKEND_AUDIO_DIR, filename)
    file.save(save_path)
    file_size = os.path.getsize(save_path)

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audio_evidence (event_id, filename, filepath, file_size_bytes)
            VALUES (?, ?, ?, ?)
        """, (event_id, filename, save_path, file_size))
        # Update emergency_events if matches
        cursor.execute("""
            UPDATE emergency_events SET audio_filename = ? WHERE event_id = ?
        """, (filename, event_id))
        conn.commit()
        conn.close()

        print(f"🎙️ [BACKEND] Audio Evidence Stored: {filename} ({file_size} bytes)")
        return jsonify({"status": "success", "filename": filename, "size": file_size}), 201
    except Exception as exc:
        print(f"[Backend Audio DB Error]: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route('/api/emergency/events', methods=['GET'])
def list_emergency_events():
    """Returns all emergency events stored in backend."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM emergency_events ORDER BY id DESC LIMIT 50")
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify({"status": "success", "count": len(rows), "events": rows})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route('/api/geofence/event', methods=['POST'])
def record_geofence_event():
    """Records entry/exit geofence transitions."""
    data = request.json or {}
    zone_name = data.get("zone_name", "Unknown Zone")
    event_type = data.get("event_type", "BREACH")  # "ENTRY" or "EXIT"
    timestamp = data.get("timestamp", datetime.now().isoformat())
    lat = float(data.get("latitude", 0.0))
    lon = float(data.get("longitude", 0.0))

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO geofence_events (timestamp, zone_name, event_type, latitude, longitude)
            VALUES (?, ?, ?, ?, ?)
        """, (timestamp, zone_name, event_type, lat, lon))
        conn.commit()
        conn.close()

        print(f"📍 [BACKEND] Geofence Event: {event_type} - {zone_name} at ({lat}, {lon})")
        return jsonify({"status": "success", "logged": True}), 201
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route('/api/sync', methods=['POST'])
def batch_sync():
    """Batch synchronization endpoint for offline events and telemetry."""
    data = request.json or {}
    events = data.get("emergency_events", [])
    geofence_events = data.get("geofence_events", [])

    synced_events = 0
    synced_geofence = 0

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        for ev in events:
            cursor.execute("""
                INSERT OR REPLACE INTO emergency_events 
                (event_id, timestamp, threat_type, latitude, longitude, maps_link, audio_filename, contacts_notified, call_status, sms_status, sync_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SYNCED')
            """, (
                ev.get("event_id"),
                ev.get("timestamp"),
                ev.get("threat_type"),
                ev.get("latitude"),
                ev.get("longitude"),
                ev.get("maps_link"),
                ev.get("audio_filename", ""),
                json.dumps(ev.get("contacts_notified", [])),
                ev.get("call_status", "UNKNOWN"),
                ev.get("sms_status", "UNKNOWN")
            ))
            synced_events += 1

        for gf in geofence_events:
            cursor.execute("""
                INSERT INTO geofence_events (timestamp, zone_name, event_type, latitude, longitude)
                VALUES (?, ?, ?, ?, ?)
            """, (
                gf.get("timestamp"),
                gf.get("zone_name"),
                gf.get("event_type"),
                gf.get("latitude"),
                gf.get("longitude")
            ))
            synced_geofence += 1

        conn.commit()
        conn.close()

        print(f"🔄 [BACKEND SYNC] Synchronized {synced_events} events and {synced_geofence} geofence records.")
        return jsonify({
            "status": "success",
            "synced_events": synced_events,
            "synced_geofence": synced_geofence
        })
    except Exception as exc:
        print(f"[Backend Sync Error]: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route('/api/db/reset', methods=['POST'])
def reset_database():
    """Resets backend database tables."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for tbl in ['emergency_events', 'audio_evidence', 'geofence_events', 'location_history', 'battery_logs']:
            cursor.execute(f"DELETE FROM {tbl}")
        conn.commit()
        cursor.execute("VACUUM")
        conn.close()
        print("🗑️ [BACKEND] Database reset requested and executed.")
        return jsonify({"status": "success", "message": "All backend database tables have been reset."})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


# ── Audio & Video Evidence Management Endpoints ──────────────────────────────
@app.route('/api/recordings', methods=['GET'])
def list_backend_recordings():
    """Lists audio and video evidence stored on backend."""
    try:
        recordings = []
        if os.path.exists(BACKEND_AUDIO_DIR):
            for fname in os.listdir(BACKEND_AUDIO_DIR):
                fpath = os.path.join(BACKEND_AUDIO_DIR, fname)
                if os.path.isfile(fpath):
                    stat = os.stat(fpath)
                    recordings.append({
                        "type": "audio",
                        "filename": fname,
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })

        backend_video_dir = os.path.join(BACKEND_STORAGE_DIR, "video")
        if os.path.exists(backend_video_dir):
            for fname in os.listdir(backend_video_dir):
                fpath = os.path.join(backend_video_dir, fname)
                if os.path.isfile(fpath):
                    stat = os.stat(fpath)
                    recordings.append({
                        "type": "video",
                        "filename": fname,
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })

        return jsonify({"status": "success", "count": len(recordings), "recordings": recordings})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route('/api/recordings/<media_type>/<filename>', methods=['DELETE'])
def delete_backend_recording(media_type, filename):
    """Deletes a specific audio or video evidence file from backend storage."""
    safe_name = os.path.basename(filename)
    if media_type == "audio":
        target_dir = BACKEND_AUDIO_DIR
    elif media_type == "video":
        target_dir = os.path.join(BACKEND_STORAGE_DIR, "video")
    else:
        return jsonify({"status": "error", "message": f"Unsupported media type '{media_type}'"}), 400

    target_path = os.path.join(target_dir, safe_name)
    deleted = False
    if os.path.exists(target_path):
        try:
            os.remove(target_path)
            deleted = True
        except Exception as exc:
            return jsonify({"status": "error", "message": f"Could not delete file: {exc}"}), 500

    # Also clean SQLite audio_evidence and clear reference in emergency_events
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM audio_evidence WHERE filename = ?", (safe_name,))
        cursor.execute("UPDATE emergency_events SET audio_filename = '' WHERE audio_filename = ?", (safe_name,))
        conn.commit()
        conn.close()
    except Exception:
        pass

    return jsonify({"status": "success", "media_type": media_type, "filename": safe_name, "deleted": deleted})


@app.route('/api/recordings/all', methods=['DELETE'])
def delete_all_backend_recordings():
    """Deletes all recordings of specified type ('audio', 'video', or 'all') from backend storage."""
    media_type = request.args.get('type', 'all').lower()
    deleted_count = 0

    dirs_to_clean = []
    if media_type in ('audio', 'all') and os.path.exists(BACKEND_AUDIO_DIR):
        dirs_to_clean.append(BACKEND_AUDIO_DIR)
    if media_type in ('video', 'all'):
        video_dir = os.path.join(BACKEND_STORAGE_DIR, 'video')
        if os.path.exists(video_dir):
            dirs_to_clean.append(video_dir)

    for d in dirs_to_clean:
        for fname in os.listdir(d):
            fp = os.path.join(d, fname)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                    deleted_count += 1
                except Exception:
                    pass

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if media_type in ('audio', 'all'):
            cursor.execute("DELETE FROM audio_evidence")
            cursor.execute("UPDATE emergency_events SET audio_filename = ''")
        conn.commit()
        conn.close()
    except Exception:
        pass

    print(f"🗑️ [BACKEND] Deleted {deleted_count} {media_type} recordings.")
    return jsonify({"status": "success", "deleted_count": deleted_count, "media_type": media_type})



if __name__ == '__main__':
    print("🚀 Safety Backend Engine Running with SQLite Storage on Port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False)