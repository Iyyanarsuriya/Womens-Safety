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
from gui_module import ModernSafetyApp
from network_monitor_module import NetworkMonitor
from fall_detector import start_detection
from macrodroid_dispatch_module import trigger_aura_sos


class MainSafetyController:
    def __init__(self, emergency_contacts=None, real_pin="1234", fake_pin="9999"):
        self.emergency_contacts = emergency_contacts if emergency_contacts else []
        self.real_pin = real_pin
        self.fake_pin = fake_pin

        # System Core Engines
        self.location_engine = OfflineLocationEngine()
        self.predictor = LSTMTrajectoryPredictor(sequence_length=5)
        self.anomaly_engine = TrajectoryAnomalyEngine()
        self.sensor_diagnostics = SystemSensorDiagnostics(battery_threshold=15)
        self.acoustic_engine = OfflineAcousticEngine(trigger_callback=self.voice_trigger_callback)

        # 🔧 FIX: NetworkMonitor needs a `controller` reference to report back
        # to (it was being constructed with no arguments before, which crashes
        # immediately). gui_app is attached later in attach_gui().
        self.network_monitor = NetworkMonitor(self)

        # GUI Reference Link
        self.gui_app = None

        # System State
        self.system_status = "ACTIVE_MONITORING"
        self.stealth_active = False
        self.previous_loc = self.location_engine.get_current_location()

        # 🔧 Phone's real cellular signal status (updated by NetworkMonitor).
        self.phone_has_signal = True

        # 🔧 FIX: This was accidentally set to a list of PLACE NAMES
        # (["Home", "Office/College"]) - that's the old GUI-only display
        # list. Geofencing needs a list of ZONE DICTS with coordinates and
        # radius, built via add_safe_zone(). Starts empty = geofencing off
        # until the user adds a zone from Settings.
        self.safe_zones = []

        # Encryption & Local Vault
        self.vault_key_path = "vault.key"
        self.cipher = self._init_encryption_key()
        self.blackbox_file = "blackbox_vault.json"

        # Start Fall Detector automatically - works even before the GUI
        # exists, thanks to the None-check inside on_fall_detected().
        self.fall_detector = start_detection(callback_function=self.on_fall_detected)

    def attach_gui(self, gui_app):
        self.gui_app = gui_app

        # Now that the GUI exists, give the network monitor a reference to
        # it (so it can update the live signal label) and start polling.
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
        """Called by GUI the moment a threat is triggered."""
        current_loc = self.location_engine.get_current_location()
        try:
            self.acoustic_engine.record_emergency_audio(duration_seconds=15)
            self.acoustic_engine.record_emergency_video(duration_seconds=15)
        except Exception as e:
            print(f"[Recording Error] {e}")
        self.log_blackbox_event(current_loc["latitude"], current_loc["longitude"], "RECORDING_STARTED")

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

    def encrypt_vault_evidence(self, file_path):
        if os.path.exists(file_path) and not file_path.endswith(".enc"):
            try:
                with open(file_path, "rb") as f:
                    raw_data = f.read()
                encrypted_data = self.cipher.encrypt(raw_data)
                enc_path = file_path + ".enc"
                with open(enc_path, "wb") as ef:
                    ef.write(encrypted_data)
                os.remove(file_path)
                print(f"[Evidence Vault] Encrypted: {enc_path}")
            except Exception as e:
                print(f"[Vault Error] Encryption failed: {e}")

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

    # --- DISPATCH & TELEMETRY ---
    def trigger_auto_call(self, contact_number):
        def call_worker():
            time.sleep(2)
            try:
                cmd = f"adb shell am start -a android.intent.action.CALL -d tel:{contact_number}"
                subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"[AutoCall Error] {e}")

        threading.Thread(target=call_worker, daemon=True).start()

    def set_emergency_contacts(self, contacts_list):
        if isinstance(contacts_list, list):
            self.emergency_contacts = contacts_list

    # --- GEOFENCING: Safe Zone Management ---
    def add_safe_zone(self, name, latitude, longitude, radius_km=0.5):
        self.safe_zones.append({
            "name": name, "latitude": latitude, "longitude": longitude, "radius_km": radius_km
        })

    def remove_safe_zone(self, index):
        if 0 <= index < len(self.safe_zones):
            self.safe_zones.pop(index)

    def check_geofence(self, current_loc):
        """Returns True if current_loc is OUTSIDE every defined safe zone.
        Empty self.safe_zones = geofencing disabled (always returns False)."""
        if not self.safe_zones:
            return False
        for zone in self.safe_zones:
            distance_km = self.location_engine.haversine_distance(
                current_loc["latitude"], current_loc["longitude"],
                zone["latitude"], zone["longitude"]
            )
            if distance_km <= zone["radius_km"]:
                return False
        return True

    def send_low_battery_notice(self, percent, location_data):
        """
        🔧 Lightweight battery-low handler: sends ONE informational SMS
        (battery % + location link) to the primary contact. Deliberately
        does NOT call execute_emergency_sequence() - no siren, no auto-call,
        no full threat escalation. A low battery is a precaution to flag,
        not a confirmed emergency.
        """
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

    def execute_emergency_sequence(self, threat_type, location_data):
        self.system_status = "EMERGENCY_TRIGGERED"
        lat = location_data.get("latitude", 0.0)
        lon = location_data.get("longitude", 0.0)
        maps_link = f"https://maps.google.com/?q={lat},{lon}"

        self.log_blackbox_event(lat, lon, threat_type)

        if not self.stealth_active:
            # If the connected phone has NO cellular signal, force the
            # high-decibel siren regardless of the laptop's own network.
            force_siren = not self.phone_has_signal
            self.acoustic_engine.play_emergency_siren(duration_cycles=3, force=force_siren)

        if self.emergency_contacts:
            primary_contact = self.emergency_contacts[0]
            secondary_contact = self.emergency_contacts[1] if len(self.emergency_contacts) > 1 else None
            self.send_bluetooth_alert(primary_contact, maps_link)

            # 🔧 Real SMS + escalating calls (P1 -> wait -> call P1 ->
            # if unanswered -> call P2) via the MacroDroid macro. This
            # replaces the separate Termux-SMS and adb-call paths so the
            # demo doesn't fire duplicate/conflicting real-world actions.
            trigger_aura_sos(primary_contact, secondary_contact, lat, lon)

    def run_live_safety_cycle(self, simulated_lat=None, simulated_lon=None, simulated_timestamp=None):
        current_loc = self.location_engine.get_current_location()
        if simulated_lat is not None and simulated_lon is not None:
            current_loc = {"latitude": simulated_lat, "longitude": simulated_lon,
                           "timestamp": simulated_timestamp if simulated_timestamp is not None else current_loc.get("timestamp")}

        current_lat = current_loc["latitude"]
        current_lon = current_loc["longitude"]

        self.predictor.update_history(current_lat, current_lon)
        predicted_point = self.predictor.predict_next_coordinate()

        anomaly_res = self.anomaly_engine.evaluate_telemetry(current_loc, self.previous_loc)

        if isinstance(anomaly_res, tuple):
            is_threat, threat_type = anomaly_res[0], anomaly_res[1] if len(anomaly_res) > 1 else "ANOMALY_DETECTED"
        elif isinstance(anomaly_res, dict):
            is_threat = anomaly_res.get("is_threat", False)
            threat_type = anomaly_res.get("threat_type", "ANOMALY_DETECTED")
        else:
            is_threat, threat_type = False, "NORMAL"

        # Live speed (km/h) - computed BEFORE previous_loc is overwritten,
        # so the dashboard's map display can show it in real time.
        speed_kmh = self.location_engine.calculate_speed(self.previous_loc, current_loc)

        self.previous_loc = current_loc

        # GEOFENCING: outside every defined safe zone = breach.
        if self.check_geofence(current_loc) and not is_threat:
            is_threat, threat_type = True, "GEOFENCE_BREACH"

        diag = self.sensor_diagnostics.run_full_diagnostics()

        if is_threat:
            if self.gui_app:
                # 🔧 FIX: Show the interactive "are you safe?" countdown
                # FIRST, matching Feature #4's spec, instead of dispatching
                # SMS/calls/siren immediately on every anomaly. Real
                # dispatch now only happens if the countdown is not
                # dismissed in time (handled by gui_app.dispatch_sos()).
                self.gui_app.root.after(0, lambda: self.gui_app.trigger_threat(f"⚠️ {threat_type}"))
            else:
                # No GUI attached (headless/testing) - dispatch immediately.
                self.execute_emergency_sequence(threat_type, current_loc)

        # Push this reading to the dashboard's persistent map display
        # (red dot + path + predicted point + speed) without blocking or
        # freezing the GUI.
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


# --- SYSTEM LAUNCHER ---
if __name__ == "__main__":
    controller = MainSafetyController(real_pin="1234", fake_pin="9999")

    root = tk.Tk()
    app = ModernSafetyApp(root, controller=controller)
    controller.attach_gui(app)

    try:
        controller.acoustic_engine.start_listening()
        controller.acoustic_engine.set_setup_complete(True)
    except Exception as e:
        print(f"Acoustic startup warning: {e}")

    def on_closing():
        try:
            if hasattr(controller, 'fall_detector'):
                controller.fall_detector.stop()
            if hasattr(controller, 'network_monitor'):
                controller.network_monitor.stop()
            controller.acoustic_engine.stop_listening()
        except Exception:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()