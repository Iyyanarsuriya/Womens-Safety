"""
main.py
────────────────────────────────────────────────────────────────────────────
AURA — AI-Powered Women Safety System Launcher.
Initializes the master controller, Tkinter GUI, sensor engines, and sync daemons.
"""

import sys
import tkinter as tk

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from gui_module import ModernSafetyApp
from main_controller import MainSafetyController


def main():
    print("=" * 60)
    print("🛡️  AURA — AI Women Safety System Starting Up...")
    print("=" * 60)

    print("1. Initializing Master Safety Controller & Engines...")
    controller = MainSafetyController()

    print("2. Launching Modern Dashboard Interface...")
    root = tk.Tk()
    app = ModernSafetyApp(root, controller=controller)
    controller.attach_gui(app)

    def on_closing():
        print("\n🛑 Shutting down AURA Safety System cleanly...")
        try:
            controller.stop_all()
        except (Exception, KeyboardInterrupt):
            pass
        try:
            root.destroy()
        except Exception:
            pass
        sys.exit(0)

    root.protocol("WM_DELETE_WINDOW", on_closing)

    try:
        print("✅ System Ready & Monitoring! Running Mainloop...\n")
        root.mainloop()
    except KeyboardInterrupt:
        on_closing()
    finally:
        try:
            controller.stop_all()
        except Exception:
            pass


if __name__ == "__main__":
    main()