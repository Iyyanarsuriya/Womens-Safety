import subprocess
import threading
import time


class NetworkMonitor:

    def __init__(self, controller=None, gui_app=None, poll_interval=2.0):
        self.controller = controller
        self.gui_app = gui_app
        self.poll_interval = poll_interval
        self.is_running = False
        self.phone_has_signal = True

    def start(self):
        self.is_running = True
        threading.Thread(target=self._poll_loop, daemon=True).start()
        print("📶 [Network Monitor] Active - Hotspot IP Tracking...")

    def _poll_loop(self):
        while self.is_running:
            status, status_text, color = self._check_phone_network()
            self.phone_has_signal = status

            if self.controller:
                self.controller.phone_has_signal = status

            if self.gui_app and self.is_running:
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

            time.sleep(self.poll_interval)

    def _get_default_gateway(self):
        try:
            import socket
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
                # Return the subnet gateway (e.g. 192.168.1.1)
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
                return True, "📶 Signal: LTE/5G Connected", "#10b981"  # Green
            else:
                return False, "🚫 Signal: Phone Disconnected", "#64748b"  # Gray

        except Exception:
            return False, "🚫 Signal: Phone Disconnected", "#64748b"  # Gray

    def stop(self):
        self.is_running = False