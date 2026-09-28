import os
import json
import time
import asyncio
import threading
import subprocess
import tkinter as tk
from datetime import datetime
from cryptography.fernet import Fernet
from bleak import BleakScanner, BleakClient

from location_module import OfflineLocationEngine
from prediction_module import LSTMTrajectoryPredictor
from anomaly_engine import TrajectoryAnomalyEngine
from sensor_module import SystemSensorDiagnostics
from acoustic_module import OfflineAcousticEngine
from network_monitor_module import NetworkMonitor
from fall_detector import start_detection
from gps_bridge_module import GPSBridge
from sync_manager import SyncManager
from android_telephony_module import AndroidTelephonyManager
from macrodroid_dispatch_module import trigger_aura_sos


class MainSafetyController:
    def __init__(self, emergency_contacts=None, real_pin="1234", fake_pin="9999"):
        self.emergency_contacts = emergency_contacts if emergency_contacts else []
        self.real_pin = real_pin
        self.fake_pin = fake_pin
        self._load_dynamic_profile()

        # System Core Engines
        self.location_engine = OfflineLocationEngine()
        self.predictor = LSTMTrajectoryPredictor(sequence_length=8)
        self.anomaly_engine = TrajectoryAnomalyEngine()
        self.sensor_diagnostics = SystemSensorDiagnostics(battery_threshold=15)
        self.acoustic_engine = OfflineAcousticEngine(trigger_callback=self.voice_trigger_callback)
        self.telephony_manager = AndroidTelephonyManager()

        # Offline Synchronization Manager
        self.sync_manager = SyncManager()
        self.sync_manager.start()

        # GPS Bridge for real mobile phone location stream over TCP (port 8082)
        self.gps_bridge = GPSBridge(self)
        try:
            self.gps_bridge.start()
        except Exception as e:
            print(f"[GPS Bridge] Startup notice: {e}")

        # Network Monitor
        self.network_monitor = NetworkMonitor(self)

        # GUI Reference Link
        self.gui_app = None

        # System State
        self.system_status = "ACTIVE_MONITORING"
        self.stealth_active = False
        self.previous_loc = self.location_engine.get_current_location()
        self.phone_has_signal = True

        # Safe Zones (synchronized with location_engine's geofence manager)
        self.safe_zones = self.location_engine.geofence_manager.safe_zones

        # Encryption & Local Vault
        self.vault_key_path = "vault.key"
        self.cipher = self._init_encryption_key()
        self.blackbox_file = "blackbox_vault.json"

        # Fall Detector Engine
        self.fall_detector = start_detection(callback_function=self.on_fall_detected)

    def attach_gui(self, gui_app):
        self.gui_app = gui_app
        if hasattr(self, 'network_monitor') and self.network_monitor:
            self.network_monitor.gui_app = gui_app
            self.network_monitor.start()

    def on_fall_detected(self):
        """Callback fired directly from fall_detector.py's background thread."""
        print("\n🚨 [MainController] Fall Event Signal Received!")
        if self.gui_app and hasattr(self.gui_app, 'root'):
            self.gui_app.root.after(0, lambda: self.gui_app.trigger_threat("💥 HARD FALL / DROP DETECTED"))
        else:
            loc = self.location_engine.get_current_location()
            self.execute_emergency_sequence("FALL_DETECTED", loc)

    def start_emergency_recording(self):
        """Called by GUI or threat activation to record 15s audio & video."""
        current_loc = self.location_engine.get_current_location()
        try:
            self.acoustic_engine.record_emergency_audio(duration_seconds=15)
            self.acoustic_engine.record_emergency_video(duration_seconds=15)
        except Exception as e:
            print(f"[Recording Error] {e}")
        self.log_blackbox_event(current_loc["latitude"], current_loc["longitude"], "RECORDING_STARTED")

        # Schedule check to queue recorded audio in SyncManager once finished
        def _queue_audio_when_ready():
            time.sleep(16)
            audio_dir = self.acoustic_engine.audio_dir
            if os.path.exists(audio_dir):
                files = sorted(
                    [os.path.join(audio_dir, f) for f in os.listdir(audio_dir) if f.endswith(".wav")],
                    key=os.path.getmtime,
                    reverse=True
                )
                if files:
                    latest = files[0]
                    self.sync_manager.queue_audio_file(latest, event_id=f"EV_{int(time.time())}")

        threading.Thread(target=_queue_audio_when_ready, daemon=True).start()

    # --- BLEAK ASYNC DISPATCHER ---
    def send_bluetooth_alert(self, contact_number, maps_link):
        print(f"[Bluetooth Dispatch] Initializing BLE Scan for {contact_number}...")

        async def ble_task():
            try:
                devices = await BleakScanner.discover(timeout=3.0)
                for device in devices:
                    if "AURA_MOBILE" in str(device.name):
                        async with BleakClient(device.address) as client:
                            payload = f"SOS:{contact_number}:{maps_link}".encode('utf-8')
                            print(f"[Bluetooth Dispatch] Packet sent successfully to {device.name}")
                        break
            except Exception as e:
                print(f"[Bluetooth Error] Bleak transmission failed: {e}")

        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(ble_task())
            loop.close()

        threading.Thread(target=run_loop, daemon=True).start()

    def process_incoming_bluetooth_command(self, bluetooth_packet):
        phone_bat = bluetooth_packet.get("phone_battery", 100)
        accel_data = bluetooth_packet.get("accelerometer", None)
        is_fall = bluetooth_packet.get("fall_detected", False)

        self.sensor_diagnostics.update_mobile_sensor_telemetry(phone_bat, accel_data, is_fall)
        if is_fall:
            current_loc = self.location_engine.get_current_location()
            self.execute_emergency_sequence("MOBILE_FALL_DETECTED", current_loc)

    # --- ENCRYPTION & BLACKBOX LOGGING ---
    def _init_encryption_key(self):
        if not os.path.exists(self.vault_key_path):
            key = Fernet.generate_key()
            with open(self.vault_key_path, "wb") as kf:
                kf.write(key)
        else:
            with open(self.vault_key_path, "rb") as kf:
                key = kf.read()
        return Fernet(key)

    def log_blackbox_event(self, lat, lon, event_type):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "latitude": lat,
            "longitude": lon,
            "event": event_type,
            "status": self.system_status
        }
        logs = []
        if os.path.exists(self.blackbox_file):
            try:
                with open(self.blackbox_file, "r") as f:
                    logs = json.load(f)
            except Exception:
                logs = []
        logs.append(entry)
        with open(self.blackbox_file, "w") as f:
            json.dump(logs, f, indent=2)

    # --- DURESS & STEALTH ENGINE ---
    def verify_duress_pin(self, entered_pin, gui_root=None):
        if entered_pin == self.real_pin:
            self.system_status = "DEACTIVATED"
            print("[Security] System disarmed gracefully.")
            return "SUCCESS_DISABLE"
        elif entered_pin == self.fake_pin:
            print("[Security] DURESS PIN DETECTED! Triggering Stealth Alarm...")
            self.enable_stealth_lock(gui_root)
            loc = self.location_engine.get_current_location()
            self.execute_emergency_sequence("DURESS_FAKE_PIN_TRIGGER", loc)
            return "FAKE_DISABLE_ACTIVE"
        return "INVALID_PIN"

    def enable_stealth_lock(self, root_window):
        self.stealth_active = True
        if root_window:
            root_window.attributes("-fullscreen", True)
            root_window.configure(bg="#000000")
            root_window.config(cursor="none")
            for widget in root_window.winfo_children():
                widget.pack_forget() if hasattr(widget, 'pack_forget') else widget.grid_forget()

    def _load_dynamic_profile(self):
        profile_path = os.path.join("data", "user_profile.json")
        if os.path.exists(profile_path):
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    p = json.load(f)
                    if not self.emergency_contacts:
                        self.emergency_contacts = [c["phone"] for c in p.get("contacts", []) if "phone" in c]
                    if "real_pin" in p and p["real_pin"]:
                        self.real_pin = str(p["real_pin"]).strip()
                    if "fake_pin" in p and p["fake_pin"]:
                        self.fake_pin = str(p["fake_pin"]).strip()
            except Exception as e:
                print(f"[MainController Profile Load Notice] {e}")

    def set_pins(self, real_pin, fake_pin):
        if real_pin:
            self.real_pin = str(real_pin).strip()
        if fake_pin:
            self.fake_pin = str(fake_pin).strip()

    def set_emergency_contacts(self, contacts_list):
        if isinstance(contacts_list, list):
            self.emergency_contacts = contacts_list

    # --- GEOFENCING: Safe Zone Management ---
    def add_safe_zone(self, name, latitude, longitude, radius_km=0.5):
        self.location_engine.geofence_manager.add_safe_zone(name, latitude, longitude, radius_km)
        self.safe_zones = self.location_engine.geofence_manager.safe_zones

    def remove_safe_zone(self, index):
        self.location_engine.geofence_manager.remove_safe_zone(index)
        self.safe_zones = self.location_engine.geofence_manager.safe_zones

    def check_geofence(self, current_loc):
        return self.location_engine.geofence_manager.is_outside_all_zones(
            current_loc["latitude"], current_loc["longitude"]
        )

    def send_low_battery_notice(self, percent, location_data):
        lat = location_data.get("latitude", 0.0)
        lon = location_data.get("longitude", 0.0)
        maps_link = f"https://maps.google.com/?q={lat},{lon}"

        if self.emergency_contacts:
            primary_contact = self.emergency_contacts[0]
            trigger_aura_sos(primary_contact, "", lat, lon)

        self.log_blackbox_event(lat, lon, f"LOW_BATTERY_NOTICE_{percent}PCT")

    def voice_trigger_callback(self, status, word):
        if status == "TRIGGER":
            if self.gui_app:
                self.gui_app.root.after(0, lambda: self.gui_app.trigger_threat(f"VOICE COMMAND ({word.upper()})"))
            else:
                current_loc = self.location_engine.get_current_location()
                self.execute_emergency_sequence(f"VOICE_EMERGENCY_{word.upper()}", current_loc)

    # ── COMPLETE EMERGENCY EXECUTION ─────────────────────────────────────────

    def execute_emergency_sequence(self, threat_type, location_data):
        """
        Executes full offline-first emergency sequence:
          1. Activates emergency state & blackbox record.
          2. Sounds loud audible alarm/siren.
          3. Obtains verified GPS / last-known location & builds Google Maps link.
          4. Dispatches SMS to configured guardians.
          5. Handles priority-based emergency calls (P1 then P2) according to Android restrictions.
          6. Records audio evidence.
          7. Queues event in SyncManager for offline storage & backend synchronization.
        """
        self.system_status = "EMERGENCY_TRIGGERED"
        lat = location_data.get("latitude", 0.0)
        lon = location_data.get("longitude", 0.0)
        maps_link = f"https://maps.google.com/?q={lat},{lon}"

        self.log_blackbox_event(lat, lon, threat_type)

        # 1. Loud Siren / Alarm
        if not self.stealth_active:
            force_siren = not self.phone_has_signal
            self.acoustic_engine.play_emergency_siren(duration_cycles=3, force=force_siren)

        # 2. Audio recording
        self.start_emergency_recording()

        primary_contact = self.emergency_contacts[0] if self.emergency_contacts else ""
        secondary_contact = self.emergency_contacts[1] if len(self.emergency_contacts) > 1 else ""

        # 3. Priority-based calling adhering to Android restrictions
        call_results = self.telephony_manager.place_priority_emergency_call(primary_contact, secondary_contact)

        # 4. SMS Dispatch
        sms_msg = f"EMERGENCY SOS ALERT! Threat: {threat_type}. Location: {maps_link}"
        sms_results = self.telephony_manager.dispatch_emergency_sms(
            primary_contact, secondary_contact, sms_msg, lat, lon
        )

        # 5. Bluetooth broadcast
        if primary_contact:
            self.send_bluetooth_alert(primary_contact, maps_link)

        # 6. Queue in offline-first SyncManager for backend persistence
        event_payload = {
            "event_id": f"EV_{int(time.time() * 1000)}",
            "timestamp": datetime.now().isoformat(),
            "threat_type": threat_type,
            "latitude": lat,
            "longitude": lon,
            "maps_link": maps_link,
            "contacts_notified": self.emergency_contacts,
            "call_status": f"P1:{call_results.get('p1_status')}, P2:{call_results.get('p2_status')}",
            "sms_status": str(sms_results)
        }
        self.sync_manager.queue_emergency_event(event_payload)

        return event_payload

    def run_live_safety_cycle(self, simulated_lat=None, simulated_lon=None, simulated_timestamp=None):
        """Performs a periodic safety inspection cycle."""
        current_loc = self.location_engine.get_current_location()
        if simulated_lat is not None and simulated_lon is not None:
            current_loc = {
                "latitude": simulated_lat,
                "longitude": simulated_lon,
                "timestamp": simulated_timestamp if simulated_timestamp is not None else current_loc.get("timestamp")
            }

        current_lat = current_loc["latitude"]
        current_lon = current_loc["longitude"]

        # LSTM / Cluster prediction update
        self.predictor.update_history(current_lat, current_lon)
        predicted_point = self.predictor.predict_next_coordinate()

        # Route & Anomaly evaluation
        anomaly_res = self.anomaly_engine.evaluate_telemetry(current_loc, self.previous_loc)
        if isinstance(anomaly_res, tuple):
            is_threat, threat_type = anomaly_res[0], anomaly_res[1] if len(anomaly_res) > 1 else "ANOMALY_DETECTED"
        else:
            is_threat, threat_type = False, "NORMAL"

        speed_kmh = self.location_engine.calculate_speed(self.previous_loc, current_loc)
        self.previous_loc = current_loc

        # Geofence Transitions Check (Entry & Exit events)
        transitions = self.location_engine.geofence_manager.evaluate_transitions(current_lat, current_lon)
        for t in transitions:
            self.sync_manager.queue_geofence_event(t["zone_name"], t["event"], t["latitude"], t["longitude"])
            if t["event"] == "EXIT":
                is_threat, threat_type = True, f"GEOFENCE_BREACH ({t['zone_name']})"
            elif t["event"] == "ENTRY" and self.gui_app:
                self.gui_app.send_desktop_popup("✅ Safe Zone Entered", f"Entered {t['zone_name']}")

        diag = self.sensor_diagnostics.run_full_diagnostics()

        if is_threat:
            if self.gui_app:
                self.gui_app.root.after(0, lambda: self.gui_app.trigger_threat(f"⚠️ {threat_type}"))
            else:
                self.execute_emergency_sequence(threat_type, current_loc)

        if self.gui_app and hasattr(self.gui_app, "update_map_canvas"):
            self.gui_app.root.after(
                0,
                lambda: self.gui_app.update_map_canvas(
                    current_lat, current_lon, predicted_point, speed_kmh, is_threat
                )
            )

        return {
            "status": self.system_status,
            "current_location": (current_lat, current_lon),
            "predicted_next": predicted_point,
            "anomaly_check": {"is_threat": is_threat, "threat_type": threat_type},
            "system_health": diag["diagnostic_status"]
        }

    def stop_all(self):
        """Clean shutdown of all engines and threads."""
        try:
            if hasattr(self, 'fall_detector'):
                self.fall_detector.stop()
            if hasattr(self, 'network_monitor'):
                self.network_monitor.stop()
            if hasattr(self, 'gps_bridge'):
                self.gps_bridge.stop()
            if hasattr(self, 'sync_manager'):
                self.sync_manager.stop()
            if hasattr(self, 'acoustic_engine'):
                self.acoustic_engine.stop_listening()
        except Exception as e:
            print(f"[Shutdown Notice]: {e}")