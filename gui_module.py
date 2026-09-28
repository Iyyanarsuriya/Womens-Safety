import os
import glob
import re
import time
import threading
import subprocess
import platform
import math
import tkinter as tk
from tkinter import ttk, messagebox
import pygame
from PIL import Image, ImageTk
from acoustic_module import OfflineAcousticEngine
import map_simulator
import map_config
from macrodroid_dispatch_module import trigger_aura_sos

try:
    from plyer import notification
    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# ── Colour palette (single source of truth) ────────────────────────────────────
_P = {
    # Backgrounds
    "bg_root":    "#060b14",
    "bg_panel":   "#0d1421",
    "bg_card":    "#111827",
    "bg_card2":   "#0f1929",
    "bg_input":   "#1a2540",

    # Borders / accents
    "border":     "#1e3a5f",
    "border2":    "#243552",
    "accent":     "#38bdf8",      # sky-400
    "accent2":    "#818cf8",      # indigo-400
    "green":      "#10b981",      # emerald-500
    "amber":      "#f59e0b",      # amber-500
    "red":        "#ef4444",      # red-500
    "purple":     "#a855f7",      # purple-500
    "predict":    "#facc15",      # yellow prediction markers

    # Text
    "text_hi":    "#f1f5f9",
    "text_mid":   "#94a3b8",
    "text_dim":   "#475569",

    # Threat
    "threat_bg":  "#450a0a",
    "threat_fg":  "#fca5a5",

    # SOS button
    "sos_bg":     "#b91c1c",
    "sos_hover":  "#ef4444",
}


class ModernSafetyApp:
    def __init__(self, root, controller=None):
        self.root       = root
        self.controller = controller

        self.root.title("AURA — AI Emergency Safety System")
        self.root.geometry("1280x760")
        self.root.minsize(1100, 680)
        self.root.configure(bg=_P["bg_root"])
        self.root.resizable(True, True)

        self.is_fake_shutdown = False
        self.root.bind("<F8>", lambda event: self.trigger_fake_shutdown())
        self.root.bind("<F12>", lambda event: self.trigger_threat("🚨 MANUAL EMERGENCY (F12 HOTKEY)"))
        self.root.bind("<Control-s>", lambda event: self.trigger_threat("🚨 MANUAL EMERGENCY (HOTKEY)"))
        self.root.bind("<Control-S>", lambda event: self.trigger_threat("🚨 MANUAL EMERGENCY (HOTKEY)"))

        os.makedirs(os.path.join("recordings", "audio"), exist_ok=True)
        os.makedirs(os.path.join("recordings", "video"), exist_ok=True)
        os.makedirs("assets", exist_ok=True)
        os.makedirs("data", exist_ok=True)

        try:
            pygame.mixer.init()
        except Exception as e:
            print(f"Audio Mixer Warning: {e}")

        # ── User profile state ────────────────────────────────────────────────
        self.user_name   = ""
        self.user_phone  = ""
        self.contacts    = []    # [{name, phone}, …] — index 0 = P1
        self.safe_locations = []
        self.real_pin    = "1234"
        self.fake_pin    = "9999"
        self.delay_timer = tk.IntVar(value=15)
        self.enable_macrodroid = tk.BooleanVar(value=True)
        self.contact_rows = []

        # ── MacroDroid contact entries (set by settings dialog) ───────────────
        # p1_entry / p2_entry are populated once the dashboard is built.
        self.p1_entry = None
        self.p2_entry = None

        # ── Threat / timer state ──────────────────────────────────────────────
        self.time_left        = 15
        self.total_time       = 15
        self.is_threat_active = False
        self.timer_job        = None

        self.is_protection_active  = False
        self.low_battery_alert_sent = False

        # ── StringVars used across the dashboard ──────────────────────────────
        self.battery_status_str = tk.StringVar(value="🔋 Battery: 100%")
        self.signal_status_str  = tk.StringVar(value="📶 Signal: Checking…")
        self.speed_indicator_str = tk.StringVar(value="Speed: -- km/h")

        # Live telemetry sidebar vars
        self._tele_speed    = tk.StringVar(value="-- km/h")
        self._tele_seg_dist = tk.StringVar(value="-- m")
        self._tele_cum_dist = tk.StringVar(value="-- km")
        self._tele_pred_lat = tk.StringVar(value="--")
        self._tele_pred_lon = tk.StringVar(value="--")
        self._tele_conf     = tk.StringVar(value="--")
        self._tele_network  = tk.StringVar(value="Checking…")
        self._tele_threat   = tk.StringVar(value="● MONITORING")

        self.acoustic_engine = None

        self.main_container = tk.Frame(self.root, bg=_P["bg_root"])
        self.main_container.pack(fill="both", expand=True)

        self.root.bind("<Escape>", lambda e: self.dismiss_alarm("ESC Key Pressed"))

        self.map_trail_points = []

        self.profile_path = os.path.join("data", "user_profile.json")
        self.load_user_profile()

        threading.Thread(target=self.monitor_battery_status, daemon=True).start()
        self.show_splash_screen()

    # ═══════════════════════════════════════════════════════════════════════════
    # Profile Persistence
    # ═══════════════════════════════════════════════════════════════════════════

    def load_user_profile(self):
        """Restores user profile, contacts, and custom PINs across application restarts."""
        if os.path.exists(self.profile_path):
            try:
                import json
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    p = json.load(f)
                    self.user_name = p.get("user_name", "")
                    self.user_phone = p.get("user_phone", "")
                    self.contacts = p.get("contacts", [])
                    self.real_pin = p.get("real_pin", getattr(self, "real_pin", "1234"))
                    self.fake_pin = p.get("fake_pin", getattr(self, "fake_pin", "9999"))
                    dt = p.get("delay_timer", 15)
                    self.delay_timer.set(dt if dt in (15, 30) else 15)
                    if self.contacts and self.user_name:
                        self.is_protection_active = True
                        if self.controller:
                            self.controller.set_emergency_contacts([c["phone"] for c in self.contacts])
                            self.controller.set_pins(self.real_pin, self.fake_pin)
                print(f"✅ [Profile] Loaded profile for '{self.user_name}' with {len(self.contacts)} emergency contacts.")
            except Exception as e:
                print(f"[Profile Load Warning] {e}")

    def save_user_profile(self):
        """Saves current user profile, contacts, and custom PINs to disk."""
        try:
            import json
            data = {
                "user_name": self.user_name,
                "user_phone": self.user_phone,
                "contacts": self.contacts,
                "delay_timer": self.delay_timer.get(),
                "real_pin": getattr(self, "real_pin", "1234"),
                "fake_pin": getattr(self, "fake_pin", "9999"),
                "is_protection_active": self.is_protection_active
            }
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print("💾 [Profile] User profile saved successfully.")
        except Exception as e:
            print(f"[Profile Save Warning] {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════════════════

    def send_desktop_popup(self, title, message):
        """Dispatches an audible alert and an OS desktop notification toast."""
        def _beep():
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
        threading.Thread(target=_beep, daemon=True).start()

        if PLYER_AVAILABLE:
            try:
                notification.notify(title=title, message=message,
                                    app_name="AURA Safety Engine", timeout=5)
            except Exception as e:
                print(f"[Notification Notice] {e}")

    def clear_container(self):
        for w in self.main_container.winfo_children():
            w.destroy()

    def is_valid_phone(self, phone_str):
        digits = re.sub(r"\D", "", phone_str)
        return len(digits) == 10

    def _add_placeholder(self, entry, placeholder,
                         color=_P["text_dim"], real_color=_P["text_hi"]):
        entry.insert(0, placeholder)
        entry.config(fg=color)
        entry._placeholder = placeholder
        entry._is_placeholder = True

        def on_focus_in(e):
            if getattr(entry, "_is_placeholder", False):
                entry.delete(0, tk.END)
                entry.config(fg=real_color)
                entry._is_placeholder = False

        def on_focus_out(e):
            if not entry.get().strip():
                entry.insert(0, placeholder)
                entry.config(fg=color)
                entry._is_placeholder = True

        entry.bind("<FocusIn>",  on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

    @staticmethod
    def _entry_value_or_blank(entry):
        if getattr(entry, "_is_placeholder", False):
            return ""
        return entry.get().strip()

    # ── Reusable widget factories ─────────────────────────────────────────────

    def _glowing_label(self, parent, text, font_size=8, color=None,
                       bg=None, **kwargs):
        """A label styled as a glowing status badge."""
        c = color or _P["accent"]
        b = bg    or _P["bg_card"]
        return tk.Label(
            parent, text=text,
            font=("Segoe UI", font_size, "bold"),
            fg=c, bg=b,
            padx=6, pady=2,
            **kwargs,
        )

    def _card(self, parent, accent_color=_P["border2"]):
        """Returns a 2-pixel left-border card. Content goes in .content."""
        outer = tk.Frame(parent, bg=_P["bg_card"],
                         highlightbackground=_P["border"],
                         highlightthickness=1)
        strip = tk.Frame(outer, bg=accent_color, width=3)
        strip.pack(side="left", fill="y")
        inner = tk.Frame(outer, bg=_P["bg_card"])
        inner.pack(side="left", fill="both", expand=True, padx=(10, 8), pady=8)
        outer.content = inner
        return outer

    def _section_header(self, parent, icon, title, color):
        row = tk.Frame(parent, bg=parent["bg"])
        row.pack(fill="x", anchor="w", pady=(0, 6))
        badge = tk.Canvas(row, width=22, height=22,
                          bg=parent["bg"], highlightthickness=0)
        badge.pack(side="left", padx=(0, 6))
        badge.create_oval(1, 1, 21, 21, fill=color, outline="")
        badge.create_text(11, 11, text=icon, font=("Segoe UI", 10))
        tk.Label(row, text=title, font=("Segoe UI", 8, "bold"),
                 fg=color, bg=parent["bg"]).pack(side="left")
        return row

    def _circle_icon_button(self, parent, icon, caption, command,
                             bg=_P["bg_card"], fg=_P["accent"], size=40):
        wrap = tk.Frame(parent, bg=parent["bg"])
        c = tk.Canvas(wrap, width=size, height=size,
                      bg=parent["bg"], highlightthickness=0, cursor="hand2")
        c.pack()
        circle   = c.create_oval(2, 2, size - 2, size - 2, fill=bg, outline="")
        label_id = c.create_text(size / 2, size / 2, text=icon,
                                  font=("Segoe UI", int(size * 0.38)), fill=fg)
        tk.Label(wrap, text=caption, font=("Segoe UI", 7),
                 fg=_P["text_dim"], bg=parent["bg"]).pack(pady=(2, 0))

        def _click(e):  command()
        def _hin(e):
            c.itemconfig(circle, fill=fg)
            c.itemconfig(label_id, fill=_P["bg_root"])
        def _hout(e):
            c.itemconfig(circle, fill=bg)
            c.itemconfig(label_id, fill=fg)

        c.bind("<Button-1>", _click)
        c.bind("<Enter>",    _hin)
        c.bind("<Leave>",    _hout)
        return wrap

    # ═══════════════════════════════════════════════════════════════════════════
    # 1 – SPLASH SCREEN
    # ═══════════════════════════════════════════════════════════════════════════

    def show_splash_screen(self):
        self.clear_container()
        splash = tk.Frame(self.main_container, bg=_P["bg_root"])
        splash.pack(fill="both", expand=True)

        canvas = tk.Canvas(splash, width=340, height=340,
                           bg=_P["bg_root"], highlightthickness=0)
        canvas.pack(pady=(40, 10))

        # Static vector logo
        canvas.create_oval(60, 60, 280, 280, fill="#1e1b4b",
                           outline="#6366f1", width=2)
        canvas.create_oval(130, 90, 210, 170, fill="#f472b6", outline="")
        canvas.create_polygon(105, 250, 170, 140, 235, 250,
                              fill="#ec4899", outline="")
        canvas.create_text(170, 200, text="AURA",
                           font=("Segoe UI", 22, "bold"), fill="#ffffff")
        canvas.create_text(170, 230, text="SAFETY ENGINE",
                           font=("Segoe UI", 9, "bold"), fill=_P["accent"])

        tk.Label(splash, text="AURA SAFETY SYSTEM",
                 font=("Segoe UI", 26, "bold"),
                 fg=_P["accent"], bg=_P["bg_root"]).pack(pady=(0, 4))
        tk.Label(splash, text="Offline Edge AI  •  Realtime Location Intel  •  Emergency Dispatch",
                 font=("Segoe UI", 10), fg=_P["text_mid"],
                 bg=_P["bg_root"]).pack(pady=(0, 14))

        # Animated spinner
        self._spinner_angle  = 0
        self._spinner_active = True

        def _spin():
            if not self._spinner_active:
                return
            canvas.delete("spin")
            canvas.create_oval(24, 24, 316, 316, outline="#1e293b",
                               width=5, tags="spin")
            canvas.create_arc(24, 24, 316, 316,
                              start=self._spinner_angle, extent=100,
                              outline=_P["accent"], width=5,
                              style="arc", tags="spin")
            # Second arc for double-helix look
            canvas.create_arc(24, 24, 316, 316,
                              start=self._spinner_angle + 180, extent=60,
                              outline=_P["accent2"], width=3,
                              style="arc", tags="spin")
            self._spinner_angle = (self._spinner_angle + 8) % 360
            self.root.after(28, _spin)

        _spin()

        def _launch():
            time.sleep(2.0)
            self._spinner_active = False
            if self.is_protection_active and self.contacts:
                self.start_safety_monitoring_loop()
                self.root.after(0, lambda: self.build_modern_dashboard(pending_notification="✅ System Armed (Restored from Profile)"))
            else:
                self.root.after(0, self.build_setup_screen)

        threading.Thread(target=_launch, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════════════════
    # 2 – SETUP SCREEN
    # ═══════════════════════════════════════════════════════════════════════════

    def build_setup_screen(self):
        self.clear_container()

        setup_card = tk.Frame(
            self.main_container, bg=_P["bg_panel"],
            highlightbackground=_P["border"], highlightthickness=1,
        )
        setup_card.place(relx=0.5, rely=0.5, anchor="center",
                         width=560, height=620)

        hdr = tk.Frame(setup_card, bg=_P["bg_panel"])
        hdr.pack(fill="x", padx=32, pady=(28, 6))
        tk.Label(hdr, text="🛡️  AURA SAFETY ENGINE SETUP",
                 font=("Segoe UI", 15, "bold"),
                 fg=_P["accent"], bg=_P["bg_panel"]).pack(anchor="w")
        tk.Label(hdr, text="AI-Powered Offline Edge Emergency Protection",
                 font=("Segoe UI", 9), fg=_P["text_dim"],
                 bg=_P["bg_panel"]).pack(anchor="w", pady=(2, 10))

        frm = tk.Frame(setup_card, bg=_P["bg_panel"])
        frm.pack(fill="both", expand=True, padx=32)

        def _lbl(text, color=_P["accent2"]):
            tk.Label(frm, text=text, font=("Segoe UI", 8, "bold"),
                     fg=color, bg=_P["bg_panel"]).pack(anchor="w", pady=(8, 2))

        def _entry(**kw):
            e = tk.Entry(frm, font=("Segoe UI", 11),
                         bg=_P["bg_input"], fg=_P["text_hi"],
                         insertbackground=_P["accent"],
                         relief="flat", bd=0, highlightthickness=1,
                         highlightbackground=_P["border"],
                         highlightcolor=_P["accent"], **kw)
            e.pack(fill="x", ipady=9, pady=(0, 4))
            return e

        _lbl("FULL NAME")
        e_name = _entry()

        _lbl("MOBILE NUMBER  (10 digits)")
        e_phone = _entry()

        # Emergency contacts
        contacts_hdr = tk.Frame(frm, bg=_P["bg_panel"])
        contacts_hdr.pack(fill="x", pady=(10, 4))
        tk.Label(contacts_hdr, text="EMERGENCY CONTACTS  (P1 = highest priority)",
                 font=("Segoe UI", 8, "bold"),
                 fg=_P["accent2"], bg=_P["bg_panel"]).pack(side="left")
        tk.Button(contacts_hdr, text="+ Add",
                  font=("Segoe UI", 8, "bold"),
                  bg=_P["accent"], fg=_P["bg_root"],
                  bd=0, cursor="hand2", padx=10, pady=2,
                  command=lambda: _add_contact_row()).pack(side="right")

        contacts_box = tk.Frame(frm, bg=_P["bg_panel"])
        contacts_box.pack(fill="x")

        self.contact_rows = []

        def _add_contact_row(init_name="", init_phone=""):
            row = tk.Frame(contacts_box, bg=_P["bg_panel"])
            row.pack(fill="x", pady=3)

            e_cn = tk.Entry(row, font=("Segoe UI", 10),
                            bg=_P["bg_input"], fg=_P["text_hi"],
                            insertbackground=_P["accent"], bd=0,
                            highlightthickness=1,
                            highlightbackground=_P["border"],
                            highlightcolor=_P["accent"])
            e_cn.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 4))
            if init_name:
                e_cn.insert(0, init_name)
                e_cn._is_placeholder = False
            else:
                self._add_placeholder(e_cn, "Contact Name")

            e_cp = tk.Entry(row, font=("Segoe UI", 10),
                            bg=_P["bg_input"], fg=_P["text_hi"],
                            insertbackground=_P["accent"], bd=0,
                            highlightthickness=1,
                            highlightbackground=_P["border"],
                            highlightcolor=_P["accent"])
            e_cp.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 4))
            if init_phone:
                e_cp.insert(0, init_phone)
                e_cp._is_placeholder = False
            else:
                self._add_placeholder(e_cp, "10-Digit Mobile")

            def _del():
                self.contact_rows = [r for r in self.contact_rows
                                     if r["frame"] is not row]
                row.destroy()

            tk.Button(row, text="✖", font=("Segoe UI", 9, "bold"),
                      bg=_P["red"], fg="#fff", bd=0, cursor="hand2",
                      width=3, command=_del).pack(side="right", ipady=4)

            self.contact_rows.append({"frame": row,
                                       "name_entry": e_cn,
                                       "phone_entry": e_cp})

        _add_contact_row()

        def _do_setup():
            n = e_name.get().strip()
            p = e_phone.get().strip()
            if not n:
                messagebox.showerror("Setup Error", "Please enter your Full Name.")
                return
            if not self.is_valid_phone(p):
                messagebox.showerror("Setup Error",
                                     "Invalid Mobile Number! Enter a valid 10-digit number.")
                return

            parsed = []
            for row in self.contact_rows:
                cn = self._entry_value_or_blank(row["name_entry"])
                cp = self._entry_value_or_blank(row["phone_entry"])
                if cn and cp:
                    if not self.is_valid_phone(cp):
                        messagebox.showerror(
                            "Validation Error",
                            f"Contact number '{cp}' must be exactly 10 digits.")
                        return
                    parsed.append({"name": cn, "phone": cp})

            if not parsed:
                messagebox.showerror("Setup Error",
                                     "Add at least one valid 10-digit Emergency Contact.")
                return

            self.user_name  = n
            self.user_phone = p
            self.contacts   = parsed
            self.is_protection_active = True
            self.save_user_profile()

            if self.controller:
                self.controller.set_emergency_contacts(
                    [c["phone"] for c in parsed])

            try:
                if self.controller:
                    self.controller.acoustic_engine.trigger_callback = self.handle_voice_event
                    self.controller.acoustic_engine.start_listening()
                    self.controller.acoustic_engine.set_setup_complete(True)
                    self.acoustic_engine = self.controller.acoustic_engine
                else:
                    self.acoustic_engine = OfflineAcousticEngine(
                        trigger_callback=self.handle_voice_event)
                    self.acoustic_engine.start_listening()
                    self.acoustic_engine.set_setup_complete(True)
            except Exception as e:
                print(f"Acoustic startup: {e}")

            self.start_safety_monitoring_loop()
            self.build_modern_dashboard(
                pending_notification="✅ System Armed & Protection Active")

        tk.Button(
            setup_card,
            text="ACTIVATE SYSTEM PROTECTION  ➔",
            font=("Segoe UI", 10, "bold"),
            bg=_P["green"], fg="#ffffff", bd=0, cursor="hand2",
            command=_do_setup,
        ).pack(fill="x", padx=32, ipady=12, pady=(14, 28))

    # ── Backend monitoring loop ───────────────────────────────────────────────

    def start_safety_monitoring_loop(self):
        def cycle():
            if self.is_protection_active and self.controller:
                try:
                    self.controller.run_live_safety_cycle()
                except Exception as e:
                    print(f"[Safety Cycle Error] {e}")
            self.root.after(3000, cycle)
        cycle()

    # ── Battery monitoring ────────────────────────────────────────────────────

    def monitor_battery_status(self):
        while True:
            if self.is_protection_active and PSUTIL_AVAILABLE:
                battery = psutil.sensors_battery()
                if battery:
                    pct = battery.percent
                    self.battery_status_str.set(f"🔋 {pct:.0f}%")
                    if pct <= 15 and not battery.power_plugged \
                            and not self.low_battery_alert_sent:
                        self.low_battery_alert_sent = True
                        self.root.after(
                            0, lambda p=pct: self.trigger_low_battery_alert(p))
                    elif pct > 15:
                        self.low_battery_alert_sent = False
            time.sleep(10)

    def trigger_low_battery_alert(self, percent):
        msg = f"🔋 Low battery notice sent ({percent:.0f}%)"
        self.send_desktop_popup("🔋 Low Battery Notice", msg)
        if self.controller:
            try:
                loc = self.controller.location_engine.get_current_location()
                self.controller.send_low_battery_notice(percent, loc)
            except Exception as e:
                print(f"[Low Battery Error] {e}")
        self.build_modern_dashboard(pending_notification=msg, is_warning=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # 3 – DURESS SECURITY DIALOG
    # ═══════════════════════════════════════════════════════════════════════════

    def open_deactivation_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("System Deactivation")
        dlg.geometry("360x240")
        dlg.configure(bg=_P["bg_panel"])
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text="🔒  ENTER SECURITY PIN",
                 font=("Segoe UI", 12, "bold"),
                 fg=_P["red"], bg=_P["bg_panel"]).pack(pady=20)
        pin_e = tk.Entry(dlg, show="●", font=("Segoe UI", 16),
                         bg=_P["bg_input"], fg=_P["text_hi"],
                         justify="center", bd=0, insertbackground=_P["accent"])
        pin_e.pack(ipady=8, padx=36, fill="x")

        def _process():
            pin = pin_e.get().strip()
            res = "SUCCESS_DISABLE"
            if self.controller:
                res = self.controller.verify_duress_pin(pin, gui_root=self.root)
            else:
                if pin == "9999":   res = "FAKE_SHUTDOWN"
                elif pin == "1234": res = "SUCCESS_DISABLE"
            dlg.destroy()
            if res == "SUCCESS_DISABLE":
                self.root.destroy()
            elif res == "FAKE_SHUTDOWN":
                messagebox.showinfo("System Message",
                                    "System Deactivated Successfully.")
                self.trigger_stealth_fake_shutdown()

        tk.Button(dlg, text="CONFIRM DISARM",
                  font=("Segoe UI", 10, "bold"),
                  bg=_P["red"], fg="#fff", bd=0,
                  command=_process).pack(pady=20, ipady=8,
                                         padx=36, fill="x")

    def trigger_stealth_fake_shutdown(self):
        self.clear_container()
        self.root.attributes("-fullscreen", True)
        self.root.config(cursor="none")
        stealth = tk.Canvas(self.main_container,
                            bg="#000000", highlightthickness=0)
        stealth.pack(fill="both", expand=True)
        if self.controller:
            self.controller.start_emergency_recording()
        self.send_desktop_popup("AURA Stealth Engine",
                                "Pitch Black Mode. Covert tracking active.")

    # ═══════════════════════════════════════════════════════════════════════════
    # 4 – MAIN DASHBOARD
    # ═══════════════════════════════════════════════════════════════════════════

    def build_modern_dashboard(self, pending_notification=None,
                                is_error=False, is_warning=False,
                                impact_alert=None):
        self.clear_container()
        self.map_trail_points = []

        # ── Top navigation bar ────────────────────────────────────────────────
        topbar = tk.Frame(self.main_container, bg=_P["bg_panel"],
                          padx=14, pady=9,
                          highlightbackground=_P["border"],
                          highlightthickness=1)
        topbar.pack(fill="x")

        # Logo + title
        logo_row = tk.Frame(topbar, bg=_P["bg_panel"])
        logo_row.pack(side="left")
        logo_c = tk.Canvas(logo_row, width=26, height=26,
                           bg=_P["bg_panel"], highlightthickness=0)
        logo_c.pack(side="left", padx=(0, 8))
        logo_c.create_oval(1, 1, 25, 25, fill=_P["accent2"], outline="")
        logo_c.create_text(13, 13, text="🛡", font=("Segoe UI", 12))
        tk.Label(logo_row, text="AURA SAFETY DASHBOARD",
                 font=("Segoe UI", 13, "bold"),
                 fg=_P["accent"], bg=_P["bg_panel"]).pack(side="left")

        # Right side icons
        icon_row = tk.Frame(topbar, bg=_P["bg_panel"])
        icon_row.pack(side="right")
        self._circle_icon_button(
            icon_row, "🔒", "Disarm", self.open_deactivation_dialog,
            bg=_P["bg_card"], fg=_P["red"]).pack(side="right", padx=4)
        self._circle_icon_button(
            icon_row, "⚙️", "Settings", self.open_settings_dialog,
            bg=_P["bg_card"], fg=_P["accent"]).pack(side="right", padx=4)

        # Status badges
        badge_row = tk.Frame(topbar, bg=_P["bg_panel"])
        badge_row.pack(side="right", padx=10)
        for txt, fg in [
            (self.battery_status_str.get(),  _P["amber"]),
            ("🗂️ Vault: ON",                  _P["green"]),
            ("🛰️ Blackbox: ACTIVE",           _P["accent"]),
        ]:
            tk.Label(badge_row, text=txt,
                     font=("Segoe UI", 8, "bold"),
                     fg=fg, bg=_P["bg_card"],
                     padx=8, pady=3).pack(side="left", padx=3)

        # ── Alert banners ─────────────────────────────────────────────────────
        if impact_alert:
            bar = tk.Frame(self.main_container, bg="#991b1b", pady=6)
            bar.pack(fill="x")
            tk.Label(bar, text=f"💥 IMPACT: {impact_alert}",
                     font=("Segoe UI", 9, "bold"),
                     fg="#fff", bg="#991b1b").pack()

        if pending_notification:
            bg_c = "#450a0a" if is_error else ("#78350f" if is_warning else "#064e3b")
            fg_c = _P["red"] if is_error else ("#fde047" if is_warning else _P["green"])
            bar = tk.Frame(self.main_container, bg=bg_c, pady=5)
            bar.pack(fill="x")
            tk.Label(bar, text=pending_notification,
                     font=("Segoe UI", 9, "bold"),
                     fg=fg_c, bg=bg_c).pack()

        # ── Body ──────────────────────────────────────────────────────────────
        body = tk.Frame(self.main_container, bg=_P["bg_root"])
        body.pack(fill="both", expand=True, padx=12, pady=8)

        # Left column
        left = tk.Frame(body, bg=_P["bg_root"])
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self._build_left_column(left)

        # Centre column (map + actions)
        centre = tk.Frame(body, bg=_P["bg_root"])
        centre.pack(side="left", fill="both", expand=True, padx=6)
        self._build_centre_column(centre)

        # Right column (telemetry sidebar)
        right = tk.Frame(body, bg=_P["bg_root"])
        right.pack(side="right", fill="both", padx=(6, 0))
        self._build_telemetry_sidebar(right)

    # ── Left column ───────────────────────────────────────────────────────────

    def _build_left_column(self, parent):
        # Profile card
        pc = self._card(parent, accent_color=_P["accent2"])
        pc.pack(fill="x", pady=(0, 8))
        avatar = tk.Canvas(pc.content, width=42, height=42,
                           bg=_P["bg_card"], highlightthickness=0)
        avatar.pack(side="left", padx=(0, 10))
        init = (self.user_name[:1] or "A").upper()
        avatar.create_oval(1, 1, 41, 41, fill="#6366f1", outline="")
        avatar.create_text(21, 21, text=init,
                           font=("Segoe UI", 16, "bold"), fill="#fff")

        pinfo = tk.Frame(pc.content, bg=_P["bg_card"])
        pinfo.pack(side="left", fill="x", expand=True)
        tk.Label(pinfo, text=f"{self.user_name}  •  {self.user_phone}",
                 font=("Segoe UI", 10, "bold"),
                 fg=_P["text_hi"], bg=_P["bg_card"]).pack(anchor="w")
        tk.Label(pinfo, text=f"⏱  SOS Countdown: {self.delay_timer.get()}s",
                 font=("Segoe UI", 8),
                 fg=_P["text_mid"], bg=_P["bg_card"]).pack(anchor="w")

        # MacroDroid P1 / P2 entries
        md_card = self._card(parent, accent_color="#7c3aed")
        md_card.pack(fill="x", pady=(0, 8))
        self._section_header(md_card.content, "📡", "MACRODROID DISPATCH CONTACTS", "#7c3aed")

        def _md_entry(label, row_num):
            r = tk.Frame(md_card.content, bg=_P["bg_card"])
            r.pack(fill="x", pady=2)
            tk.Label(r, text=label, font=("Segoe UI", 8, "bold"),
                     fg=_P["text_mid"], bg=_P["bg_card"],
                     width=8).pack(side="left")
            e = tk.Entry(r, font=("Segoe UI", 10),
                         bg=_P["bg_input"], fg=_P["text_hi"],
                         insertbackground=_P["accent"],
                         bd=0, highlightthickness=1,
                         highlightbackground=_P["border"],
                         highlightcolor="#7c3aed")
            e.pack(side="left", fill="x", expand=True, ipady=5)
            e._is_placeholder = False
            return e

        self.p1_entry = _md_entry("P1  (Priority 1)", 0)
        self.p2_entry = _md_entry("P2  (Priority 2)", 1)

        # Pre-fill from contacts if available
        if len(self.contacts) > 0:
            self.p1_entry.insert(0, self.contacts[0]["phone"])
        if len(self.contacts) > 1:
            self.p2_entry.insert(0, self.contacts[1]["phone"])

        tk.Label(md_card.content,
                 text="These numbers are sent live to MacroDroid on SOS dispatch.",
                 font=("Segoe UI", 7), fg=_P["text_dim"],
                 bg=_P["bg_card"]).pack(anchor="w", pady=(4, 0))

        # Contacts card
        cc = self._card(parent, accent_color=_P["accent"])
        cc.pack(fill="both", expand=True, pady=(0, 8))
        self._section_header(cc.content, "👥", "EMERGENCY CONTACTS (by priority)", _P["accent"])
        for idx, item in enumerate(self.contacts, start=1):
            r = tk.Frame(cc.content, bg=_P["bg_card"])
            r.pack(fill="x", pady=3)
            priority_color = _P["red"] if idx == 1 else (_P["amber"] if idx == 2 else _P["text_mid"])
            tk.Label(r, text=f"P{idx}", font=("Segoe UI", 9, "bold"),
                     fg=priority_color, bg=_P["bg_card"],
                     width=3).pack(side="left")
            tk.Label(r, text=f"{item['name']}",
                     font=("Segoe UI", 9, "bold"),
                     fg=_P["text_hi"], bg=_P["bg_card"]).pack(side="left", padx=(4, 0))
            tk.Label(r, text=f"  {item['phone']}",
                     font=("Segoe UI", 8),
                     fg=_P["text_mid"], bg=_P["bg_card"]).pack(side="left")

        # Evidence vault card
        ev = self._card(parent, accent_color="#7c2d12")
        ev.pack(fill="x", pady=(0, 4))
        self._section_header(ev.content, "📁", "EVIDENCE VAULT", "#f97316")
        vf = tk.Frame(ev.content, bg=_P["bg_card"])
        vf.pack(fill="x", pady=4)

        for icon, label, color, folder, attr in [
            ("🎙️", "Audio Vault",  _P["accent"],  os.path.join("recordings", "audio"), "a_count_lbl"),
            ("📹", "Video Vault",  _P["purple"], os.path.join("recordings", "video"),  "v_count_lbl"),
        ]:
            fr = tk.Frame(vf, bg=_P["bg_card2"], cursor="hand2")
            fr.pack(side="left", fill="both", expand=True,
                    padx=(0, 4) if "Audio" in label else (4, 0), ipady=6)
            tk.Label(fr, text=icon, font=("Segoe UI", 18),
                     fg=color, bg=_P["bg_card2"]).pack()
            tk.Label(fr, text=label, font=("Segoe UI", 8, "bold"),
                     fg=color, bg=_P["bg_card2"]).pack()
            cnt = tk.Label(fr, text="0 files", font=("Segoe UI", 7),
                           fg=_P["text_dim"], bg=_P["bg_card2"])
            cnt.pack()
            setattr(self, attr, cnt)
            _folder = folder
            fr.bind("<Button-1>",
                    lambda e, f=_folder, t=label:
                    self.open_folder_contents(f, t))

        threading.Thread(target=self.refresh_media_lists, daemon=True).start()

    # ── Centre column ─────────────────────────────────────────────────────────

    def _build_centre_column(self, parent):
        # Map card
        mc = self._card(parent, accent_color=_P["green"])
        mc.pack(fill="both", expand=True, pady=(0, 8))

        mhdr = tk.Frame(mc.content, bg=_P["bg_card"])
        mhdr.pack(fill="x", pady=(0, 6))
        badge = tk.Canvas(mhdr, width=22, height=22,
                          bg=_P["bg_card"], highlightthickness=0)
        badge.pack(side="left", padx=(0, 6))
        badge.create_oval(1, 1, 21, 21, fill=_P["green"], outline="")
        badge.create_text(11, 11, text="🗺️", font=("Segoe UI", 10))
        tk.Label(mhdr, text="LIVE ROUTE MAP",
                 font=("Segoe UI", 8, "bold"),
                 fg=_P["green"], bg=_P["bg_card"]).pack(side="left")
        tk.Label(mhdr, textvariable=self.speed_indicator_str,
                 font=("Segoe UI", 8, "bold"),
                 fg=_P["amber"], bg=_P["bg_card"]).pack(side="right")

        # Map canvas with gradient background
        self.map_canvas = tk.Canvas(
            mc.content, bg="#0a1628",
            highlightthickness=1, highlightbackground=_P["border"],
            height=240,
        )
        self.map_canvas.pack(fill="both", expand=True)
        self._draw_map_grid()

        # SOS button (full-width, glowing red)
        sos_outer = tk.Frame(parent, bg=_P["bg_root"])
        sos_outer.pack(fill="x", pady=(0, 8))
        sos_btn = tk.Button(
            sos_outer,
            text="🚨  MANUAL SOS TRIGGER",
            font=("Segoe UI", 12, "bold"),
            bg=_P["sos_bg"], fg="#ffffff", bd=0, cursor="hand2",
            activebackground=_P["sos_hover"],
            command=self.trigger_threat,
        )
        sos_btn.pack(fill="x", ipady=12)
        # Hover glow effect
        sos_btn.bind("<Enter>",
                     lambda e: sos_btn.config(bg=_P["sos_hover"]))
        sos_btn.bind("<Leave>",
                     lambda e: sos_btn.config(bg=_P["sos_bg"]))

        # Map simulator launcher
        tk.Button(
            parent,
            text="🗺️  Open Interactive Map Simulator",
            font=("Segoe UI", 9, "bold"),
            bg=_P["bg_card"], fg=_P["accent"],
            bd=0, cursor="hand2",
            highlightthickness=1, highlightbackground=_P["border"],
            command=self.open_map_simulator,
        ).pack(fill="x", ipady=8, pady=(0, 4))

        tk.Button(
            parent, text="🔄  Clear Map Path",
            font=("Segoe UI", 8), bg=_P["bg_card2"],
            fg=_P["text_mid"], bd=0, cursor="hand2",
            command=self.clear_map_display,
        ).pack(fill="x", ipady=5)

    # ── Right telemetry sidebar ───────────────────────────────────────────────

    def _build_telemetry_sidebar(self, parent):
        parent.configure(width=200)
        parent.pack_propagate(False)

        hdr = tk.Frame(parent, bg=_P["bg_panel"],
                       highlightbackground=_P["border"], highlightthickness=1)
        hdr.pack(fill="x", pady=(0, 6))
        tk.Label(hdr, text="⚡ LIVE TELEMETRY",
                 font=("Segoe UI", 9, "bold"),
                 fg=_P["accent"], bg=_P["bg_panel"],
                 pady=8).pack()

        fields = [
            ("⚡ Speed",        self._tele_speed,    _P["amber"]),
            ("📏 Seg. Dist",    self._tele_seg_dist, _P["text_hi"]),
            ("🛣 Trip Dist",    self._tele_cum_dist, _P["text_hi"]),
            ("🤖 Pred. Lat",   self._tele_pred_lat, _P["predict"]),
            ("🤖 Pred. Lon",   self._tele_pred_lon, _P["predict"]),
            ("🎯 Confidence",   self._tele_conf,     _P["predict"]),
            ("📶 Network",      self._tele_network,  _P["green"]),
            ("🛡 Status",       self._tele_threat,   _P["green"]),
        ]
        for label, var, color in fields:
            row = tk.Frame(parent, bg=_P["bg_card"],
                           highlightbackground=_P["border"],
                           highlightthickness=1)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=("Segoe UI", 7, "bold"),
                     fg=_P["text_dim"], bg=_P["bg_card"],
                     anchor="w", width=12).pack(side="left",
                                                padx=(6, 2), pady=4)
            tk.Label(row, textvariable=var, font=("Segoe UI", 8, "bold"),
                     fg=color, bg=_P["bg_card"],
                     anchor="w").pack(side="left", padx=(0, 6))

        # Separator
        tk.Frame(parent, bg=_P["border"], height=1).pack(fill="x", pady=8)

        # Geofence
        geo_card = self._card(parent, accent_color=_P["green"])
        geo_card.pack(fill="x", pady=2)
        self._section_header(geo_card.content, "📍", "SAFE ZONES", _P["green"])
        tk.Label(geo_card.content,
                 text=f"Zones: {', '.join(self.safe_locations)}",
                 font=("Segoe UI", 7), fg=_P["text_mid"],
                 bg=_P["bg_card"]).pack(anchor="w")

        # Hardware telemetry
        hw_card = self._card(parent, accent_color=_P["accent"])
        hw_card.pack(fill="x", pady=(4, 0))
        self._section_header(hw_card.content, "📱", "HARDWARE", _P["accent"])
        tk.Label(hw_card.content, textvariable=self.signal_status_str,
                 font=("Segoe UI", 8), fg=_P["green"],
                 bg=_P["bg_card"]).pack(anchor="w")
        tk.Label(hw_card.content, textvariable=self.battery_status_str,
                 font=("Segoe UI", 8), fg=_P["amber"],
                 bg=_P["bg_card"]).pack(anchor="w")

    # ═══════════════════════════════════════════════════════════════════════════
    # 5 – VAULT DIALOG
    # ═══════════════════════════════════════════════════════════════════════════

    def open_folder_contents(self, folder_path, title):
        dlg = tk.Toplevel(self.root)
        dlg.title(f"📁 {title}")
        dlg.geometry("520x400")
        dlg.configure(bg=_P["bg_panel"])
        dlg.transient(self.root)

        tk.Label(dlg, text=f"📁 {title.upper()}",
                 font=("Segoe UI", 10, "bold"),
                 fg=_P["accent"], bg=_P["bg_panel"]).pack(pady=10)

        lb = tk.Listbox(dlg, font=("Segoe UI", 9),
                        bg="#161b22", fg="#f8fafc",
                        selectbackground=_P["accent"], bd=0)
        lb.pack(fill="both", expand=True, padx=15, pady=5)

        files = sorted(glob.glob(os.path.join(folder_path, "*.*")), reverse=True)
        for f in files:
            lb.insert(tk.END, os.path.basename(f))

        bf = tk.Frame(dlg, bg=_P["bg_panel"])
        bf.pack(fill="x", padx=15, pady=10)

        def play():
            sel = lb.curselection()
            if not sel:
                return
            fname = lb.get(sel[0])
            fpath = os.path.abspath(os.path.join(folder_path, fname))
            if not os.path.exists(fpath):
                messagebox.showerror("File Missing", f"'{fname}' no longer exists.")
                lb.delete(sel[0])
                return
            try:
                if platform.system() == "Windows":  os.startfile(fpath)
                elif platform.system() == "Darwin":  subprocess.Popen(["open", fpath])
                else:                                subprocess.Popen(["xdg-open", fpath])
            except Exception as e:
                messagebox.showerror("Playback Error", str(e))

        def delete():
            sel = lb.curselection()
            if not sel:
                return
            fname = lb.get(sel[0])
            if messagebox.askyesno("Delete", f"Permanently delete '{fname}'?"):
                try:
                    os.remove(os.path.join(folder_path, fname))
                    lb.delete(sel[0])
                    threading.Thread(target=self.refresh_media_lists,
                                     daemon=True).start()
                except Exception as e:
                    messagebox.showerror("Delete Error", str(e))

        tk.Button(bf, text="▶ Play", font=("Segoe UI", 8, "bold"),
                  bg=_P["accent"], fg=_P["bg_root"],
                  bd=0, command=play, width=12).pack(side="left", padx=4)
        tk.Button(bf, text="🗑 Delete", font=("Segoe UI", 8, "bold"),
                  bg=_P["red"], fg="#fff",
                  bd=0, command=delete, width=12).pack(side="left", padx=4)

    def refresh_media_lists(self):
        a = len(glob.glob(os.path.join("recordings", "audio", "*.*")))
        v = len(glob.glob(os.path.join("recordings", "video", "*.*")))
        def _upd():
            if hasattr(self, "a_count_lbl") and self.a_count_lbl.winfo_exists():
                self.a_count_lbl.config(text=f"{a} recorded")
            if hasattr(self, "v_count_lbl") and self.v_count_lbl.winfo_exists():
                self.v_count_lbl.config(text=f"{v} recorded")
        self.root.after(0, _upd)

    # ═══════════════════════════════════════════════════════════════════════════
    # 6 – SETTINGS DIALOG
    # ═══════════════════════════════════════════════════════════════════════════

    def open_settings_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("⚙️ AURA System Settings")
        dlg.geometry("580x700")
        dlg.configure(bg=_P["bg_panel"])
        dlg.transient(self.root)
        dlg.grab_set()

        title_row = tk.Frame(dlg, bg=_P["bg_panel"])
        title_row.pack(pady=12)
        tb = tk.Canvas(title_row, width=28, height=28,
                       bg=_P["bg_panel"], highlightthickness=0)
        tb.pack(side="left", padx=(0, 8))
        tb.create_oval(1, 1, 27, 27, fill=_P["accent"], outline="")
        tb.create_text(14, 14, text="⚙️", font=("Segoe UI", 12))
        tk.Label(title_row, text="SYSTEM CONFIGURATION",
                 font=("Segoe UI", 12, "bold"),
                 fg=_P["accent"], bg=_P["bg_panel"]).pack(side="left")

        frm = tk.Frame(dlg, bg=_P["bg_panel"], padx=22)
        frm.pack(fill="both", expand=True)

        usr_row = tk.Frame(frm, bg=_P["bg_panel"])
        usr_row.pack(fill="x", pady=(2, 8))

        # User Name col
        u_col = tk.Frame(usr_row, bg=_P["bg_panel"])
        u_col.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Label(u_col, text="REGISTERED USER NAME",
                 font=("Segoe UI", 8, "bold"),
                 fg=_P["accent2"], bg=_P["bg_panel"]).pack(anchor="w")
        e_name = tk.Entry(u_col, font=("Segoe UI", 10),
                          bg=_P["bg_input"], fg=_P["text_hi"], bd=0)
        e_name.insert(0, self.user_name)
        e_name.pack(fill="x", ipady=5, pady=(2, 0))

        # User Phone col
        p_col = tk.Frame(usr_row, bg=_P["bg_panel"])
        p_col.pack(side="right", fill="x", expand=True, padx=(6, 0))
        tk.Label(p_col, text="USER PHONE (10-DIGIT)",
                 font=("Segoe UI", 8, "bold"),
                 fg=_P["accent2"], bg=_P["bg_panel"]).pack(anchor="w")
        e_phone = tk.Entry(p_col, font=("Segoe UI", 10),
                           bg=_P["bg_input"], fg=_P["text_hi"], bd=0)
        e_phone.insert(0, self.user_phone)
        e_phone.pack(fill="x", ipady=5, pady=(2, 0))

        # PINs & Timer row
        sec_row = tk.Frame(frm, bg=_P["bg_panel"])
        sec_row.pack(fill="x", pady=(2, 10))

        # Real PIN col
        rpin_col = tk.Frame(sec_row, bg=_P["bg_panel"])
        rpin_col.pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Label(rpin_col, text="REAL DISARM PIN",
                 font=("Segoe UI", 8, "bold"),
                 fg=_P["green"], bg=_P["bg_panel"]).pack(anchor="w")
        e_real_pin = tk.Entry(rpin_col, font=("Segoe UI", 10),
                              bg=_P["bg_input"], fg=_P["text_hi"], bd=0)
        e_real_pin.insert(0, getattr(self, "real_pin", "1234"))
        e_real_pin.pack(fill="x", ipady=5, pady=(2, 0))

        # Duress Fake PIN col
        fpin_col = tk.Frame(sec_row, bg=_P["bg_panel"])
        fpin_col.pack(side="left", fill="x", expand=True, padx=4)
        tk.Label(fpin_col, text="DURESS FAKE PIN",
                 font=("Segoe UI", 8, "bold"),
                 fg=_P["red"], bg=_P["bg_panel"]).pack(anchor="w")
        e_fake_pin = tk.Entry(fpin_col, font=("Segoe UI", 10),
                              bg=_P["bg_input"], fg=_P["text_hi"], bd=0)
        e_fake_pin.insert(0, getattr(self, "fake_pin", "9999"))
        e_fake_pin.pack(fill="x", ipady=5, pady=(2, 0))

        # Timer col
        tmr_col = tk.Frame(sec_row, bg=_P["bg_panel"])
        tmr_col.pack(side="right", fill="x", expand=True, padx=(4, 0))
        tk.Label(tmr_col, text="SOS COUNTDOWN",
                 font=("Segoe UI", 8, "bold"),
                 fg=_P["amber"], bg=_P["bg_panel"]).pack(anchor="w")
        spin = tk.Spinbox(tmr_col, from_=5, to=60, increment=5,
                          textvariable=self.delay_timer,
                          font=("Segoe UI", 10, "bold"),
                          bg=_P["bg_input"], fg=_P["amber"], bd=0)
        spin.pack(fill="x", ipady=5, pady=(2, 0))

        # Contacts
        contacts_hdr = tk.Frame(frm, bg=_P["bg_panel"])
        contacts_hdr.pack(fill="x", pady=(6, 6))
        tk.Label(contacts_hdr,
                 text="EMERGENCY CONTACTS  (top = highest priority)",
                 font=("Segoe UI", 8, "bold"),
                 fg=_P["accent2"], bg=_P["bg_panel"]).pack(side="left")

        contacts_frame = tk.Frame(frm, bg=_P["bg_panel"])
        contacts_frame.pack(fill="x", pady=4)

        settings_contact_rows = []

        def render_contact_rows():
            for r in settings_contact_rows:
                r["frame"].destroy()
            settings_contact_rows.clear()
            for idx, contact in enumerate(self.contacts):
                row = tk.Frame(contacts_frame, bg=_P["bg_card2"])
                row.pack(fill="x", pady=3, ipady=3)
                tk.Label(row, text=f"P{idx+1}",
                         font=("Segoe UI", 9, "bold"),
                         fg=_P["amber"], bg=_P["bg_card2"],
                         width=3).pack(side="left", padx=(4, 4))
                ec_n = tk.Entry(row, font=("Segoe UI", 9),
                                bg=_P["bg_input"], fg=_P["text_hi"],
                                bd=0, width=16)
                ec_n.insert(0, contact["name"])
                ec_n.pack(side="left", padx=2, ipady=4)
                ec_p = tk.Entry(row, font=("Segoe UI", 9),
                                bg=_P["bg_input"], fg=_P["text_hi"],
                                bd=0, width=13)
                ec_p.insert(0, contact["phone"])
                ec_p.pack(side="left", padx=2, ipady=4)

                def _up(i=idx):
                    if i > 0:
                        self.contacts[i-1], self.contacts[i] = \
                            self.contacts[i], self.contacts[i-1]
                        render_contact_rows()

                def _down(i=idx):
                    if i < len(self.contacts) - 1:
                        self.contacts[i+1], self.contacts[i] = \
                            self.contacts[i], self.contacts[i+1]
                        render_contact_rows()

                def _del(i=idx):
                    self.contacts.pop(i)
                    render_contact_rows()

                for lbl, cmd in [("↑", _up), ("↓", _down), ("✖", _del)]:
                    bg = _P["red"] if lbl == "✖" else "#334155"
                    tk.Button(row, text=lbl,
                              font=("Segoe UI", 8, "bold"),
                              bg=bg, fg="#fff", bd=0, width=2,
                              command=cmd).pack(side="left", padx=1)

                settings_contact_rows.append({
                    "frame": row, "name_entry": ec_n, "phone_entry": ec_p})

        render_contact_rows()

        tk.Button(frm, text="+ Add Emergency Contact",
                  font=("Segoe UI", 8, "bold"),
                  bg=_P["accent"], fg=_P["bg_root"],
                  bd=0, cursor="hand2", pady=4,
                  command=lambda: [
                      self.contacts.append({"name": "New Contact",
                                            "phone": "0000000000"}),
                      render_contact_rows()
                  ]).pack(fill="x", pady=(4, 16))

        self._section_header(frm, "📍", "SAFE ZONES", _P["green"])
        zones_frame = tk.Frame(frm, bg=_P["bg_panel"])
        zones_frame.pack(fill="x", pady=(0, 5))

        def render_zone_rows():
            for w in zones_frame.winfo_children():
                w.destroy()
            zones = self.controller.safe_zones if self.controller else []
            if not zones:
                tk.Label(zones_frame,
                         text="No safe zones — geofencing OFF.",
                         font=("Segoe UI", 8), fg=_P["text_dim"],
                         bg=_P["bg_panel"]).pack(anchor="w")
                return
            for idx, zone in enumerate(zones):
                row = tk.Frame(zones_frame, bg=_P["bg_card2"])
                row.pack(fill="x", pady=2, ipady=3)
                tk.Label(row,
                         text=f"📍 {zone['name']} (r={zone['radius_km']} km)",
                         font=("Segoe UI", 8),
                         fg=_P["text_hi"], bg=_P["bg_card2"]).pack(side="left", padx=6)

                def _del_zone(i=idx):
                    self.controller.remove_safe_zone(i)
                    render_zone_rows()

                tk.Button(row, text="✖", font=("Segoe UI", 8, "bold"),
                          bg=_P["red"], fg="#fff", bd=0, width=2,
                          command=_del_zone).pack(side="right", padx=4)

        render_zone_rows()

        def _add_zone():
            if not self.controller:
                messagebox.showerror("Error", "Controller not connected.")
                return
            zd = tk.Toplevel(dlg)
            zd.title("Add Safe Zone")
            zd.geometry("310x230")
            zd.configure(bg=_P["bg_panel"])
            zd.transient(dlg)
            zd.grab_set()
            tk.Label(zd, text="ZONE NAME", font=("Segoe UI", 8, "bold"),
                     fg=_P["accent2"], bg=_P["bg_panel"]).pack(anchor="w", padx=16, pady=(14, 2))
            ez = tk.Entry(zd, font=("Segoe UI", 10),
                          bg=_P["bg_input"], fg=_P["text_hi"], bd=0)
            ez.insert(0, "Home")
            ez.pack(fill="x", ipady=6, padx=16)
            tk.Label(zd, text="RADIUS (KM)", font=("Segoe UI", 8, "bold"),
                     fg=_P["accent2"], bg=_P["bg_panel"]).pack(anchor="w", padx=16, pady=(10, 2))
            er = tk.Entry(zd, font=("Segoe UI", 10),
                          bg=_P["bg_input"], fg=_P["text_hi"], bd=0)
            er.insert(0, "0.5")
            er.pack(fill="x", ipady=6, padx=16)
            tk.Label(zd, text="Uses the current simulated location as zone centre.",
                     font=("Segoe UI", 7), fg=_P["text_dim"],
                     bg=_P["bg_panel"], justify="left").pack(anchor="w", padx=16, pady=6)

            def _confirm():
                name = ez.get().strip()
                try:
                    radius = float(er.get().strip())
                except ValueError:
                    messagebox.showerror("Error", "Radius must be a number.")
                    return
                if not name:
                    messagebox.showerror("Error", "Enter a zone name.")
                    return
                current = self.controller.location_engine.get_current_location()
                self.controller.add_safe_zone(
                    name, current["latitude"], current["longitude"], radius)
                zd.destroy()
                render_zone_rows()

            tk.Button(zd, text="ADD ZONE",
                      font=("Segoe UI", 9, "bold"),
                      bg=_P["green"], fg="#fff", bd=0,
                      command=_confirm).pack(fill="x", padx=16, pady=12, ipady=6)

        tk.Button(frm, text="+ Add Current Location as Safe Zone",
                  font=("Segoe UI", 8, "bold"),
                  bg=_P["accent"], fg=_P["bg_root"],
                  bd=0, cursor="hand2", pady=4,
                  command=_add_zone).pack(fill="x", pady=(4, 16))

        self._section_header(frm, "🧪", "DEMO / TESTING", _P["text_dim"])
        tk.Button(frm, text="🧪 Test SOS Alert",
                  font=("Segoe UI", 8),
                  bg="#334155", fg=_P["text_mid"],
                  bd=0, cursor="hand2", pady=4,
                  command=lambda: [dlg.destroy(),
                                   self.trigger_threat("💥 TEST ALERT")]).pack(
                  fill="x", pady=(0, 14))

        def _save():
            for i, row in enumerate(settings_contact_rows):
                nv = row["name_entry"].get().strip()
                pv = row["phone_entry"].get().strip()
                if not nv or not self.is_valid_phone(pv):
                    messagebox.showerror(
                        "Validation Error",
                        f"Row {i+1}: valid name and 10-digit number required.")
                    return
                self.contacts[i] = {"name": nv, "phone": pv}
            if not self.contacts:
                messagebox.showerror("Error", "Keep at least one contact.")
                return

            phone_val = e_phone.get().strip()
            if phone_val and not self.is_valid_phone(phone_val):
                messagebox.showerror("Validation Error", "User phone must be a valid 10-digit number.")
                return

            r_pin = e_real_pin.get().strip()
            f_pin = e_fake_pin.get().strip()
            if not r_pin or not f_pin or r_pin == f_pin:
                messagebox.showerror("PIN Error", "Real PIN and Duress Fake PIN must both be set and must not be identical.")
                return

            self.user_name = e_name.get().strip()
            self.user_phone = phone_val
            self.real_pin = r_pin
            self.fake_pin = f_pin
            self.save_user_profile()
            if self.controller:
                self.controller.set_emergency_contacts(
                    [c["phone"] for c in self.contacts])
                self.controller.set_pins(self.real_pin, self.fake_pin)
            dlg.destroy()
            self.build_modern_dashboard(
                pending_notification="⚙️ Settings Updated Successfully!")

        tk.Button(dlg, text="SAVE CHANGES",
                  font=("Segoe UI", 10, "bold"),
                  bg=_P["green"], fg="#fff", bd=0,
                  command=_save).pack(fill="x", ipady=9, padx=22, pady=14)

    # ═══════════════════════════════════════════════════════════════════════════
    # 7 – THREAT TIMER & SOS DISPATCH
    # ═══════════════════════════════════════════════════════════════════════════

    def trigger_threat(self, reason_msg="⚠️ CRITICAL THREAT DETECTED ⚠️"):
        if self.is_threat_active:
            return
        if not self.is_protection_active:
            self.is_protection_active = True

        def _beep():
            try:
                import winsound
                winsound.Beep(1200, 150)
                winsound.Beep(1600, 150)
            except Exception:
                print("\a")
        threading.Thread(target=_beep, daemon=True).start()

        self.is_threat_active = True
        self.total_time = self.delay_timer.get()
        self.time_left  = self.total_time

        self.clear_container()

        threat_frame = tk.Frame(self.main_container, bg=_P["threat_bg"])
        threat_frame.pack(fill="both", expand=True)

        center_box = tk.Frame(threat_frame, bg=_P["threat_bg"])
        center_box.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(center_box, text=reason_msg,
                 font=("Segoe UI", 18, "bold"),
                 fg=_P["threat_fg"], bg=_P["threat_bg"]).pack(pady=(0, 12))

        self.canvas_size  = 240
        self.timer_canvas = tk.Canvas(
            center_box, width=self.canvas_size, height=self.canvas_size,
            bg=_P["threat_bg"], highlightthickness=0,
        )
        self.timer_canvas.pack(pady=10)

        tk.Button(
            center_box, text="🛡️  I AM SAFE  (DISMISS ALARM)",
            font=("Segoe UI", 12, "bold"),
            bg=_P["green"], fg="#ffffff", bd=0, cursor="hand2",
            padx=20, 
            command=lambda: self.dismiss_alarm("User confirmed safe"),
        ).pack(fill="x", pady=18,ipady=12)

        if self.controller:
            self.controller.start_emergency_recording()

        self.run_timer()

    def draw_circular_timer(self):
        self.timer_canvas.delete("all")
        cx = cy = self.canvas_size / 2
        r = 90

        # Outer glow ring
        for offset in (14, 10, 6):
            self.timer_canvas.create_oval(
                cx - r - offset, cy - r - offset,
                cx + r + offset, cy + r + offset,
                outline="#7f1d1d", width=1)

        # Background arc
        self.timer_canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            outline="#7f1d1d", width=14)

        # Countdown arc
        if self.total_time > 0:
            angle = (self.time_left / self.total_time) * 360
            self.timer_canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=90, extent=-angle,
                outline=_P["red"], width=14, style="arc")

        # Centre label
        self.timer_canvas.create_text(
            cx, cy, text=f"{self.time_left}s",
            font=("Segoe UI", 36, "bold"), fill="#ffffff")

    def run_timer(self):
        if not self.is_threat_active:
            return
        if self.time_left >= 0:
            self.draw_circular_timer()
            if self.time_left == 0:
                self.dispatch_sos()
            else:
                self.time_left -= 1
                self.timer_job = self.root.after(1000, self.run_timer)

    def dismiss_alarm(self, reason):
        if not self.is_protection_active:
            return
        self.is_threat_active = False
        if self.timer_job:
            self.root.after_cancel(self.timer_job)
        self.send_desktop_popup("✅ Alarm Dismissed", "User confirmed safe.")
        self.build_modern_dashboard(
            pending_notification=f"✅ Alarm Dismissed! ({reason})")

    def dispatch_sos(self):
        """
        Core SOS dispatch.  Reads P1 / P2 numbers LIVE from the
        self.p1_entry / self.p2_entry widgets (set on the dashboard).
        Falls back to self.contacts[0..1] if the entries are absent.
        Fires trigger_aura_sos() in a daemon thread — UI never blocks.
        """
        if not self.is_protection_active:
            return

        self.is_threat_active = False
        if self.timer_job:
            self.root.after_cancel(self.timer_job)

        # --- Gather location dynamically ---
        current_loc = {}
        if self.controller:
            try:
                current_loc = self.controller.location_engine.get_current_location()
                self.controller.execute_emergency_sequence(
                    "MANUAL_SOS_TIMEOUT", current_loc)
            except Exception as e:
                print(f"[SOS Dispatch Error] {e}")

        lat = current_loc.get("latitude")
        lon = current_loc.get("longitude")
        if lat is None or lon is None:
            if self.controller and hasattr(self.controller, "predictor"):
                summary = self.controller.predictor.get_history_summary()
                lat = summary.get("last_known_lat", 0.0)
                lon = summary.get("last_known_lon", 0.0)
            else:
                lat, lon = 0.0, 0.0

        # --- Resolve P1 / P2 dynamically from UI entries ---
        def _read_entry(entry_widget, fallback=""):
            if entry_widget is not None and hasattr(entry_widget, "get"):
                val = entry_widget.get().strip()
                if val and not getattr(entry_widget, "_is_placeholder", False):
                    return val
            return fallback

        fb_p1 = self.contacts[0]["phone"] if self.contacts else ""
        fb_p2 = self.contacts[1]["phone"] if len(self.contacts) > 1 else ""
        p1_val = _read_entry(self.p1_entry, fb_p1)
        p2_val = _read_entry(self.p2_entry, fb_p2)

        # --- Fire webhook in background thread ---
        threading.Thread(
            target=trigger_aura_sos,
            args=(p1_val, p2_val, lat, lon),
            daemon=True,
            name="SOS-Dispatch",
        ).start()

        # --- UI feedback ---
        if not getattr(self, "is_fake_shutdown", False):
            self.send_desktop_popup(
                "🚨 INSTANT SOS DISPATCHED!",
                f"Alert sent to P1={p1_val or '—'}, P2={p2_val or '—'}")
            self.build_modern_dashboard(
                pending_notification="🚨 EMERGENCY ALERT DISPATCHED!",
                is_error=True)
            self.root.after(
                5000,
                lambda: threading.Thread(
                    target=self.refresh_media_lists, daemon=True).start())

    # ═══════════════════════════════════════════════════════════════════════════
    # 8 – FAKE SHUTDOWN (F8 / duress)
    # ═══════════════════════════════════════════════════════════════════════════

    def trigger_fake_shutdown(self, event=None):
        if getattr(self, "is_fake_shutdown", False):
            return
        self.is_fake_shutdown = True
        if self.controller:
            self.controller.stealth_active = True

        self.shutdown_win = tk.Toplevel(self.root)
        self.shutdown_win.attributes("-fullscreen", True)
        self.shutdown_win.configure(bg="black")
        self.shutdown_win.overrideredirect(True)
        self.shutdown_win.attributes("-topmost", True)
        self.shutdown_win.focus_force()

        msg_frame = tk.Frame(self.shutdown_win, bg="black")
        msg_frame.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(msg_frame, text="Shutting down…",
                 font=("Segoe UI", 22), fg="white", bg="black").pack()

        def _black():
            if hasattr(self, "shutdown_win") and self.shutdown_win \
                    and self.shutdown_win.winfo_exists():
                for w in msg_frame.winfo_children():
                    w.destroy()

        self.root.after(3000, _black)
        self.shutdown_win.bind_all("<F9>", lambda e: self.exit_fake_shutdown())
        print("[Fake Shutdown] Activated. Background SOS running.")
        self.dispatch_sos()

    def exit_fake_shutdown(self, event=None):
        if hasattr(self, "shutdown_win") and self.shutdown_win:
            try:
                self.shutdown_win.unbind_all("<F9>")
                self.shutdown_win.destroy()
            except Exception:
                pass
        self.shutdown_win    = None
        self.is_fake_shutdown = False
        if self.controller:
            self.controller.stealth_active = False
        print("[Fake Shutdown] Exit complete.")

    # ═══════════════════════════════════════════════════════════════════════════
    # 9 – VOICE HANDLER
    # ═══════════════════════════════════════════════════════════════════════════

    def handle_voice_event(self, action, word):
        if not self.is_protection_active:
            return
        if action == "TRIGGER":
            self.root.after(0, self.trigger_threat)
        elif action == "CANCEL" and self.is_threat_active:
            self.root.after(0, lambda: self.dismiss_alarm(f"Voice ('{word}')"))

    # ═══════════════════════════════════════════════════════════════════════════
    # 10 – MAP CANVAS RENDERING
    # ═══════════════════════════════════════════════════════════════════════════

    def _draw_map_grid(self):
        self.map_canvas.update_idletasks()
        w = self.map_canvas.winfo_width() or 460
        h = self.map_canvas.winfo_height() or 240
        step = 40
        for i in range(0, w, step):
            self.map_canvas.create_line(i, 0, i, h,
                                        fill="#0f1d33", tags="grid")
        for i in range(0, h, step):
            self.map_canvas.create_line(0, i, w, i,
                                        fill="#0f1d33", tags="grid")
        # Landmarks on the mini-map dynamically retrieved from safe zones
        dynamic_landmarks = map_config.get_dynamic_landmarks(self.controller)
        for label, (llat, llon) in dynamic_landmarks.items():
            lx, ly = map_config.latlon_to_pixel(llat, llon, w)
            self.map_canvas.create_oval(lx - 5, ly - 5, lx + 5, ly + 5,
                                        fill=_P["green"], outline="",
                                        tags="grid")
            self.map_canvas.create_text(lx, ly - 12, text=label,
                                        fill=_P["text_mid"],
                                        font=("Segoe UI", 6),
                                        tags="grid")

    def update_map_canvas(self, lat, lon, predicted, speed_kmh, is_threat):
        """
        Called by main_controller every safety cycle.  Now also pulls
        Haversine segment distance and LSTM confidence from the predictor
        and updates the live telemetry sidebar.
        """
        if not hasattr(self, "map_canvas") or not self.map_canvas.winfo_exists():
            return

        if lat and lon and not (lat == 0.0 and lon == 0.0):
            if abs(lat - map_config.CENTER_LAT) > map_config.ZOOM_SPAN_DEGREES * 0.45 or \
               abs(lon - map_config.CENTER_LON) > map_config.ZOOM_SPAN_DEGREES * 0.45:
                map_config.set_map_center(lat, lon)

        w  = self.map_canvas.winfo_width()  or 460
        h  = self.map_canvas.winfo_height() or 240
        sz = min(w, h)
        px, py = map_config.latlon_to_pixel(lat, lon, sz)

        # Trail
        if self.map_trail_points:
            lx, ly = self.map_trail_points[-1]
            self.map_canvas.create_line(
                lx, ly, px, py,
                fill=_P["red"], width=2, tags="trail")
        self.map_trail_points.append((px, py))

        # Current position marker
        self.map_canvas.delete("current_marker")
        mc = _P["amber"] if is_threat else _P["red"]
        self.map_canvas.create_oval(
            px - 7, py - 7, px + 7, py + 7,
            fill=mc, outline="#fff", width=1,
            tags="current_marker")

        # Predicted marker
        self.map_canvas.delete("predicted_marker")
        if predicted:
            p_lat = predicted.get("predicted_latitude") or predicted.get("latitude")
            p_lon = predicted.get("predicted_longitude") or predicted.get("longitude")
            if p_lat is not None and p_lon is not None:
                ppx, ppy = map_config.latlon_to_pixel(p_lat, p_lon, sz)
                self.map_canvas.create_oval(
                    ppx - 9, ppy - 9, ppx + 9, ppy + 9,
                    outline=_P["predict"], width=2,
                    tags="predicted_marker")

        # Telemetry sidebar
        self.speed_indicator_str.set(f"Speed: {speed_kmh} km/h")
        self._tele_speed.set(f"{speed_kmh} km/h")

        # Pull extra stats from predictor if available
        if self.controller and hasattr(self.controller, "predictor"):
            try:
                summary = self.controller.predictor.get_history_summary()
                self._tele_seg_dist.set(
                    f"{summary.get('last_segment_m', 0.0):.1f} m")
                self._tele_cum_dist.set(
                    f"{summary.get('cumulative_distance_km', 0.0):.3f} km")
                pred2 = self.controller.predictor.predict_next_coordinate()
                if pred2:
                    self._tele_pred_lat.set(
                        f"{pred2.get('predicted_latitude', '--'):.5f}")
                    self._tele_pred_lon.set(
                        f"{pred2.get('predicted_longitude', '--'):.5f}")
                    self._tele_conf.set(
                        f"{pred2.get('confidence', 0.0) * 100:.1f}%")
            except Exception:
                pass

        # Threat status badge
        if is_threat:
            self._tele_threat.set("● THREAT ⚠️")
        else:
            self._tele_threat.set("● MONITORING")

        # Network status
        if self.controller and hasattr(self.controller, "phone_has_signal"):
            sig = self.controller.phone_has_signal
            self._tele_network.set("Online ✅" if sig else "Offline ⚠️")

    def clear_map_display(self):
        if hasattr(self, "map_canvas") and self.map_canvas.winfo_exists():
            self.map_canvas.delete("trail", "current_marker", "predicted_marker")
        self.map_trail_points = []
        self.speed_indicator_str.set("Speed: -- km/h")
        self._tele_speed.set("-- km/h")

    def open_map_simulator(self):
        if not self.controller:
            messagebox.showwarning(
                "No Controller",
                "Map Simulator requires the Safety Controller to be running.")
            return
        try:
            map_simulator.open_map_simulator(self.root, self.controller)
        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("Map Simulator Error",
                                 f"Could not open Map Simulator:\n\n{e}")


# ── Standalone test entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app  = ModernSafetyApp(root)
    root.mainloop()