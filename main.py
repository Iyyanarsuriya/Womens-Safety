import tkinter as tk
from fall_detector import start_detection
from gui_module import ModernSafetyApp
from main_controller import MainSafetyController
from network_monitor_module import NetworkMonitor

def main():
    print("1. Initializing Master Controller...")
    controller = MainSafetyController()

    print("2. Launching Tkinter GUI Window...")
    root = tk.Tk()
    app = ModernSafetyApp(root, controller=controller)
    controller.attach_gui(app)

    def on_fall_detected():
        print("\n🚨 FALL DETECTED! Triggering Safety Alert! 🚨\n")
        root.after(0, lambda: app.trigger_threat("💥 HARDWARE FALL DETECTED (Phone Sensor)"))

    print("3. Starting Fall Detector Thread...")
    detector = start_detection(callback_function=on_fall_detected)

    print("4. Starting Network Monitor Thread...")
    net_monitor = NetworkMonitor(controller, gui_app=app)
    net_monitor.start()

    try:
        root.mainloop()
    finally:
        detector.stop()
        net_monitor.stop()
        gps_bridge.stop()


if __name__ == "__main__":
    main()