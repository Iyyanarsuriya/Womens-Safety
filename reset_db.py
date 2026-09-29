#!/usr/bin/env python3
"""
Utility script to reset the Safety System database and media vaults.
Usage:
    python reset_db.py          # Resets all SQLite tables in data/backend_safety.db
    python reset_db.py --all    # Resets SQLite DB + cached offline JSON vaults
    python reset_db.py --fresh  # Completely wipes DB, cached vaults, logs, and sample audios/videos
"""
import os
import sys
import glob
import sqlite3
import json

# Ensure safe stdout encoding on Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DATA_DIR = "data"
DB_PATH = os.path.join(DATA_DIR, "backend_safety.db")

def reset_sqlite_db():
    if not os.path.exists(DB_PATH):
        print(f"[INFO] Database file not found at {DB_PATH}. Initializing schema...")
        from app import init_db
        init_db()
        print("[SUCCESS] Initialized empty database.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    tables = [
        "emergency_events",
        "audio_evidence",
        "geofence_events",
        "location_history",
        "battery_logs"
    ]
    for tbl in tables:
        try:
            cursor.execute(f"DELETE FROM {tbl}")
            print(f"  - Cleared table: {tbl}")
        except sqlite3.OperationalError as e:
            print(f"  - Table {tbl} notice: {e}")

    conn.commit()
    cursor.execute("VACUUM")
    conn.close()
    print("[SUCCESS] Database vacuumed and reset successfully.")

def reset_cached_vaults():
    vault_file = os.path.join(DATA_DIR, "offline_events_vault.json")
    try:
        with open(vault_file, "w", encoding="utf-8") as fp:
            fp.write(json.dumps({"emergency_events": [], "audio_queue": [], "geofence_events": []}, indent=2))
        print(f"  - Reset offline vault: {vault_file}")
    except Exception as e:
        print(f"  - Failed to reset {vault_file}: {e}")

    list_files = [
        os.path.join(DATA_DIR, "location_history.json"),
        os.path.join(DATA_DIR, "past_locations.json"),
        "blackbox_vault.json",
    ]
    for f in list_files:
        try:
            with open(f, "w", encoding="utf-8") as fp:
                fp.write("[]\n")
            print(f"  - Reset JSON file: {f}")
        except Exception as e:
            print(f"  - Failed to reset {f}: {e}")

    loc_csv = os.path.join(DATA_DIR, "location_log.csv")
    try:
        with open(loc_csv, "w", encoding="utf-8") as fp:
            fp.write("timestamp,latitude,longitude,speed_kmh,status\n")
        print(f"  - Reset location log: {loc_csv}")
    except Exception as e:
        print(f"  - Failed to reset {loc_csv}: {e}")

def remove_media_files():
    patterns = [
        os.path.join("recordings", "audio", "*.*"),
        os.path.join("recordings", "video", "*.*"),
        os.path.join("data", "backend_storage", "audio", "*.*"),
    ]
    deleted_count = 0
    for pat in patterns:
        for f in glob.glob(pat):
            try:
                os.remove(f)
                deleted_count += 1
            except Exception as e:
                print(f"  - Could not delete {f}: {e}")
    print(f"[SUCCESS] Removed {deleted_count} sample audio and video recordings.")

def clear_logs():
    for log_name in ["app_system.log", "acoustic_log.txt"]:
        if os.path.exists(log_name):
            try:
                with open(log_name, "w", encoding="utf-8") as fp:
                    fp.write("")
                print(f"  - Cleared log: {log_name}")
            except Exception as e:
                print(f"  - Could not clear {log_name}: {e}")

if __name__ == "__main__":
    is_fresh = "--fresh" in sys.argv
    is_all = "--all" in sys.argv or is_fresh

    print("[RESET] Resetting Safety System Database...")
    reset_sqlite_db()

    if is_all:
        print("[RESET] Resetting cached vaults...")
        reset_cached_vaults()

    if is_fresh:
        print("[RESET] Removing all sample audios and videos...")
        remove_media_files()
        clear_logs()

    if is_fresh or "--profile" in sys.argv:
        prof_file = os.path.join(DATA_DIR, "user_profile.json")
        if os.path.exists(prof_file):
            try:
                os.remove(prof_file)
                print(f"[RESET] Removed user profile: {prof_file} (initial setup screen restored)")
            except Exception as e:
                print(f"[NOTICE] Could not remove {prof_file}: {e}")

    print("[DONE] Everything requested has been reset fresh.")
