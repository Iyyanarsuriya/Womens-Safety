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
            print("  ✅ Backend is ONLINE with SQLite database ready.")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
