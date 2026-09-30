import json
import socket
import threading
import time

HOST = "localhost"
PORT = 8082
RECONNECT_DELAY_SEC = 2.0
RECV_BUFFER_BYTES = 4096


class GPSBridge:
    def __init__(self, controller):
        self.controller = controller
        self._stop_event = threading.Event()

    def start(self):
        self._stop_event.clear()
        threading.Thread(target=self._run, daemon=True).start()
        print("🛰️ [GPS Bridge] Started - connecting to phone's location stream...")
        return self

    def stop(self):
        self._stop_event.set()

    def _run(self):
        last_notice_time = 0.0
        while not self._stop_event.is_set():
            try:
                self._connect_and_read()
            except Exception as exc:
                now = time.time()
                if not self._stop_event.is_set() and (now - last_notice_time >= 30.0):
                    print(f"🛰️ [GPS Bridge] Standby - awaiting phone GPS stream on port {PORT}...")
                    last_notice_time = now
                self._stop_event.wait(RECONNECT_DELAY_SEC)

    def _connect_and_read(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect((HOST, PORT))
            sock.settimeout(None)
            print("🛰️ [GPS Bridge] Connected. Listening for location data...")

            buffer = ""
            while not self._stop_event.is_set():
                chunk = sock.recv(RECV_BUFFER_BYTES)
                if not chunk:
                    print("🛰️ [GPS Bridge] Server closed the connection.")
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                buffer = self._process_buffer(buffer)

    def _process_buffer(self, buffer):
        lines = buffer.split("\n")
        incomplete = lines[-1]

        for line in lines[:-1]:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                self._handle_payload(data)
            except json.JSONDecodeError:
                pass

        return incomplete

    def _handle_payload(self, data):
        lat = data.get("latitude")
        lon = data.get("longitude")
        if lat is None or lon is None:
            return

        self.controller.location_engine.current_lat = float(lat)
        self.controller.location_engine.current_lon = float(lon)
        print(f"🛰️ [GPS Bridge] Real location: {lat:.6f}, {lon:.6f}")


if __name__ == "__main__":
    class DummyLocationEngine:
        current_lat = 0.0
        current_lon = 0.0

    class DummyController:
        location_engine = DummyLocationEngine()

    print("=== GPS Bridge - Standalone Test ===")
    bridge = GPSBridge(DummyController())
    bridge.start()
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        bridge.stop()