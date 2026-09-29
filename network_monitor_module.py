import subprocess
import threading
import time
import socket


class NetworkMonitor:

    def __init__(self, controller=None, gui_app=None, poll_interval=2.0, target_host=None, ping_interval=None):
        self.controller = controller
        self.gui_app = gui_app
        self.target_host = target_host
        self.poll_interval = ping_interval if ping_interval is not None else poll_interval
        self.is_running = False
        self._stop_event = threading.Event()
        self.phone_has_signal = True
        self.was_connected = True
        self.alarm_active = False

    @property
    def is_connected(self):
        return self.phone_has_signal

    @is_connected.setter
    def is_connected(self, val):
        self.phone_has_signal = bool(val)
        self.was_connected = bool(val)

    def _handle_connection_transition(self, now_connected: bool):
        """
        Processes connection state transitions.
        Prevents repeated alarms when already disconnected.
        Returns event dict or None.
        """
        if not now_connected and self.was_connected:
            self.was_connected = False
            self.phone_has_signal = False
            if not self.alarm_active:
                self.alarm_active = True
                self._handle_disconnection()
                return {"event": "CONNECTION_LOST"}
            return None
        elif not now_connected and not self.was_connected:
            # Already disconnected; avoid repeated alarm loop
            return None
        elif now_connected and not self.was_connected:
            self.was_connected = True
            self.phone_has_signal = True
            self.alarm_active = False
            self._handle_reconnection()
            return {"event": "CONNECTION_RESTORED"}
        return None

    def start(self):
        self.is_running = True
        self._stop_event.clear()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        print("📶 [Network Monitor] Active - Hotspot IP & Connectivity Tracking...")

    def _poll_loop(self):
        while self.is_running and not self._stop_event.is_set():
            status, status_text, color = self._check_phone_network()
            self.phone_has_signal = status

            if self.controller:
                self.controller.phone_has_signal = status

            # Handle state transitions
            if not status and self.was_connected:
                # TRANSITION: CONNECTED -> DISCONNECTED
                self._handle_disconnection()
            elif status and not self.was_connected:
                # TRANSITION: DISCONNECTED -> CONNECTED (RECONNECTION)
                self._handle_reconnection()

            self.was_connected = status

            if self.gui_app and self.is_running and not self._stop_event.is_set():
                try:
                    if hasattr(self.gui_app, "root") and self.gui_app.root.winfo_exists():
                        if hasattr(self.gui_app, "signal_status_str"):
                            self.gui_app.root.after(
                                0, lambda s=status_text: self.gui_app.signal_status_str.set(s)
                            )
                        if hasattr(self.gui_app, "update_signal_label"):
                            self.gui_app.root.after(
                                0, lambda s=status_text, c=color: self.gui_app.update_signal_label(s, c)
                            )
                except Exception:
                    pass

            self._stop_event.wait(self.poll_interval)

    def _handle_disconnection(self):
        """Fires once upon unexpected network/hotspot disconnection to prevent loops."""
        if self.alarm_active:
            return
        self.alarm_active = True
        print("⚠️ [NetworkMonitor] Connection lost! Triggering audible/visible warning...")

        # 1. Audible warning tone in background
        def _sound_alarm():
            try:
                import winsound
                for _ in range(3):
                    winsound.Beep(900, 150)
                    winsound.Beep(600, 150)
            except Exception:
                print("\a")

        threading.Thread(target=_sound_alarm, daemon=True).start()

        # 2. Visible alarm on GUI
        if self.gui_app and hasattr(self.gui_app, "root") and self.gui_app.root.winfo_exists():
            self.gui_app.root.after(
                0,
                lambda: self.gui_app.send_desktop_popup(
                    "⚠️ Connectivity Alert",
                    "Phone Hotspot / Network unexpectedly disconnected! Please verify phone connection."
                )
            )

        # 3. Log to Blackbox
        if self.controller and hasattr(self.controller, "log_blackbox_event"):
            loc = self.controller.location_engine.get_current_location() if hasattr(self.controller, "location_engine") else {"latitude": 0.0, "longitude": 0.0}
            self.controller.log_blackbox_event(
                loc.get("latitude", 0.0),
                loc.get("longitude", 0.0),
                "HOTSPOT_DISCONNECTED",
                details="Network connection to gateway timed out"
            )

    def _handle_reconnection(self):
        """Fires once upon successful reconnection."""
        self.alarm_active = False
        print("✅ [NetworkMonitor] Hotspot / Network reconnected successfully.")

        # Brief positive chime
        def _sound_restored():
            try:
                import winsound
                winsound.Beep(1200, 100)
                winsound.Beep(1600, 150)
            except Exception:
                pass

        threading.Thread(target=_sound_restored, daemon=True).start()

        if self.gui_app and hasattr(self.gui_app, "root") and self.gui_app.root.winfo_exists():
            self.gui_app.root.after(
                0,
                lambda: self.gui_app.send_desktop_popup(
                    "✅ Connectivity Restored",
                    "Phone Hotspot / Network has reconnected successfully."
                )
            )

        if self.controller and hasattr(self.controller, "log_blackbox_event"):
            loc = self.controller.location_engine.get_current_location() if hasattr(self.controller, "location_engine") else {"latitude": 0.0, "longitude": 0.0}
            self.controller.log_blackbox_event(
                loc.get("latitude", 0.0),
                loc.get("longitude", 0.0),
                "HOTSPOT_RECONNECTED",
                details="Network connection to gateway restored"
            )

    def _get_default_gateway(self):
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            res = subprocess.run(["ipconfig"], capture_output=True, text=True, startupinfo=startupinfo)

            for line in res.stdout.splitlines():
                if "Default Gateway" in line:
                    parts = line.split(":")
                    if len(parts) > 1:
                        val = parts[1].strip()
                        if val and not val.startswith("fe80") and val != "::":
                            return val

            # Dynamic fallback: check local interface routing dynamically
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                sub = ip.rsplit(".", 1)[0]
                return f"{sub}.1"
        except Exception:
            return "127.0.0.1"

    def _check_phone_network(self):
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            gateway_ip = self._get_default_gateway()

            ping_res = subprocess.run(
                ["ping", "-n", "1", "-w", "500", gateway_ip],
                capture_output=True,
                text=True,
                startupinfo=startupinfo,
            )

            if ping_res.returncode == 0:
                return True, "📶 Signal: Connected", "#10b981"  # Green
            else:
                return False, "🚫 Signal: Disconnected", "#ef4444"  # Red

        except Exception:
            return False, "🚫 Signal: Disconnected", "#ef4444"

    def stop(self):
        self.is_running = False
        self._stop_event.set()


# Module-level alias for backward compatibility and test suite
NetworkConnectivityMonitor = NetworkMonitor