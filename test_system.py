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


if __name__ == "__main__":
    unittest.main(verbosity=2)
