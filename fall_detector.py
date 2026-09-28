"""
fall_detector.py
────────────────────────────────────────────────────────────────────────────
Offline-first Fall Detection module for Android (Termux + ADB).
Optimized for Bed / Cushion / Short-Height Drop testing!
"""

import json
import math
import socket
import threading
import time
import logging

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [FallDetector] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fall_detector")

# ── Tuned Constants for Testing & Real World ────────────────────────────────
HOST                  = "localhost"
PORT                  = 8080

FREEFALL_THRESHOLD    = 6.0    # m/s² (Default Gravity is 9.8 m/s²; drop drops below 6.0)
IMPACT_THRESHOLD      = 8.0   # m/s² (Lowered from 22.0 to capture soft surface impacts)
FALL_WINDOW_SEC       = 2.0    # seconds — max gap allowed between free-fall & impact
RECONNECT_DELAY_SEC   = 2.0    # seconds wait before socket retries
RECV_BUFFER_BYTES     = 4096   # TCP receive buffer size

# 🔧 Set True while rehearsing to see live magnitude readings in the
# terminal (helps confirm the phone is streaming + tune thresholds if
# needed). Set False again for the actual demo to keep output clean.
DEBUG_PRINT_MAGNITUDE = True


class FallDetector:
    def __init__(self, callback: callable):
        if not callable(callback):
            raise TypeError("callback must be a callable (function/method).")
        self._callback       = callback
        self._stop_event     = threading.Event()
        self._thread         = threading.Thread(
            target=self._run, name="FallDetectorThread", daemon=True
        )
        self._freefall_time = None

    def start(self):
        self._stop_event.clear()
        self._thread.start()
        logger.info("Detector thread started (%s).", self._thread.name)
        return self

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        logger.info("Detector thread stopped.")

    @property
    def is_running(self):
        return self._thread.is_alive()

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self._connect_and_read()
            except Exception as exc:
                logger.warning(
                    "Stream error (%s: %s). Retrying in %.1f s ...",
                    type(exc).__name__, exc, RECONNECT_DELAY_SEC,
                )
                time.sleep(RECONNECT_DELAY_SEC)

    def _connect_and_read(self):
        logger.info("Connecting to %s:%d ...", HOST, PORT)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(10.0)
            sock.connect((HOST, PORT))
            sock.settimeout(None)
            logger.info("Connected. Listening for sensor data ...")

            buffer = ""
            while not self._stop_event.is_set():
                chunk = sock.recv(RECV_BUFFER_BYTES)
                if not chunk:
                    logger.warning("Server closed the connection.")
                    break

                buffer += chunk.decode("utf-8", errors="replace")
                buffer  = self._process_buffer(buffer)

    def _process_buffer(self, buffer):
        lines      = buffer.split("\n")
        incomplete = lines[-1]

        for line in lines[:-1]:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                self._handle_payload(payload)
            except json.JSONDecodeError:
                pass

        return incomplete

    def _handle_payload(self, payload):
        """
        Dynamically finds sensor values whether key is 'lis2hh12_acc',
        'accelerometer', or first available JSON dict key.
        """
        try:
            values = []
            if isinstance(payload, dict):
                for key in ["lis2hh12_acc", "accelerometer"] + list(payload.keys()):
                    if key in payload and "values" in payload[key]:
                        values = payload[key]["values"]
                        break

            if len(values) < 3:
                return

            x, y, z  = float(values[0]), float(values[1]), float(values[2])
            magnitude = math.sqrt(x**2 + y**2 + z**2)

        except (KeyError, TypeError, ValueError):
            return

        # 🔧 Live readout so you can confirm the stream is alive and tune
        # thresholds during rehearsal.
        if DEBUG_PRINT_MAGNITUDE:
            print(f"   mag={magnitude:.2f} m/s²", end="\r")

        now = time.monotonic()
        self._evaluate_fall_pattern(magnitude, now)

    def _evaluate_fall_pattern(self, magnitude, now):
        if magnitude < FREEFALL_THRESHOLD:
            if self._freefall_time is None:
                logger.info("🔻 Free-fall Phase Detected! (Magnitude: %.2f m/s²)", magnitude)
            self._freefall_time = now

        elif magnitude > IMPACT_THRESHOLD:
            if self._freefall_time is not None:
                elapsed = now - self._freefall_time
                if elapsed <= FALL_WINDOW_SEC:
                    logger.info(
                        "🚨 FALL IMPACT DETECTED! (Free-fall to Impact in %.3f s, "
                        "Impact Mag: %.2f m/s²)",
                        elapsed, magnitude,
                    )
                    self._freefall_time = None
                    self._fire_callback()
                else:
                    self._freefall_time = None
            else:
                logger.debug("High motion/shake (Mag: %.2f) without Free-fall.", magnitude)

    def _fire_callback(self):
        try:
            self._callback()
        except Exception as exc:
            logger.error("Callback error: %s", exc, exc_info=True)


def start_detection(callback_function):
    detector = FallDetector(callback=callback_function)
    detector.start()
    return detector


if __name__ == "__main__":
    def _demo_callback():
        print("\n" + "=" * 60)
        print("  🚨 FALL DETECTED! ALERT POPUP TRIGGERED 🚨")
        print("=" * 60 + "\n")

    print(f"Running fall_detector.py (Test Mode)...")
    det = start_detection(callback_function=_demo_callback)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        det.stop()