import os
import time
import threading
import psutil
import cv2


class SystemSensorDiagnostics:
    
    def __init__(self, battery_threshold=15):
        self.battery_threshold = battery_threshold
        self.low_battery_flag = False
        
        # Telemetry buffer for external phone/embedded sensors
        self.external_sensor_data = {
            "phone_battery": None,
            "accelerometer": {"x": 0.0, "y": 0.0, "z": 0.0},
            "fall_detected": False
        }

        # Video Recording Directory Setup
        self.recordings_dir = "recordings"
        if not os.path.exists(self.recordings_dir):
            os.makedirs(self.recordings_dir)

    def get_system_battery(self):
        """ Checks Laptop/Host System Battery Status """
        battery = psutil.sensors_battery()
        if battery is None:
            return {
                "percent": 100,
                "power_plugged": True,
                "is_critical": False,
                "source": "Host PC (AC Power)"
            }

        percent = battery.percent
        power_plugged = battery.power_plugged
        is_critical = (percent <= self.battery_threshold) and (not power_plugged)

        return {
            "percent": percent,
            "power_plugged": power_plugged,
            "is_critical": is_critical,
            "source": "Host PC Battery"
        }

    def update_mobile_sensor_telemetry(self, phone_battery_pct, accel_data=None, is_fall=False):
        """ 
        Real-time API endpoint to receive Telemetry from Mobile Phone 
        via Wi-Fi Socket, ADB, or MQTT Packet.
        """
        self.external_sensor_data["phone_battery"] = phone_battery_pct
        if accel_data:
            self.external_sensor_data["accelerometer"] = accel_data
        self.external_sensor_data["fall_detected"] = is_fall

    # --- 🎥 SILENT EMERGENCY BACKGROUND VIDEO RECORDING ---
    def record_emergency_video(self, duration_seconds=10, fps=20.0):
        """
        Records silent background evidence video via OpenCV without popping up any window.
        Saves file directly into 'recordings/' folder.
        """
        def video_thread():
            # Check battery before recording to save power
            diag = self.run_full_diagnostics()
            if diag["host_battery"]["is_critical"]:
                print("⚠️ [VIDEO MUTE] Battery critical (<15%). Skipping video recording to save power.")
                return

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(self.recordings_dir, f"SOS_Video_{timestamp}.avi")
            print(f"🎥 [SILENT VIDEO STARTED] Capturing background video to '{filename}'...")

            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # CAP_DSHOW prevents slow startup on Windows
            if not cap.isOpened():
                print("❌ [CAMERA ERROR] Webcam not available or occupied by another app.")
                return

            # Set resolution (Default 640x480 for lightweight processing)
            frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            out = cv2.VideoWriter(filename, fourcc, fps, (frame_width, frame_height))

            start_time = time.time()
            try:
                while int(time.time() - start_time) < duration_seconds:
                    ret, frame = cap.read()
                    if ret:
                        out.write(frame)
                    else:
                        break
                print(f"✅ [VIDEO SAVED] Silent evidence video stored successfully: {filename}")
            except Exception as e:
                print(f"❌ Video Recording Error: {e}")
            finally:
                cap.release()
                out.release()

        # Run video recording in daemon background thread so GUI never freezes
        threading.Thread(target=video_thread, daemon=True).start()

    def run_full_diagnostics(self):
        """ Performs combined system and external device status check """
        host_bat = self.get_system_battery()
        cpu_usage = psutil.cpu_percent(interval=0.2)
        ram_usage = psutil.virtual_memory().percent

        phone_bat = self.external_sensor_data["phone_battery"]
        
        # Critical Battery logic considering both Host and Mobile
        critical_battery = host_bat["is_critical"] or (phone_bat is not None and phone_bat <= self.battery_threshold)
        
        status_msg = "HEALTHY"
        if critical_battery:
            status_msg = "CRITICAL_BATTERY_WARNING"
        elif self.external_sensor_data["fall_detected"]:
            status_msg = "HARDWARE_IMPACT_DETECTED"
        elif cpu_usage > 90 or ram_usage > 90:
            status_msg = "HIGH_SYSTEM_LOAD"

        return {
            "host_battery": host_bat,
            "mobile_battery_percent": phone_bat,
            "accelerometer": self.external_sensor_data["accelerometer"],
            "fall_detected": self.external_sensor_data["fall_detected"],
            "cpu_usage_percent": cpu_usage,
            "ram_usage_percent": ram_usage,
            "diagnostic_status": status_msg
        }


if __name__ == "__main__":
    print("[Sensor Module] Initializing Multi-Device Diagnostics & Silent Video Engine...")
    sensor = SystemSensorDiagnostics(battery_threshold=15)

    # 1. Normal Check
    diag = sensor.run_full_diagnostics()
    print(f"\n🖥️ Host Status: {diag['diagnostic_status']}")
    print(f"🔋 Host Battery: {diag['host_battery']['percent']}%")

    # 2. Testing Silent Video Recording (Triggers background thread)
    print("\n🎥 Testing Silent Video Recording for 5 seconds...")
    sensor.record_emergency_video(duration_seconds=5)

    # Keep main alive brief moment to witness thread logs
    time.sleep(6)