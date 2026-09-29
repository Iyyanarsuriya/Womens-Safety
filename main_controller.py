import os
import json
import time
import asyncio
import threading
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


class CallEscalationManager:
    """Manages 1-2 minute response timeout and automated sequential priority calls."""
    def __init__(self, controller):
        self.controller = controller

    @property
    def timeout_s(self):
        return self.controller.call_escalation_timeout_sec

    @timeout_s.setter
    def timeout_s(self, val):
        self.controller.call_escalation_timeout_sec = max(60, min(120, int(val)))

    def set_timeout(self, val):
        self.timeout_s = val

    @property
    def escalation_active(self):
        return self.controller.call_escalation_status in ["WAITING_RESPONSE", "CALLING_IN_PROGRESS"]

    @property
    def escalation_state(self):
        return self.controller.call_escalation_status

    def start_escalation(self, contacts, incident_type="EMERGENCY"):
        self.controller.start_call_escalation(contacts, incident_type)

    def cancel_escalation(self, reason="User confirmed safe"):
        self.controller.cancel_call_escalation()
        self.controller.call_escalation_status = "RESOLVED_SAFE"


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

        # Trip Destination Management (persisted in data/current_trip.json)
        self.trip_file = os.path.join("data", "current_trip.json")
        self._load_trip_destination()

        # Demo Mode State (strictly isolated from real GPS)
        self.demo_mode_active = False
        self.demo_lat = None
        self.demo_lon = None
        self.demo_speed = 0.0

        # Display Only Mode (Show tracking & map visually only, no automated emergency actions)
        self.display_only_mode = True

        # Automated Call Escalation State
        self.call_escalation_timeout_sec = 60  # Configurable 60 - 120s
        self.call_escalation_thread = None
        self.call_escalation_cancel_event = threading.Event()
        self.call_escalation_remaining = 0
        self.call_escalation_status = "IDLE"
        self.escalation_manager = CallEscalationManager(self)

        # Battery warning state (Requirement 6: <=15% separate warning, no SOS, no loops)
        self.battery_warning_sent = False

        # Incident Debounce State
        self.last_sos_time = 0.0
        self.last_sos_payload = None

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

    # ── TRIP DESTINATION MANAGEMENT ──────────────────────────────────────────

    @property
    def trip_destination(self):
        return self.get_trip_destination()

    def _load_trip_destination(self):
        if os.path.exists(self.trip_file):
            try:
                with open(self.trip_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data and "latitude" in data and "longitude" in data:
                        self.anomaly_engine.set_destination(
                            data.get("name", "Saved Destination"),
                            data["latitude"],
                            data["longitude"]
                        )
                        print(f"🎯 [Destination] Restored trip destination: {data.get('name')} ({data['latitude']}, {data['longitude']})")
            except Exception as e:
                print(f"[Destination Load Notice] {e}")

    def set_trip_destination(self, name: str, latitude: float, longitude: float):
        os.makedirs("data", exist_ok=True)
        dest = {
            "name": str(name).strip() or "Destination",
            "latitude": float(latitude),
            "longitude": float(longitude),
            "created_at": datetime.now().isoformat()
        }
        try:
            with open(self.trip_file, "w", encoding="utf-8") as f:
                json.dump(dest, f, indent=2)
            self.anomaly_engine.set_destination(dest["name"], dest["latitude"], dest["longitude"])
            self.log_blackbox_event(dest["latitude"], dest["longitude"], "DESTINATION_SET", details=f"Target: {dest['name']}")
            print(f"🎯 [Destination] Saved new trip destination: {dest['name']}")
        except Exception as e:
            print(f"[Destination Save Error] {e}")
        return dest

    def get_trip_destination(self):
        return self.anomaly_engine.get_destination()

    def clear_trip_destination(self):
        self.anomaly_engine.clear_destination()
        if os.path.exists(self.trip_file):
            try:
                os.remove(self.trip_file)
            except Exception:
                pass
        self.log_blackbox_event(0.0, 0.0, "DESTINATION_CLEARED")
        print("🎯 [Destination] Cleared trip destination.")

    # ── ISOLATED DEMO MODE MANAGEMENT ────────────────────────────────────────

    def set_demo_mode(self, active: bool):
        self.demo_mode_active = bool(active)
        if self.demo_mode_active:
            print("🎮 [Demo Mode] ACTIVATED — Simulated movement isolated from real GPS.")
            self.log_blackbox_event(
                self.demo_lat or 0.0, self.demo_lon or 0.0,
                "DEMO_MODE_ACTIVATED", is_demo=True
            )
        else:
            print("🎮 [Demo Mode] DEACTIVATED — Reverted to real GPS sensor stream.")
            self.log_blackbox_event(
                0.0, 0.0, "DEMO_MODE_DEACTIVATED", is_demo=False
            )

    def start_demo_mode(self, start_lat=12.9716, start_lon=77.5946, speed_kmh=25.0):
        self.set_demo_mode(True)
        self.update_demo_position(start_lat, start_lon, speed_kmh)

    def step_demo_movement(self, d_lat=0.0005, d_lon=0.0005):
        if self.demo_lat is not None and self.demo_lon is not None:
            self.demo_lat += d_lat
            self.demo_lon += d_lon

    def stop_demo_mode(self):
        self.set_demo_mode(False)

    def update_demo_position(self, lat: float, lon: float, speed_kmh: float = 25.0):
        self.demo_lat = float(lat)
        self.demo_lon = float(lon)
        self.demo_speed = float(speed_kmh)

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

    def log_blackbox_event(self, *args, **kwargs):
        """
        Logs incidents and security state transitions into the blackbox vault.
        Accepts: (lat, lon, event_type, details=None, is_demo=None) OR
                 (event_type, location=None, details=None, is_demo=None)
        """
        lat = 0.0
        lon = 0.0
        event_type = "SAFETY_EVENT"
        details = kwargs.get("details", "")
        is_demo = kwargs.get("is_demo", None)

        if len(args) >= 3 and (isinstance(args[0], (int, float)) or isinstance(args[1], (int, float))):
            lat = float(args[0])
            lon = float(args[1])
            event_type = str(args[2])
            if len(args) > 3: details = args[3]
            if len(args) > 4: is_demo = args[4]
        elif len(args) >= 1 and isinstance(args[0], str):
            event_type = args[0]
            loc = kwargs.get("location")
            if loc and isinstance(loc, dict):
                lat = loc.get("latitude", 0.0)
                lon = loc.get("longitude", 0.0)
            elif len(args) >= 3:
                lat = float(args[1])
                lon = float(args[2])

        entry = {
            "timestamp": datetime.now().isoformat(),
            "latitude": round(float(lat), 6),
            "longitude": round(float(lon), 6),
            "event": event_type,
            "status": self.system_status,
            "details": details or "",
            "mode": "DEMO" if (is_demo if is_demo is not None else self.demo_mode_active) else "PRODUCTION"
        }
        logs = []
        if os.path.exists(self.blackbox_file):
            try:
                with open(self.blackbox_file, "r") as f:
                    logs = json.load(f)
            except Exception:
                logs = []
        logs.append(entry)
        # Keep last 500 entries
        if len(logs) > 500:
            logs = logs[-500:]
        try:
            with open(self.blackbox_file, "w") as f:
                json.dump(logs, f, indent=2)
        except Exception as e:
            print(f"[Blackbox Write Warning] {e}")

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
        if self.gui_app and hasattr(self.gui_app, "trigger_fake_shutdown"):
            self.gui_app.root.after(0, self.gui_app.trigger_fake_shutdown)
        elif root_window:
            root_window.attributes("-fullscreen", True)
            root_window.configure(bg="#000000")
            root_window.config(cursor="none")

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
                    if "escalation_timeout" in p:
                        self.call_escalation_timeout_sec = int(p["escalation_timeout"])
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

    # ── LOW BATTERY SEPARATE WARNING (NO SOS TRIGGER) ────────────────────────
    def send_low_battery_notice(self, battery_pct=None, location_data=None, percent=None):
        """
        Sends a separate Low Battery Warning SMS to saved emergency contacts.
        CRITICAL: Does NOT trigger SOS!
        """
        pct = battery_pct if battery_pct is not None else (percent if percent is not None else 15)
        if self.battery_warning_sent:
            return False

        if location_data is None:
            location_data = self.location_engine.get_current_location()

        lat = location_data.get("latitude", 0.0)
        lon = location_data.get("longitude", 0.0)

        self.battery_warning_sent = True
        print(f"🔋 [MainController] Dispatching Low Battery Warning ({pct}%) to contacts: {self.emergency_contacts}")
        sms_results = self.telephony_manager.send_low_battery_sms(
            self.emergency_contacts, pct, lat, lon
        )

        self.log_blackbox_event(lat, lon, f"LOW_BATTERY_NOTICE_{pct}PCT", details=str(sms_results))
        return True

    def reset_battery_warning_state(self):
        self.battery_warning_sent = False

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
          1. Enforces incident debounce to prevent duplicate SMS for same incident.
          2. Activates emergency state & blackbox record.
          3. Sounds loud audible alarm/siren.
          4. Obtains verified GPS / last-known location & builds Google Maps link.
          5. Immediately sends SMS containing: Threat message, current location coords, Google Maps link.
          6. Records audio/video evidence.
          7. Queues event in SyncManager for offline storage & backend synchronization.
          8. Starts 1–2 minute response timeout for automated call escalation.
        """
        now = time.time()
        # Incident debounce: do not duplicate identical emergency sequence within 30 seconds
        if (now - self.last_sos_time) < 30.0 and self.last_sos_payload:
            print(f"ℹ️ [EmergencySequence] Debouncing repeated trigger for threat '{threat_type}'. Returning None (duplicate suppressed).")
            return None

        self.last_sos_time = now
        self.system_status = "EMERGENCY_TRIGGERED"
        lat = location_data.get("latitude", 0.0)
        lon = location_data.get("longitude", 0.0)
        maps_link = f"https://maps.google.com/?q={lat:.6f},{lon:.6f}"

        self.log_blackbox_event(lat, lon, threat_type, details=f"Emergency activated: {threat_type}")

        # 1. Loud Siren / Alarm
        if not self.stealth_active:
            force_siren = not self.phone_has_signal
            self.acoustic_engine.play_emergency_siren(duration_cycles=3, force=force_siren)

        # 2. Audio recording
        self.start_emergency_recording()

        primary_contact = self.emergency_contacts[0] if self.emergency_contacts else ""
        secondary_contact = self.emergency_contacts[1] if len(self.emergency_contacts) > 1 else ""

        # 3. SMS Dispatch with current location coords and Google Maps link
        sms_msg = (
            f"EMERGENCY SOS ALERT! Threat: {threat_type}. "
            f"Current Location: Lat {lat:.6f}, Lon {lon:.6f}. "
            f"Google Maps Link: {maps_link}"
        )
        sms_results = self.telephony_manager.dispatch_emergency_sms(
            self.emergency_contacts, message=sms_msg, lat=lat, lon=lon
        )

        # 4. Bluetooth broadcast
        if primary_contact:
            self.send_bluetooth_alert(primary_contact, maps_link)

        # 5. Queue in offline-first SyncManager for backend persistence
        event_payload = {
            "event_id": f"EV_{int(time.time() * 1000)}",
            "timestamp": datetime.now().isoformat(),
            "threat_type": threat_type,
            "latitude": lat,
            "longitude": lon,
            "maps_link": maps_link,
            "contacts_notified": self.emergency_contacts,
            "call_status": "ESCALATION_PENDING_RESPONSE_TIMEOUT",
            "sms_status": str(sms_results)
        }
        self.sync_manager.queue_emergency_event(event_payload)
        self.last_sos_payload = event_payload

        # 6. Start Escalation to Automated Calls after 1–2 minute response timeout
        self.start_call_escalation(self.emergency_contacts, threat_type)

        return event_payload

    # ── CALL ESCALATION MANAGER (1-2 MINUTE RESPONSE TIMEOUT) ────────────────

    def start_call_escalation(self, contacts, threat_type):
        """Starts response timeout (1-2 minutes). If unanswered, sequentially calls saved contacts."""
        self.cancel_call_escalation()
        self.call_escalation_cancel_event.clear()
        self.call_escalation_remaining = self.call_escalation_timeout_sec
        self.call_escalation_status = "WAITING_RESPONSE"

        def _escalation_worker():
            print(f"⏱️ [Call Escalation] Started {self.call_escalation_timeout_sec}s response timeout before calling...")
            while self.call_escalation_remaining > 0 and not self.call_escalation_cancel_event.is_set():
                if self.gui_app and hasattr(self.gui_app, "update_escalation_state"):
                    try:
                        self.gui_app.root.after(
                            0, lambda r=self.call_escalation_remaining: self.gui_app.update_escalation_state(
                                f"📞 Escalating to calls in {r}s (Waiting for guardian response)"
                            )
                        )
                    except Exception:
                        pass
                time.sleep(1.0)
                self.call_escalation_remaining -= 1

            if self.call_escalation_cancel_event.is_set():
                self.call_escalation_status = "CANCELLED"
                print("✅ [Call Escalation] Cancelled (User confirmed safe or response recorded).")
                if self.gui_app and hasattr(self.gui_app, "update_escalation_state"):
                    try:
                        self.gui_app.root.after(0, lambda: self.gui_app.update_escalation_state("✅ Call Escalation Cancelled"))
                    except Exception:
                        pass
                return

            # Timeout expired! Initiate priority calls
            self.call_escalation_status = "CALLING_IN_PROGRESS"
            print("🚨 [Call Escalation] Response timeout expired! Initiating automated priority calls...")
            if self.gui_app and hasattr(self.gui_app, "update_escalation_state"):
                try:
                    self.gui_app.root.after(0, lambda: self.gui_app.update_escalation_state("🚨 Initiating Automated Priority Calls..."))
                except Exception:
                    pass

            call_res = self.telephony_manager.place_priority_emergency_call(*contacts)
            self.call_escalation_status = "CALLS_COMPLETED"
            self.log_blackbox_event(0.0, 0.0, "CALL_ESCALATION_EXECUTED", details=str(call_res))

            if self.gui_app and hasattr(self.gui_app, "update_escalation_state"):
                msg = f"📞 Call Escalation: P1={call_res.get('p1_status', 'N/A')}, P2={call_res.get('p2_status', 'N/A')}"
                try:
                    self.gui_app.root.after(0, lambda m=msg: self.gui_app.update_escalation_state(m))
                except Exception:
                    pass

        self.call_escalation_thread = threading.Thread(target=_escalation_worker, daemon=True)
        self.call_escalation_thread.start()

    def cancel_call_escalation(self):
        self.call_escalation_cancel_event.set()
        self.call_escalation_status = "CANCELLED"

    def acknowledge_user_safe(self, cooldown_seconds=90.0):
        """Called when user confirms safety (e.g. dismissing alarm / PIN entry)."""
        now = time.time()
        self.system_status = "ACTIVE_MONITORING"
        self.last_sos_time = now
        self.cancel_call_escalation()
        if hasattr(self, "anomaly_engine"):
            self.anomaly_engine.acknowledge_safe(threat_type="ALL", cooldown_seconds=cooldown_seconds)
        self.log_blackbox_event(0.0, 0.0, "USER_SAFE_CONFIRMED", details="User confirmed safe; alarms & cooldowns reset.")
        print("🛡️ [SafetyController] User confirmed safe. Status set to ACTIVE_MONITORING; 90s cooldown active.")

    # ── PERIODIC SAFETY INSPECTION CYCLE ─────────────────────────────────────

    def run_live_safety_cycle(self, simulated_lat=None, simulated_lon=None, simulated_timestamp=None):
        """Performs a periodic safety inspection cycle."""
        # Check if in Demo Mode
        if self.demo_mode_active and self.demo_lat is not None and self.demo_lon is not None:
            current_loc = {
                "latitude": self.demo_lat,
                "longitude": self.demo_lon,
                "timestamp": simulated_timestamp if simulated_timestamp is not None else time.time(),
                "maps_url": f"https://maps.google.com/?q={self.demo_lat:.6f},{self.demo_lon:.6f}"
            }
        else:
            current_loc = self.location_engine.get_current_location()
            if simulated_lat is not None and simulated_lon is not None:
                current_loc = {
                    "latitude": simulated_lat,
                    "longitude": simulated_lon,
                    "timestamp": simulated_timestamp if simulated_timestamp is not None else current_loc.get("timestamp"),
                    "maps_url": f"https://maps.google.com/?q={simulated_lat:.6f},{simulated_lon:.6f}"
                }

        current_lat = current_loc["latitude"]
        current_lon = current_loc["longitude"]

        # LSTM / Cluster prediction update
        self.predictor.update_history(current_lat, current_lon)
        predicted_point = self.predictor.predict_next_coordinate()

        # Route & Anomaly evaluation
        anomaly_res = self.anomaly_engine.evaluate_telemetry(
            current_loc, self.previous_loc, external_predicted_loc=predicted_point
        )
        if isinstance(anomaly_res, tuple):
            is_threat, threat_type = anomaly_res[0], anomaly_res[1] if len(anomaly_res) > 1 else "ANOMALY_DETECTED"
        else:
            is_threat, threat_type = False, "NORMAL"

        speed_kmh = self.demo_speed if self.demo_mode_active else self.location_engine.calculate_speed(self.previous_loc, current_loc)
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

        is_display_only = getattr(self, "display_only_mode", False) or (self.gui_app and getattr(self.gui_app, "display_only_mode", False))
        if is_threat:
            if is_display_only:
                print(f"👁️ [DISPLAY ONLY] Threat evaluated: '{threat_type}'. Emergency actions suppressed (Show Only active).")
                if self.gui_app and hasattr(self.gui_app, "_tele_threat"):
                    self.gui_app._tele_threat.set("👁️ SHOW ONLY")
            else:
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
            "system_health": diag["diagnostic_status"],
            "speed_kmh": speed_kmh,
            "is_demo": self.demo_mode_active
        }

    def stop_all(self):
        """Clean shutdown of all engines and threads."""
        try:
            self.cancel_call_escalation()
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

    # ── Mobile Phone Connectivity ───────────────────────────────────────────
    def connect_mobile_phone(self, ip_port: str = None) -> dict:
        """Connects or refreshes phone connection over USB ADB or Wi-Fi."""
        if ip_port:
            res = self.telephony_manager.connect_wifi_device(ip_port)
            if not res.get("connected"):
                return res
        info = self.telephony_manager.check_phone_connection()
        if info.get("device_connected"):
            dev_id = info.get("device_id")
            self.telephony_manager.setup_adb_port_forwarding(dev_id)
            self.phone_has_signal = True
            print(f"📱 [MainController] Mobile Phone linked: {info.get('notes')}")
        return info

    def get_phone_status(self) -> dict:
        """Returns current mobile phone connection and SIM status."""
        return self.telephony_manager.check_phone_connection()


    # ── Evidence / Media Deletion & Management ──────────────────────────────
    def delete_recording(self, file_path: str) -> bool:
        """Permanently deletes a single audio or video recording file and cleans sync queue."""
        try:
            # Clean from sync queue first to prevent concurrent background file access
            if hasattr(self, "sync_manager") and self.sync_manager:
                self.sync_manager.remove_audio_from_queue(file_path)

            if os.path.exists(file_path):
                for attempt in range(5):
                    try:
                        os.remove(file_path)
                        break
                    except PermissionError:
                        time.sleep(0.15)
                else:
                    os.remove(file_path)
            return True
        except Exception as e:
            print(f"❌ [Recording Deletion Error]: {e}")
            return False

    def delete_recordings_batch(self, file_paths: list) -> int:
        """Permanently deletes a list of recordings and cleans sync queue. Returns count deleted."""
        deleted = 0
        for fp in file_paths:
            if self.delete_recording(fp):
                deleted += 1
        return deleted

    def delete_all_recordings(self, media_type: str = "all") -> int:
        """
        Deletes all recordings matching media_type ('audio', 'video', or 'all').
        Returns the number of files deleted.
        """
        import glob
        deleted = 0
        patterns = []
        if media_type in ("audio", "all"):
            patterns.append(os.path.join("recordings", "audio", "*.*"))
            if hasattr(self, "sync_manager") and self.sync_manager:
                self.sync_manager.clear_audio_queue()
        if media_type in ("video", "all"):
            patterns.append(os.path.join("recordings", "video", "*.*"))

        for pat in patterns:
            for f in glob.glob(pat):
                try:
                    os.remove(f)
                    deleted += 1
                except Exception as e:
                    print(f"❌ [Media Deletion Error] Could not delete {f}: {e}")
        return deleted

    def get_recordings_stats(self) -> dict:
        """Returns counts and total file sizes in bytes for audio and video vaults."""
        import glob
        audio_files = glob.glob(os.path.join("recordings", "audio", "*.*"))
        video_files = glob.glob(os.path.join("recordings", "video", "*.*"))
        a_size = sum(os.path.getsize(f) for f in audio_files if os.path.isfile(f))
        v_size = sum(os.path.getsize(f) for f in video_files if os.path.isfile(f))
        return {
            "audio": {"count": len(audio_files), "size_bytes": a_size, "files": audio_files},
            "video": {"count": len(video_files), "size_bytes": v_size, "files": video_files},
            "total_count": len(audio_files) + len(video_files),
            "total_size_bytes": a_size + v_size
        }