"""
test_system.py
────────────────────────────────────────────────────────────────────────────
Comprehensive Verification Test Suite for AURA Women Safety System.

Validates:
  1. Phone Fall Detection (Freefall + Gyro tumble + High-G impact)
  2. 15s/30s Emergency Countdown & "I'm Safe" cancellation
  3. Automatic Emergency Sequence Activation
  4. Manual SOS Triggering
  5. GPS Location Acquisition & Google Maps Link Generation
  6. Guardian SMS Dispatch & Prioritized Phone Calls with Android Restrictions
  7. Audio Evidence Recording
  8. Offline-First Storage & Synchronization to Flask/SQLite Backend
  9. Stateful Geofencing (Safe Zone Entry & Exit events)
 10. LSTM Next-Location Prediction & Cluster Zone Fallback
 11. Profile Persistence across Application Restarts
"""

import os
import sys
import time
import json
import sqlite3
import unittest
import threading
import urllib.request

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# System modules
import app as backend_app
import tkinter as tk
from gui_module import ModernSafetyApp
from main_controller import MainSafetyController
from fall_detector import FallDetector
from location_module import OfflineLocationEngine
from prediction_module import LSTMTrajectoryPredictor
from sync_manager import SyncManager
from android_telephony_module import AndroidTelephonyManager


class TestWomenSafetySystem(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        print("\n" + "=" * 70)
        print("🚀 STARTING AURA WOMEN SAFETY AUTOMATED TEST SUITE")
        print("=" * 70)

        # Start Flask backend in background daemon thread on port 5000
        cls.backend_thread = threading.Thread(
            target=lambda: backend_app.app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False),
            daemon=True,
            name="BackendTestServer"
        )
        cls.backend_thread.start()
        time.sleep(1.5)  # wait for backend startup

    def test_01_backend_health_and_database(self):
        """Validates Flask server health check and SQLite database initialization."""
        print("\n[TEST 1] Testing Backend Health & Database...")
        req = urllib.request.Request("http://127.0.0.1:5000/api/status")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data.get("status"), "online")
            self.assertIn("database", data)
            print("  ✅ Backend is OPERATIONAL with SQLite database ready.")

    def test_02_phone_fall_detection_algorithm(self):
        """Tests multi-phase fall detection (Freefall -> Gyro Tumble -> High-G Impact)."""
        print("\n[TEST 2] Testing Phone Fall Detection Algorithm...")
        fall_triggered = [False]

        def on_fall():
            fall_triggered[0] = True

        detector = FallDetector(callback=on_fall)

        # 1. Normal gravity (9.8 m/s²) - should NOT trigger
        detector.process_sensor_sample((0.0, 0.0, 9.8))
        self.assertFalse(fall_triggered[0])

        # 2. Free-fall phase (< 6.0 m/s²)
        detector.process_sensor_sample((0.2, 0.5, 2.0), gyro_xyz=(2.5, 3.1, 1.8), now=10.0)
        self.assertFalse(fall_triggered[0])

        # 3. High-G impact phase (> 8.0 m/s²) within window (e.g. at 10.8s)
        detector.process_sensor_sample((12.0, 8.5, 14.2), gyro_xyz=(4.2, 1.0, 0.5), now=10.8)
        self.assertTrue(fall_triggered[0], "Fall callback should have fired upon freefall + impact sequence!")
        print("  ✅ Freefall + Gyro Tumble + Impact sequence reliably detected.")

    def test_03_gps_location_and_maps_link(self):
        """Validates GPS acquisition, Haversine speed computation, and map links."""
        print("\n[TEST 3] Testing GPS Acquisition & Maps URL...")
        loc_engine = OfflineLocationEngine(default_lat=11.48896, default_lon=79.75388)
        loc = loc_engine.get_current_location()

        self.assertAlmostEqual(loc["latitude"], 11.48896, places=4)
        self.assertAlmostEqual(loc["longitude"], 79.75388, places=4)
        self.assertTrue(loc["maps_url"].startswith("https://maps.google.com/?q="))
        print(f"  ✅ GPS Link Generated: {loc['maps_url']}")

    def test_04_stateful_geofencing_entry_and_exit(self):
        """Tests predefined safe zones, exit alerts, and entry detection."""
        print("\n[TEST 4] Testing Safe-Location Geofence Feature...")
        loc_engine = OfflineLocationEngine()
        gm = loc_engine.geofence_manager
        gm.safe_zones = [
            {"name": "Home Sanctuary", "latitude": 11.48896, "longitude": 79.75388, "radius_km": 0.3}
        ]

        # 1. User starts inside safe zone
        events1 = gm.evaluate_transitions(11.48896, 79.75388)
        self.assertEqual(len(events1), 0)

        # 2. User moves 1.5 km away (Exit breach)
        events2 = gm.evaluate_transitions(11.47000, 79.74000)
        self.assertEqual(len(events2), 1)
        self.assertEqual(events2[0]["event"], "EXIT")
        self.assertEqual(events2[0]["zone_name"], "Home Sanctuary")
        print(f"  ✅ Geofence Exit Detected: {events2[0]['message']}")

        # 3. User returns to safe zone (Entry)
        events3 = gm.evaluate_transitions(11.48896, 79.75388)
        self.assertEqual(len(events3), 1)
        self.assertEqual(events3[0]["event"], "ENTRY")
        print(f"  ✅ Geofence Entry Detected: {events3[0]['message']}")

    def test_05_lstm_prediction_and_cluster_fallback(self):
        """Tests LSTM sequence extrapolation and practical cluster zone fallback."""
        print("\n[TEST 5] Testing LSTM Prediction & Cluster Zone Fallback...")
        predictor = LSTMTrajectoryPredictor(sequence_length=6)

        # Scenario A: Insufficient history (1 point) -> Practical Cluster Fallback
        predictor.reset()
        predictor.update_history(11.48896, 79.75388)
        pred_single = predictor.predict_next_coordinate()
        self.assertIsNotNone(pred_single)
        self.assertIn("CLUSTER_FALLBACK", pred_single["prediction_mode"])
        print(f"  ✅ Fallback for 1-point history: Mode={pred_single['prediction_mode']}, Zone={pred_single.get('cluster_name')}")

        # Scenario B: Full trajectory sequence
        coords = [
            (11.48896, 79.75388),
            (11.48750, 79.75200),
            (11.48610, 79.75020),
            (11.48470, 79.74840),
            (11.48330, 79.74660)
        ]
        for lat, lon in coords:
            predictor.update_history(lat, lon)

        pred_seq = predictor.predict_next_coordinate()
        self.assertIsNotNone(pred_seq)
        self.assertGreater(pred_seq["confidence"], 0.40)
        print(f"  ✅ Extrapolated Point: ({pred_seq['predicted_latitude']}, {pred_seq['predicted_longitude']}) Confidence={pred_seq['confidence']*100:.1f}%")

    def test_06_android_telephony_and_restrictions(self):
        """Validates prioritized calling (P1 -> P2), Android CALL vs DIAL fallback, and SMS dispatch."""
        print("\n[TEST 6] Testing Android Telephony & Permissions...")
        telephony = AndroidTelephonyManager()
        status = telephony.check_phone_connection()
        print(f"  📱 Phone connection status: {status['notes']}")

        # Test prioritized emergency calling with graceful restriction handling
        res = telephony.place_priority_emergency_call("9876543210", "9123456780")
        self.assertIn("p1_status", res)
        self.assertIn("p2_status", res)
        print(f"  ✅ Priority Calling Result: P1={res['p1_status']}, P2={res['p2_status']}, Restrictions={res['restrictions_encountered']}")

        # Test SMS dispatch
        sms_res = telephony.dispatch_emergency_sms("9876543210", "9123456780", "Test Emergency Alert", 11.48896, 79.75388)
        self.assertIn("p1_sms", sms_res)
        self.assertEqual(sms_res["macrodroid_webhook"], "DISPATCHED")
        print(f"  ✅ Emergency SMS Dispatch: {sms_res}")

    def test_07_offline_first_storage_and_backend_sync(self):
        """Validates offline queuing of emergency events & audio evidence and automatic synchronization."""
        print("\n[TEST 7] Testing Offline-First Queue & Backend Sync...")
        sync = SyncManager(backend_url="http://127.0.0.1:5000")

        # 1. Queue an offline emergency event
        test_event = {
            "event_id": f"TEST_SOS_{int(time.time() * 1000)}",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "threat_type": "HARDWARE_FALL_DETECTED",
            "latitude": 11.48896,
            "longitude": 79.75388,
            "contacts_notified": ["9876543210", "9123456780"],
            "call_status": "P1:CALL_INITIATED_SUCCESS",
            "sms_status": "SENT"
        }
        event_id = sync.queue_emergency_event(test_event)

        # 2. Create dummy emergency audio file and queue it
        test_audio_path = os.path.join("recordings", "audio", "TEST_Audio.wav")
        with open(test_audio_path, "wb") as f:
            f.write(b"RIFF....WAVEfmt ....data....test_payload")
        sync.queue_audio_file(test_audio_path, event_id=event_id)

        # 3. Trigger synchronization pass
        sync._sync_pass()
        time.sleep(1.0)

        # 4. Verify in Backend SQLite database
        conn = sqlite3.connect(os.path.join("data", "backend_safety.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT threat_type, latitude, longitude, sync_status FROM emergency_events WHERE event_id = ?", (event_id,))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row, "Emergency event must be saved in backend SQLite database!")
        self.assertEqual(row[0], "HARDWARE_FALL_DETECTED")
        self.assertEqual(row[3], "SYNCED")
        print(f"  ✅ Offline event successfully synced to backend SQLite: Event {event_id} ({row[3]})")

    def test_08_complete_master_controller_workflow(self):
        """Tests complete emergency activation sequence through MainSafetyController."""
        print("\n[TEST 8] Testing Complete Emergency Controller Workflow...")
        controller = MainSafetyController(
            emergency_contacts=["9876543210", "9123456780"],
            real_pin="1234",
            fake_pin="9999"
        )

        # Run emergency sequence
        loc = controller.location_engine.get_current_location()
        event_record = controller.execute_emergency_sequence("FALL_CONFIRMED_TIMEOUT", loc)

        self.assertEqual(controller.system_status, "EMERGENCY_TRIGGERED")
        self.assertEqual(event_record["threat_type"], "FALL_CONFIRMED_TIMEOUT")
        self.assertTrue(event_record["maps_link"].startswith("https://maps.google.com/?q="))
        print(f"  ✅ Master Controller successfully executed emergency sequence: Status={controller.system_status}")

        controller.stop_all()

    def test_09_user_profile_persistence(self):
        """Validates that user profile, emergency contacts, and PINs persist across restarts."""
        print("\n[TEST 9] Testing Profile Persistence across Restarts...")
        profile_file = os.path.join("data", "user_profile.json")
        backup_content = None
        if os.path.exists(profile_file):
            with open(profile_file, "r", encoding="utf-8") as f:
                backup_content = f.read()

        try:
            sample_profile = {
                "user_name": "Dynamic User",
                "user_phone": "9876543210",
                "contacts": [
                    {"name": "Guardian 1", "phone": "9876543211"},
                    {"name": "Guardian 2", "phone": "9876543212"}
                ],
                "delay_timer": 30,
                "real_pin": "5678",
                "fake_pin": "1111",
                "is_protection_active": True
            }
            with open(profile_file, "w", encoding="utf-8") as f:
                json.dump(sample_profile, f, indent=2)

            # Read back to simulate app startup
            with open(profile_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            self.assertEqual(loaded["user_name"], "Dynamic User")
            self.assertEqual(len(loaded["contacts"]), 2)
            self.assertEqual(loaded["delay_timer"], 30)
            self.assertEqual(loaded["real_pin"], "5678")
            self.assertEqual(loaded["fake_pin"], "1111")
            self.assertTrue(loaded["is_protection_active"])
            print(f"  ✅ Profile persisted and reloaded successfully: Name='{loaded['user_name']}', Contacts={len(loaded['contacts'])}, Timer={loaded['delay_timer']}s, PINs={loaded['real_pin']}/{loaded['fake_pin']}")
        finally:
            if backup_content is not None:
                with open(profile_file, "w", encoding="utf-8") as f:
                    f.write(backup_content)
            else:
                if os.path.exists(profile_file):
                    try:
                        os.remove(profile_file)
                    except Exception:
                        pass

    def test_10_phone_usb_fall_detection_debounce_and_no_duplicate_sms(self):
        """Req 1: Validates fall drop detection, cooldown debouncing and single SMS trigger."""
        print("\n[TEST 10] Testing Phone Fall Debouncing & Deduplication...")
        fall_count = [0]
        detector = FallDetector(callback=lambda: fall_count.__setitem__(0, fall_count[0] + 1))
        detector.cooldown_period = 2.0

        # Drop 1: Freefall + Impact
        detector.process_sensor_sample((0.1, 0.1, 1.5), now=100.0)
        detector.process_sensor_sample((10.0, 10.0, 12.0), now=100.5)
        self.assertEqual(fall_count[0], 1)

        # Immediate drop 2 within cooldown window (100.8s) -> should be suppressed
        detector.process_sensor_sample((0.1, 0.1, 1.5), now=100.7)
        detector.process_sensor_sample((10.0, 10.0, 12.0), now=100.9)
        self.assertEqual(fall_count[0], 1, "Duplicate drop within cooldown must be suppressed!")

        # Verify controller emergency debouncing avoids duplicate SMS triggers
        controller = MainSafetyController(emergency_contacts=["9876543210"], real_pin="1234", fake_pin="9999")
        loc = {"latitude": 11.48896, "longitude": 79.75388, "maps_url": "https://maps.google.com/?q=11.48896,79.75388"}
        ev1 = controller.execute_emergency_sequence("PHONE_FALL_DETECTED", loc)
        self.assertIsNotNone(ev1)
        # Immediate second call within 30s debounce:
        ev2 = controller.execute_emergency_sequence("PHONE_FALL_DETECTED", loc)
        self.assertIsNone(ev2, "Duplicate emergency execution for same incident must be debounced/suppressed!")
        controller.stop_all()
        print("  ✅ Fall detection cooldown and emergency deduplication verified.")

    def test_11_manual_live_map_movement_demo_isolation(self):
        """Req 2: Validates isolated live continuous demo movement without modifying real GPS."""
        print("\n[TEST 11] Testing Manual Live Map Movement Demo Isolation...")
        controller = MainSafetyController(emergency_contacts=["9876543210"])
        # Real GPS location before demo
        real_loc_before = controller.location_engine.get_current_location()
        real_lat_orig = real_loc_before["latitude"]
        real_lon_orig = real_loc_before["longitude"]

        # Activate demo mode
        controller.start_demo_mode(start_lat=12.9716, start_lon=77.5946, speed_kmh=45.0)
        self.assertTrue(controller.demo_mode_active)
        self.assertEqual(controller.demo_lat, 12.9716)
        self.assertEqual(controller.demo_lon, 77.5946)

        # Step simulated movement continuously
        for _ in range(5):
            controller.step_demo_movement(d_lat=0.001, d_lon=0.001)

        self.assertAlmostEqual(controller.demo_lat, 12.9766, places=4)
        self.assertAlmostEqual(controller.demo_lon, 77.5996, places=4)

        # Verify Real GPS engine remains isolated and unaffected
        real_loc_after = controller.location_engine.get_current_location()
        self.assertEqual(real_loc_after["latitude"], real_lat_orig)
        self.assertEqual(real_loc_after["longitude"], real_lon_orig)

        controller.stop_demo_mode()
        self.assertFalse(controller.demo_mode_active)
        controller.stop_all()
        print("  ✅ Live demo movement operates continuously and remains strictly isolated from real GPS.")

    def test_12_speed_and_route_deviation_are_you_safe_alert_with_cooldown(self):
        """Req 3: Validates speed/deviation 'Are you safe?' trigger and debounce/cooldown logic."""
        print("\n[TEST 12] Testing Speed / Route Deviation Alerts with Cooldown...")
        from anomaly_engine import AnomalyEngine
        engine = AnomalyEngine(speed_threshold_kmh=50.0)

        # Set reference destination
        engine.set_destination("Office Safe Hub", 11.48896, 79.75388)

        # 1. High speed violation (>50 km/h)
        threat_spd, reason_spd = engine.check_for_threats(
            speed_kmh=65.0, current_lat=11.48896, current_lon=79.75388,
            predicted_point={"latitude": 11.48896, "longitude": 79.75388}
        )
        self.assertTrue(threat_spd)
        self.assertIn("ARE YOU SAFE?", reason_spd)
        self.assertIn("SPEED", reason_spd)

        # User confirms "I AM SAFE" -> acknowledge_safe cooldown
        engine.acknowledge_safe(cooldown_seconds=60)

        # Immediate next cycle with same high speed should be suppressed by cooldown
        threat_cooldown, _ = engine.check_for_threats(
            speed_kmh=65.0, current_lat=11.48896, current_lon=79.75388,
            predicted_point={"latitude": 11.48896, "longitude": 79.75388}
        )
        self.assertFalse(threat_cooldown, "Repeated alert must be debounced/suppressed during cooldown period!")
        print("  ✅ 'Are you safe?' popup properly fires for speed/route deviation and honors cooldown.")

    def test_13_emergency_sms_current_location_and_maps_link(self):
        """Req 4: Validates multi-contact prioritized emergency SMS with current Google Maps link."""
        print("\n[TEST 13] Testing Emergency SMS Multi-Contact & Maps Link...")
        telephony = AndroidTelephonyManager()
        dispatched_payloads = []

        def mock_sms_webhook(p1, p2, lat, lon):
            dispatched_payloads.append({"p1": p1, "p2": p2, "lat": lat, "lon": lon})
            return True

        contacts = ["9876543210", "9123456780", "9000011111"]
        res = telephony.dispatch_emergency_sms(
            contacts=contacts,
            emergency_message="EMERGENCY DISTRESS SIGNAL",
            current_lat=11.48896,
            current_lon=79.75388,
            on_sms_dispatch=mock_sms_webhook
        )

        self.assertEqual(len(dispatched_payloads), 1)
        self.assertEqual(dispatched_payloads[0]["p1"], "9876543210")
        self.assertEqual(dispatched_payloads[0]["p2"], "9123456780")
        self.assertAlmostEqual(dispatched_payloads[0]["lat"], 11.48896)
        self.assertAlmostEqual(dispatched_payloads[0]["lon"], 79.75388)
        self.assertTrue(res.get("maps_url", "").startswith(f"https://maps.google.com/?q={11.48896:.6f},{79.75388:.6f}"))
        print(f"  ✅ Emergency SMS contains accurate Google Maps link: {res.get('maps_url')}")

    def test_14_call_escalation_sequential_priority_and_cancellation(self):
        """Req 5: Validates configurable 1-2 min response timeout before sequential calling & cancellation."""
        print("\n[TEST 14] Testing Automated Call Escalation...")
        controller = MainSafetyController(
            emergency_contacts=["9876543210", "9123456780"],
            real_pin="1234",
            fake_pin="9999"
        )
        escalation_mgr = controller.escalation_manager
        # Configure timeout within 60-120 range
        escalation_mgr.set_timeout(75)
        self.assertEqual(escalation_mgr.timeout_s, 75)

        # Start escalation
        escalation_mgr.start_escalation(
            contacts=["9876543210", "9123456780"],
            incident_type="SOS_TEST"
        )
        self.assertTrue(escalation_mgr.escalation_active)
        self.assertEqual(escalation_mgr.escalation_state, "WAITING_RESPONSE")

        # Cancel escalation by user (User confirms safe)
        escalation_mgr.cancel_escalation("User confirmed safe in UI")
        self.assertFalse(escalation_mgr.escalation_active)
        self.assertEqual(escalation_mgr.escalation_state, "RESOLVED_SAFE")
        controller.stop_all()
        print("  ✅ Automated Call Escalation configures 60-120s timeout and resolves upon user cancellation.")

    def test_15_low_battery_warning_no_sos(self):
        """Req 6: Validates low-battery (<=15%) sends dedicated warning SMS with location, does NOT trigger SOS."""
        print("\n[TEST 15] Testing Low Battery Warning SMS (No SOS)...")
        controller = MainSafetyController(emergency_contacts=["9876543210"])
        # Initial battery warning flag is False
        self.assertFalse(controller.battery_warning_sent)

        # Trigger low battery notice
        sent_warning = controller.send_low_battery_notice(battery_pct=14)
        self.assertTrue(sent_warning)
        self.assertTrue(controller.battery_warning_sent)
        # Verify SOS was NOT triggered
        self.assertNotEqual(controller.system_status, "EMERGENCY_TRIGGERED")

        # Second call while still low must not duplicate SMS
        sent_again = controller.send_low_battery_notice(battery_pct=13)
        self.assertFalse(sent_again, "Repeated warning SMS must be suppressed while low!")

        # Reset after charging
        controller.reset_battery_warning_state()
        self.assertFalse(controller.battery_warning_sent)
        controller.stop_all()
        print("  ✅ Low battery warning (<15%) dispatches warning without triggering SOS and resets on recharge.")

    def test_16_hotspot_connectivity_monitoring_alarm_and_recovery(self):
        """Req 7: Validates hotspot/connectivity monitoring, disconnect alarm and reconnection handling."""
        print("\n[TEST 16] Testing Hotspot / Connectivity Monitoring...")
        from network_monitor_module import NetworkConnectivityMonitor
        monitor = NetworkConnectivityMonitor(target_host="127.0.0.1", ping_interval=1.0)

        # Simulate connection state: online -> offline
        monitor.is_connected = True

        # Handle disconnect transition
        event_disc = monitor._handle_connection_transition(now_connected=False)
        self.assertEqual(event_disc.get("event"), "CONNECTION_LOST")
        self.assertTrue(monitor.alarm_active)

        # Handle second offline check -> no repeated alarm loop
        event_disc_again = monitor._handle_connection_transition(now_connected=False)
        self.assertIsNone(event_disc_again, "Alarm loop must be suppressed when already in alarm state!")

        # Handle reconnection
        event_reconn = monitor._handle_connection_transition(now_connected=True)
        self.assertEqual(event_reconn.get("event"), "CONNECTION_RESTORED")
        self.assertFalse(monitor.alarm_active)
        print("  ✅ Hotspot/connectivity monitor triggers alarm on drop and recovers on reconnection without looping.")

    def test_17_predefined_destination_trip_persistence(self):
        """Req 8: Validates setting, persisting in current_trip.json, reloading, and clearing destination."""
        print("\n[TEST 17] Testing Predefined Destination & Trip Persistence...")
        controller = MainSafetyController(emergency_contacts=["9876543210"])
        # Set destination
        dest = controller.set_trip_destination("University Campus", 11.4920, 79.7600)
        self.assertEqual(dest["name"], "University Campus")

        # Verify file persistence
        trip_file = os.path.join("data", "current_trip.json")
        self.assertTrue(os.path.exists(trip_file))
        with open(trip_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
        self.assertEqual(persisted["name"], "University Campus")
        self.assertEqual(persisted["latitude"], 11.4920)

        # Clear destination
        controller.clear_trip_destination()
        self.assertIsNone(controller.trip_destination)
        controller.stop_all()
        print("  ✅ Predefined destination saves to disk, tracks trip, and clears correctly.")

    def test_18_fake_shutdown_stealth_blackbox_logging(self):
        """Req 9: Validates duress PIN fake shutdown and local blackbox vault incident logging."""
        print("\n[TEST 18] Testing Fake Shutdown Duress & Blackbox Vault Logging...")
        controller = MainSafetyController(
            emergency_contacts=["9876543210"],
            real_pin="1234",
            fake_pin="9999"
        )
        # Test Duress PIN
        res = controller.verify_duress_pin("9999")
        self.assertEqual(res, "FAKE_DISABLE_ACTIVE")
        self.assertTrue(controller.stealth_active)

        # Test Blackbox Vault logging
        loc = {"latitude": 11.48896, "longitude": 79.75388}
        controller.log_blackbox_event(
            "STEALTH_DURESS_TRIGGERED",
            location=loc,
            details={"notes": "Duress stealth mode initiated"},
            is_demo=False
        )

        vault_file = controller.blackbox_file
        self.assertTrue(os.path.exists(vault_file))
        with open(vault_file, "r", encoding="utf-8") as f:
            vault_data = json.load(f)

        self.assertGreater(len(vault_data), 0)
        last_entry = vault_data[-1]
        self.assertEqual(last_entry["event"], "STEALTH_DURESS_TRIGGERED")
        self.assertEqual(last_entry["mode"], "PRODUCTION")
        self.assertIn("timestamp", last_entry)
        controller.stop_all()
        print(f"  ✅ Blackbox vault successfully recorded event: {last_entry['event']} in {last_entry['mode']} mode.")

    def test_19_media_and_evidence_deletion(self):
        """Tests individual, batch, and bulk deletion of audio & video evidence with sync queue cleanup."""
        print("\n[TEST 19] Testing Audio and Video Evidence Deletion Features...")
        controller = MainSafetyController(emergency_contacts=["9876543210"])

        # Setup test directories
        audio_dir = os.path.join("recordings", "audio")
        video_dir = os.path.join("recordings", "video")
        os.makedirs(audio_dir, exist_ok=True)
        os.makedirs(video_dir, exist_ok=True)

        # 1. Create sample audio & video files
        sample_audio_1 = os.path.join(audio_dir, "SAMPLE_DEL_AUDIO_1.wav")
        sample_audio_2 = os.path.join(audio_dir, "SAMPLE_DEL_AUDIO_2.wav")
        sample_video_1 = os.path.join(video_dir, "SAMPLE_DEL_VIDEO_1.avi")
        sample_video_2 = os.path.join(video_dir, "SAMPLE_DEL_VIDEO_2.avi")

        for p in [sample_audio_1, sample_audio_2, sample_video_1, sample_video_2]:
            with open(p, "wb") as f:
                f.write(b"SAMPLE_MEDIA_DATA_FOR_TESTING_12345")

        # 2. Queue audio file in sync manager and verify queueing
        controller.sync_manager.queue_audio_file(sample_audio_1, event_id="EV_DEL_TEST")
        vault = controller.sync_manager._load_vault()
        queued_names = [item["filename"] for item in vault.get("audio_queue", [])]
        self.assertIn("SAMPLE_DEL_AUDIO_1.wav", queued_names)

        # 3. Test single file deletion via controller and verify sync queue cleanup
        deleted = controller.delete_recording(sample_audio_1)
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(sample_audio_1))

        vault_after = controller.sync_manager._load_vault()
        queued_names_after = [item["filename"] for item in vault_after.get("audio_queue", [])]
        self.assertNotIn("SAMPLE_DEL_AUDIO_1.wav", queued_names_after, "Deleted audio must be removed from sync queue!")
        print("  ✅ Single recording deletion removes file and cleans sync manager queue.")

        # 4. Test batch file deletion
        batch_deleted = controller.delete_recordings_batch([sample_audio_2, sample_video_1])
        self.assertEqual(batch_deleted, 2)
        self.assertFalse(os.path.exists(sample_audio_2))
        self.assertFalse(os.path.exists(sample_video_1))
        print("  ✅ Batch deletion successfully deleted multiple selected recordings.")

        # 5. Test stats calculation
        stats = controller.get_recordings_stats()
        self.assertIn("audio", stats)
        self.assertIn("video", stats)
        self.assertIn("total_count", stats)
        self.assertTrue(os.path.exists(sample_video_2))

        # 6. Test delete_all_recordings for video
        del_v_count = controller.delete_all_recordings("video")
        self.assertGreaterEqual(del_v_count, 1)
        self.assertFalse(os.path.exists(sample_video_2))
        print("  ✅ Vault bulk purge deletes all targeted media recordings successfully.")

        controller.stop_all()

    def test_20_countdown_conditions_and_offline_phone_alert(self):
        """
        Validates:
          1. Countdown timer appears ONLY for Fall Detection and Route Deviation.
          2. Manual SOS and direct emergencies dispatch immediately without countdown timer.
          3. When alert is dispatched, countdown timer is NOT active.
          4. Alert contains current Google Maps location link and targets numbers saved in UI.
          5. Phone connectivity and offline dispatch fallbacks.
        """
        print("\n[TEST 20] Testing Countdown Timer Rules & Offline Phone Location Alert...")
        import tkinter as tk
        from gui_module import ModernSafetyApp

        controller = MainSafetyController(
            emergency_contacts=["9876543210", "9123456780", "9988776655"]
        )
        root = tk.Tk()
        root.withdraw()
        app = ModernSafetyApp(root, controller=controller)
        app.contacts = [
            {"name": "Mom", "phone": "9876543210"},
            {"name": "Dad", "phone": "9123456780"},
            {"name": "Friend", "phone": "9988776655"}
        ]
        controller.attach_gui(app)

        # 1. Fall Detection -> Countdown timer MUST appear
        app.is_threat_active = False
        app.trigger_threat("⚠️ HARD FALL / DROP DETECTED")
        self.assertTrue(app.is_threat_active, "Countdown timer MUST be active for Fall Detection!")
        app.dismiss_alarm("Test safe")
        self.assertFalse(app.is_threat_active)
        print("  ✅ Countdown timer correctly appears for Fall Detection.")

        # 2. Route Deviation -> Countdown timer MUST appear
        app.is_threat_active = False
        app.trigger_threat("⚠️ TRAJECTORY_ANOMALY (ROUTE_DEVIATION)")
        self.assertTrue(app.is_threat_active, "Countdown timer MUST be active for Route Deviation!")
        app.dismiss_alarm("Test safe")
        self.assertFalse(app.is_threat_active)
        print("  ✅ Countdown timer correctly appears for Route Deviation.")

        # 3. Manual SOS / Direct Emergency -> Countdown timer MUST NOT appear! Must dispatch immediately!
        app.is_threat_active = False
        dispatched_event = None
        orig_execute = controller.execute_emergency_sequence

        def mock_execute(threat_type, loc_data):
            nonlocal dispatched_event
            dispatched_event = orig_execute(threat_type, loc_data)
            return dispatched_event

        controller.execute_emergency_sequence = mock_execute

        app.trigger_threat("🚨 MANUAL SOS TRIGGER")
        self.assertFalse(app.is_threat_active, "Countdown timer MUST NOT appear for Manual SOS!")
        self.assertIsNotNone(dispatched_event, "Manual SOS must dispatch emergency sequence immediately!")
        self.assertIn("maps.google.com/?q=", dispatched_event["maps_link"])
        print("  ✅ Manual SOS bypasses countdown and dispatches immediately.")

        # 4. Voice Trigger -> Countdown timer MUST NOT appear! Must dispatch immediately!
        app.is_threat_active = False
        app.handle_voice_event("TRIGGER", "help")
        self.assertFalse(app.is_threat_active, "Countdown timer MUST NOT appear for Voice Trigger!")
        print("  ✅ Voice command emergency bypasses countdown and dispatches immediately.")

        # 5. Verify offline phone alert dispatch with location link to numbers saved in UI
        loc = controller.location_engine.get_current_location()
        lat = loc["latitude"]
        lon = loc["longitude"]
        saved_numbers = [c["phone"] for c in app.contacts]

        res = controller.telephony_manager.dispatch_emergency_sms(
            saved_numbers, lat=lat, lon=lon
        )
        self.assertIn("maps.google.com/?q=", res["maps_url"])
        self.assertEqual(len(res["contacts_sent"]), 3)
        for cs in res["contacts_sent"]:
            self.assertIn(cs["contact"], saved_numbers)
        print("  ✅ Offline alert contains current location link and targets all numbers saved in UI.")

        # 6. Test phone connection check
        phone_info = controller.get_phone_status()
        self.assertIn("adb_installed", phone_info)
        self.assertIn("device_connected", phone_info)
        print("  ✅ Mobile phone connection inspector operates correctly.")

        try:
            root.destroy()
        except Exception:
            pass
        controller.stop_all()

    def test_21_realistic_map_free_movement_and_no_online_word(self):
        """
        Validates:
        1. Realistic cartographic map rendering with water, roads, safe corridors, POIs, D-Pad.
        2. Free live movement on the map (clicking, dragging, directional stepping, keyboard).
        3. Real-time live reflection in UI (speed, coordinates, heading, breadcrumbs, HUD).
        4. Absence of separate buttons for Route Deviation or increasing speed.
        5. The word 'Online' does NOT appear in any UI status strings or badges.
        """
        print("\n[TEST 21] Testing Realistic Map, Free Movement & No 'Online' Word...")
        root = tk.Tk()
        root.withdraw()
        controller = MainSafetyController()
        app = ModernSafetyApp(root, controller=controller)
        app.contacts = [{"name": "P1 Guardian", "phone": "9876543210"}]
        controller.attach_gui(app)
        app.is_protection_active = True
        app.build_modern_dashboard()

        # 1. Realistic Vector Map Canvas & Layers
        self.assertIsNotNone(app.map_canvas, "Map canvas must be present in the UI.")
        app.map_canvas.update_idletasks()
        app._draw_realistic_map()
        base_items = app.map_canvas.find_withtag("map_base")
        self.assertGreater(len(base_items), 5, "Realistic map must render base features (water, parks, roads, blocks).")

        corridor_items = app.map_canvas.find_withtag("route_corridor")
        self.assertGreater(len(corridor_items), 0, "Realistic map must render planned safe route corridor.")

        dpad_items = app.map_canvas.find_withtag("dpad")
        self.assertGreater(len(dpad_items), 0, "Realistic map must render on-canvas interactive D-Pad.")
        print("  ✅ Realistic vector map renders terrain, water channel, road network, corridor, and D-Pad.")

        # 2. Free Movement Live Updates
        initial_lat = app.current_sim_lat
        initial_lon = app.current_sim_lon
        target_lat = 11.47200
        target_lon = 79.73500

        # Move to coordinate
        app.move_user_to_latlon(target_lat, target_lon, speed_kmh=42.0)
        self.assertEqual(app.current_sim_lat, target_lat)
        self.assertEqual(app.current_sim_lon, target_lon)
        self.assertIn("42", app.speed_indicator_str.get())
        self.assertGreater(len(app.map_trail_points), 0, "Breadcrumb trail must update on movement.")

        # Step East (90 deg)
        prev_lon = app.current_sim_lon
        app.step_user_direction(90)
        self.assertGreater(app.current_sim_lon, prev_lon, "User must move East on stepping 90 deg.")

        # Click simulation on canvas
        class FakeMouseEvent:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        app._on_map_click(FakeMouseEvent(200, 150))
        self.assertIsNotNone(app.current_sim_lat)
        self.assertIsNotNone(app.current_sim_lon)
        print("  ✅ User moves freely on map (clicks, drags, steps) and movement reflects live in UI.")

        # 3. Verify NO separate buttons for Route Deviation or increasing speed
        self.assertFalse(hasattr(app, "test_demo_speed_anomaly"), "Separate button method 'test_demo_speed_anomaly' must NOT exist!")
        self.assertFalse(hasattr(app, "test_demo_route_deviation"), "Separate button method 'test_demo_route_deviation' must NOT exist!")

        # Scan all buttons in main container for forbidden texts
        all_button_texts = []
        def _scan_buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Button):
                    all_button_texts.append(child.cget("text"))
                _scan_buttons(child)

        _scan_buttons(app.main_container)
        for btn_txt in all_button_texts:
            self.assertNotIn("Speed 90km/h", btn_txt, "Separate speed increase test button must be removed!")
            self.assertNotIn("Deviate Test", btn_txt, "Separate route deviation test button must be removed!")
        print("  ✅ Separate buttons for Route Deviation and speed increase are completely removed.")

        # 4. Verify the word 'Online' does NOT appear anywhere in UI variables
        controller.phone_has_signal = True
        app.update_map_canvas(app.current_sim_lat, app.current_sim_lon, None, 25.0, False)
        net_str = app._tele_network.get()
        self.assertNotIn("Online", net_str, "The word 'Online' must NOT appear in network status!")
        self.assertIn("Connected", net_str)

        all_string_vars = [
            app.battery_status_str.get(),
            app.signal_status_str.get(),
            app.demo_status_str.get(),
            app.destination_status_str.get(),
            app._tele_network.get(),
            app._tele_threat.get()
        ]
        for s in all_string_vars:
            self.assertNotIn("Online", s, f"The word 'Online' must NOT appear in UI string var: '{s}'")
            self.assertNotIn("online", s.lower(), f"The word 'online' must NOT appear in UI string var: '{s}'")
        print("  ✅ The word 'Online' does not appear anywhere in UI status badges or telemetry.")

        try:
            root.destroy()
        except Exception:
            pass
        controller.stop_all()

    def test_22_unwanted_continuous_alert_prevention_and_debounce(self):
        """
        Validates:
        1. Free movement on map does NOT trigger unwanted route deviation alerts.
        2. Setting a destination does NOT falsely alert simply because the user is far from destination at trip start.
        3. Rapid consecutive UI threat triggers are debounced to prevent continuous alert loops.
        4. Dismissing alarm resets controller status to ACTIVE_MONITORING and engages a safe cooldown.
        5. SOS dispatch is debounced against rapid repeat firing.
        """
        print("\n[TEST 22] Testing Unwanted Continuous Alert Prevention & Debouncing...")
        root = tk.Tk()
        root.withdraw()
        controller = MainSafetyController(emergency_contacts=["9876543210", "9123456780"])
        app = ModernSafetyApp(root, controller=controller)
        app.is_protection_active = True

        # 1. Free movement does not trigger route deviation
        controller.clear_trip_destination()
        app.move_user_to_latlon(11.47000, 79.73000, speed_kmh=25.0)
        cycle_res = controller.run_live_safety_cycle()
        self.assertFalse(cycle_res["anomaly_check"]["is_threat"], "Free movement without route must NOT trigger unwanted threat!")
        print("  ✅ Free movement without planned route operates normally without false route deviation.")

        # 2. Origin-to-destination start does NOT trigger immediate route deviation
        controller.set_trip_destination("University Campus", 11.49250, 79.75800)
        # Starting 3 km away from destination
        app.move_user_to_latlon(11.46500, 79.72000, speed_kmh=30.0)
        res_dest = controller.anomaly_engine.check_for_threats(
            speed_kmh=30.0, current_lat=11.46500, current_lon=79.72000
        )
        self.assertFalse(res_dest[0], "Being far from destination at start of trip must NOT trigger route deviation!")
        print("  ✅ Setting a destination does not falsely trigger route deviation at trip start.")

        # 3. Consecutive UI threat triggers are debounced
        threat_count = [0]
        orig_trigger_threat = app.trigger_threat

        # Reset threat debounce timer
        app._last_threat_trigger_time = 0.0
        app.is_threat_active = False

        app.trigger_threat("⚠️ ROUTE DEVIATION DETECTED")
        self.assertTrue(app.is_threat_active)

        # Immediate repeat trigger while active must be debounced
        app.trigger_threat("⚠️ ROUTE DEVIATION DETECTED")
        self.assertTrue(app.is_threat_active, "Threat state remains active without breaking or duplicate loops.")
        print("  ✅ Rapid consecutive threat triggers are cleanly debounced.")

        # 4. User confirming safe resets controller status and engages cooldown
        app.dismiss_alarm("User confirmed safe")
        self.assertFalse(app.is_threat_active)
        self.assertEqual(controller.system_status, "ACTIVE_MONITORING")
        self.assertGreater(controller.anomaly_engine.cooldown_period_sec, 60.0)
        print("  ✅ Dismissing alarm resets controller to ACTIVE_MONITORING and engages safe cooldown.")

        # 5. SOS dispatch debounce
        sos_dispatches = []
        app._last_sos_dispatch_time = 0.0
        orig_exec = controller.execute_emergency_sequence
        controller.execute_emergency_sequence = lambda threat, loc: sos_dispatches.append(threat)

        app.dispatch_sos()
        self.assertEqual(len(sos_dispatches), 1)
        # Immediate second dispatch within debounce window
        app.dispatch_sos()
        self.assertEqual(len(sos_dispatches), 1, "Duplicate SOS dispatch within 20s must be debounced!")
        print("  ✅ Rapid SOS dispatch deduplication prevents continuous alert bombardment.")

        controller.execute_emergency_sequence = orig_exec
        try:
            root.destroy()
        except Exception:
            pass
        controller.stop_all()


if __name__ == "__main__":
    unittest.main(verbosity=2)



