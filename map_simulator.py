"""
map_simulator.py
──────────────────────────────────────────────────────────────────────────
Advanced Interactive Map Simulator — Production Edition

Features:
  • High-resolution canvas map with gradient road rendering, pulsing
    position marker, trail colour-coding, and predicted-WP beacon.
  • Zero visible control buttons on the main canvas area.
    All demo interactions are keyboard-only (hotkeys):

      Arrow Keys  — Move position smoothly one step in that direction
      D           — Trigger dynamic route deviation (±250 m sideways jump)
      S           — Boost simulation speed  (cycles through x1 → x4 → x8 → x1)
      R           — Reset route to start

  • Telemetry sidebar shows:  Speed · Haversine dist · Predicted WP ·
    Network indicator (pulled from controller).
  • Backwards-compatible with main_controller.py:
        map_simulator.open_map_simulator(parent_root, controller)
"""

import math
import time
import threading
import tkinter as tk
from tkinter import ttk

import map_config

# ── Canvas / layout constants ─────────────────────────────────────────────────
CANVAS_W         = 480
CANVAS_H         = 480
TELEMETRY_W      = 200
WIN_W            = CANVAS_W + TELEMETRY_W + 30  # canvas + sidebar + padding
WIN_H            = 640
CUSTOM_ROUTE_LABEL = "✏️ Custom Route (Click Map)"

# Hotkey step sizes in degrees (≈ 20 m at this latitude)
LAT_STEP = 0.00018
LON_STEP = 0.00022

# Speed multiplier presets (visual tick interval scales inversely)
SPEED_PRESETS = [1, 2, 4, 8]

# Colour palette
C_BG         = "#0a0f1e"
C_SURFACE    = "#111827"
C_PANEL      = "#161f30"
C_BORDER     = "#1e3a5f"
C_ACCENT     = "#38bdf8"
C_ROAD       = "#2563eb"
C_ROAD_DIM   = "#1d4ed8"
C_TRAIL      = "#ef4444"
C_TRAIL_OLD  = "#7f1d1d"
C_MARKER     = "#f97316"
C_MARKER_RIM = "#ffffff"
C_PREDICT    = "#facc15"
C_LANDMARK   = "#10b981"
C_TEXT_HI    = "#f1f5f9"
C_TEXT_MID   = "#94a3b8"
C_TEXT_DIM   = "#475569"
C_THREAT     = "#dc2626"
C_SAFE       = "#10b981"
C_DEVIATE    = "#a855f7"


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class MapSimulatorWindow:
    """Full-featured interactive map simulation window."""

    def __init__(self, parent_root, controller):
        self.controller      = controller
        self.route_points    = []
        self.current_index   = 0
        self.is_playing      = False
        self.play_job        = None
        self.simulated_clock = time.time()
        self._speed_idx      = 0          # index into SPEED_PRESETS
        self._deviation_active = False
        self._pulse_phase    = 0.0        # for marker animation
        self._trail_coords   = []         # list of (px, py) drawn so far

        # ── Window setup ──────────────────────────────────────────────────────
        self.win = tk.Toplevel(parent_root)
        self.win.title("AURA — Live Map Intelligence")
        self.win.geometry(f"{WIN_W}x{WIN_H}+60+20")
        self.win.configure(bg=C_BG)
        self.win.resizable(False, False)
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.win.after(250, lambda: self.win.attributes("-topmost", False))

        self._build_ui()
        self._bind_hotkeys()
        self._load_route()
        self._start_pulse_animation()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Header bar
        hdr = tk.Frame(self.win, bg=C_SURFACE, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        badge = tk.Canvas(hdr, width=28, height=28, bg=C_SURFACE,
                          highlightthickness=0)
        badge.pack(side="left", padx=(12, 6), pady=8)
        badge.create_oval(2, 2, 26, 26, fill=C_ACCENT, outline="")
        badge.create_text(14, 14, text="🗺", font=("Segoe UI", 12))

        tk.Label(hdr, text="AURA LIVE MAP INTELLIGENCE",
                 font=("Segoe UI", 11, "bold"), fg=C_ACCENT,
                 bg=C_SURFACE).pack(side="left")

        self._hotkey_hint = tk.Label(
            hdr,
            text="  ↑↓←→ Move  |  D Deviate  |  S Speed  |  R Reset",
            font=("Segoe UI", 8), fg=C_TEXT_DIM, bg=C_SURFACE,
        )
        self._hotkey_hint.pack(side="right", padx=12)

        # Main body: canvas + telemetry sidebar
        body = tk.Frame(self.win, bg=C_BG)
        body.pack(fill="both", expand=True, padx=10, pady=(6, 0))

        # Map canvas
        self.canvas = tk.Canvas(
            body, width=CANVAS_W, height=CANVAS_H,
            bg=C_BG, highlightthickness=1,
            highlightbackground=C_BORDER,
        )
        self.canvas.pack(side="left")
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # Telemetry sidebar
        self._build_telemetry_sidebar(body)

        # Bottom control bar (route dropdown + status — no movement buttons)
        ctrl = tk.Frame(self.win, bg=C_PANEL, padx=10, pady=8)
        ctrl.pack(fill="x", padx=10, pady=(8, 4))

        tk.Label(ctrl, text="ROUTE", font=("Segoe UI", 8, "bold"),
                 fg="#818cf8", bg=C_PANEL).pack(side="left", padx=(0, 6))

        route_options = list(map_config.get_dynamic_routes(self.controller).keys()) + [CUSTOM_ROUTE_LABEL]
        self.route_var = tk.StringVar(value=route_options[0])
        route_dd = ttk.Combobox(ctrl, textvariable=self.route_var,
                                values=route_options, state="readonly",
                                font=("Segoe UI", 9), width=36)
        route_dd.pack(side="left", padx=(0, 10))
        route_dd.bind("<<ComboboxSelected>>", lambda e: self._on_route_change())

        # Play / Pause button (only one visible button, kept for accessibility)
        self.play_btn = tk.Button(
            ctrl, text="▶ Play", font=("Segoe UI", 9, "bold"),
            bg=C_SAFE, fg="#ffffff", bd=0, cursor="hand2",
            command=self._toggle_play, padx=12, pady=4,
        )
        self.play_btn.pack(side="left")

        # Status bar
        self.status_var = tk.StringVar(value="Ready. Focus window then use arrow keys.")
        self.status_lbl = tk.Label(
            self.win, textvariable=self.status_var,
            font=("Segoe UI", 8), fg=C_TEXT_MID, bg=C_BG,
            anchor="w", wraplength=WIN_W - 20,
        )
        self.status_lbl.pack(fill="x", padx=14, pady=(2, 8))

    def _build_telemetry_sidebar(self, parent):
        sb = tk.Frame(parent, bg=C_PANEL, width=TELEMETRY_W)
        sb.pack(side="right", fill="y", padx=(10, 0))
        sb.pack_propagate(False)

        tk.Label(sb, text="TELEMETRY", font=("Segoe UI", 9, "bold"),
                 fg=C_ACCENT, bg=C_PANEL).pack(pady=(14, 4))

        self._tele_vars = {}
        fields = [
            ("speed_kmh",     "⚡ Speed",      "-- km/h",   C_TEXT_HI),
            ("hav_dist",      "📏 Seg. Dist",  "-- m",      C_TEXT_HI),
            ("cum_dist",      "🛣 Trip Dist",   "-- km",     C_TEXT_HI),
            ("wp_index",      "📍 Waypoint",   "0 / 0",     C_TEXT_MID),
            ("pred_lat",      "🤖 Pred. Lat",  "--",        C_PREDICT),
            ("pred_lon",      "🤖 Pred. Lon",  "--",        C_PREDICT),
            ("confidence",    "🎯 Confidence", "--",        C_PREDICT),
            ("network",       "📶 Network",    "Checking",  C_SAFE),
            ("speed_mult",    "🚀 Speed Mult", "×1",        C_ACCENT),
            ("deviation",     "↗ Deviation",   "OFF",       C_TEXT_DIM),
        ]

        for key, label, default, color in fields:
            row = tk.Frame(sb, bg=C_PANEL)
            row.pack(fill="x", padx=8, pady=3)
            tk.Label(row, text=label, font=("Segoe UI", 7, "bold"),
                     fg=C_TEXT_DIM, bg=C_PANEL, anchor="w",
                     width=13).pack(side="left")
            var = tk.StringVar(value=default)
            self._tele_vars[key] = var
            tk.Label(row, textvariable=var, font=("Segoe UI", 8, "bold"),
                     fg=color, bg=C_PANEL, anchor="w").pack(side="left")

        # Separator
        sep = tk.Frame(sb, bg=C_BORDER, height=1)
        sep.pack(fill="x", padx=8, pady=8)

        # Hotkey cheat-sheet
        cheat = [
            ("↑↓←→", "Move marker"),
            ("D",     "Route deviation"),
            ("S",     "Speed boost"),
            ("R",     "Reset route"),
        ]
        tk.Label(sb, text="HOTKEYS", font=("Segoe UI", 7, "bold"),
                 fg=C_TEXT_DIM, bg=C_PANEL).pack(anchor="w", padx=8)
        for key_str, desc in cheat:
            row = tk.Frame(sb, bg=C_PANEL)
            row.pack(fill="x", padx=8, pady=1)
            tk.Label(row, text=key_str, font=("Segoe UI", 8, "bold"),
                     fg=C_ACCENT, bg=C_PANEL, width=5).pack(side="left")
            tk.Label(row, text=desc, font=("Segoe UI", 7),
                     fg=C_TEXT_MID, bg=C_PANEL).pack(side="left")

    # ── Hotkey bindings ───────────────────────────────────────────────────────

    def _bind_hotkeys(self):
        self.win.bind("<Up>",    lambda e: self._arrow_move(LAT_STEP, 0))
        self.win.bind("<Down>",  lambda e: self._arrow_move(-LAT_STEP, 0))
        self.win.bind("<Left>",  lambda e: self._arrow_move(0, -LON_STEP))
        self.win.bind("<Right>", lambda e: self._arrow_move(0,  LON_STEP))
        self.win.bind("<d>",     lambda e: self._trigger_deviation())
        self.win.bind("<D>",     lambda e: self._trigger_deviation())
        self.win.bind("<s>",     lambda e: self._cycle_speed())
        self.win.bind("<S>",     lambda e: self._cycle_speed())
        self.win.bind("<r>",     lambda e: self._reset_route())
        self.win.bind("<R>",     lambda e: self._reset_route())
        # Ensure the window captures keyboard events
        self.win.focus_set()

    # ── Arrow-key free movement ───────────────────────────────────────────────

    def _arrow_move(self, dlat: float, dlon: float):
        """Move the simulated marker freely by keyboard arrows."""
        if not self.route_points:
            # Seed a starting point at the centre of the map.
            lat, lon = map_config.CENTER_LAT, map_config.CENTER_LON
            self.route_points = [(lat, lon)]
            self.current_index = 0

        cur_lat, cur_lon = self.route_points[self.current_index]
        new_lat = cur_lat + dlat
        new_lon = cur_lon + dlon

        # Append as a new waypoint so the trail grows.
        self.route_points.append((new_lat, new_lon))
        self.current_index = len(self.route_points) - 1

        self._fire_safety_cycle(new_lat, new_lon)
        self._draw_map()
        self._update_status(f"Arrow move → ({new_lat:.5f}, {new_lon:.5f})")

    # ── D key: route deviation ────────────────────────────────────────────────

    def _trigger_deviation(self):
        """Inject a lateral offset to simulate leaving the safe route."""
        if not self.route_points:
            return
        self._deviation_active = not self._deviation_active
        dev_status = "ACTIVE" if self._deviation_active else "OFF"
        self._tele_vars["deviation"].set(dev_status)

        if self._deviation_active:
            # Apply deviation offset to remaining route waypoints.
            offset = 0.0023   # ≈ 250 m in degrees
            n = len(self.route_points)
            dev_start = self.current_index
            for i in range(dev_start, n):
                lat, lon = self.route_points[i]
                self.route_points[i] = (lat + offset, lon + offset)
            self._draw_map()
            self._update_status("⚠️ DEVIATION TRIGGERED — route shifted 250 m off-path")
        else:
            self._on_route_change()
            self._update_status("✅ Deviation cleared — route reset to normal path")

    # ── S key: speed cycle ────────────────────────────────────────────────────

    def _cycle_speed(self):
        self._speed_idx = (self._speed_idx + 1) % len(SPEED_PRESETS)
        mult = SPEED_PRESETS[self._speed_idx]
        self._tele_vars["speed_mult"].set(f"×{mult}")
        self._update_status(f"🚀 Speed multiplier set to ×{mult}")

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_map(self):
        self.canvas.delete("all")
        self._draw_grid()
        self._draw_roads()
        self._draw_landmarks()
        self._draw_trail()
        self._draw_marker()
        self._draw_predicted_marker()

    def _draw_grid(self):
        step = CANVAS_W // 12
        for i in range(0, CANVAS_W, step):
            self.canvas.create_line(i, 0, i, CANVAS_H,
                                    fill="#0f1f35", width=1, tags="grid")
        for i in range(0, CANVAS_H, step):
            self.canvas.create_line(0, i, CANVAS_W, i,
                                    fill="#0f1f35", width=1, tags="grid")
        # Cardinal labels
        self.canvas.create_text(6, 6,   text="N", fill=C_TEXT_DIM,
                                 font=("Segoe UI", 7, "bold"), anchor="nw")
        self.canvas.create_text(6, CANVAS_H - 6, text="S", fill=C_TEXT_DIM,
                                 font=("Segoe UI", 7, "bold"), anchor="sw")

    def _draw_roads(self):
        if len(self.route_points) < 2:
            return
        pixel_pts = [map_config.latlon_to_pixel(lat, lon, CANVAS_W)
                     for lat, lon in self.route_points]
        # Outer glow (wide dim blue)
        flat = [c for p in pixel_pts for c in p]
        if len(flat) >= 4:
            self.canvas.create_line(*flat, fill="#1e3a5f", width=8,
                                     smooth=True, tags="road_glow")
            # Road itself
            self.canvas.create_line(*flat, fill=C_ROAD, width=3,
                                     smooth=True, tags="road")

    def _draw_landmarks(self):
        if self.route_var.get() == CUSTOM_ROUTE_LABEL:
            return
        dynamic_landmarks = map_config.get_dynamic_landmarks(self.controller)
        for label, (llat, llon) in dynamic_landmarks.items():
            lx, ly = map_config.latlon_to_pixel(llat, llon, CANVAS_W)
            self.canvas.create_oval(lx - 7, ly - 7, lx + 7, ly + 7,
                                     fill=C_LANDMARK, outline=C_TEXT_HI,
                                     width=1, tags="landmark")
            self.canvas.create_text(lx, ly - 16, text=label,
                                     fill=C_TEXT_HI,
                                     font=("Segoe UI", 7, "bold"),
                                     tags="landmark")

    def _draw_trail(self):
        """Draw the already-travelled path with a gradient from old→recent."""
        if len(self._trail_coords) < 2:
            return
        n = len(self._trail_coords)
        for i in range(1, n):
            frac = i / n
            color = C_TRAIL if frac > 0.4 else C_TRAIL_OLD
            x0, y0 = self._trail_coords[i - 1]
            x1, y1 = self._trail_coords[i]
            self.canvas.create_line(x0, y0, x1, y1, fill=color,
                                     width=2, tags="trail")

    def _draw_marker(self):
        """Draw the pulsing position marker."""
        self.canvas.delete("marker")
        if not self.route_points or self.current_index >= len(self.route_points):
            return
        lat, lon = self.route_points[self.current_index]
        px, py = map_config.latlon_to_pixel(lat, lon, CANVAS_W)

        # Outer pulse ring
        r_outer = int(12 + 4 * math.sin(self._pulse_phase))
        self.canvas.create_oval(
            px - r_outer, py - r_outer,
            px + r_outer, py + r_outer,
            outline=C_MARKER, width=2, tags="marker",
        )
        # Inner solid dot
        self.canvas.create_oval(
            px - 6, py - 6, px + 6, py + 6,
            fill=C_MARKER, outline=C_MARKER_RIM, width=2, tags="marker",
        )
        # Coordinate label
        self.canvas.create_text(
            px, py - r_outer - 6,
            text=f"({lat:.4f}, {lon:.4f})",
            fill=C_ACCENT, font=("Segoe UI", 7), tags="marker",
        )

    def _draw_predicted_marker(self):
        """Draw the AI-predicted next waypoint as a dashed diamond."""
        self.canvas.delete("predicted")
        if not (self.controller and hasattr(self.controller, "predictor")):
            return
        pred = self.controller.predictor.predict_next_coordinate()
        if not pred:
            return
        p_lat = pred.get("predicted_latitude")
        p_lon = pred.get("predicted_longitude")
        if p_lat is None or p_lon is None:
            return
        ppx, ppy = map_config.latlon_to_pixel(p_lat, p_lon, CANVAS_W)
        r = 9
        # Diamond shape
        self.canvas.create_polygon(
            ppx, ppy - r, ppx + r, ppy,
            ppx, ppy + r, ppx - r, ppy,
            outline=C_PREDICT, fill="", width=2,
            dash=(4, 2), tags="predicted",
        )
        self.canvas.create_text(
            ppx, ppy + r + 8,
            text=f"AI: ({p_lat:.4f}, {p_lon:.4f})",
            fill=C_PREDICT, font=("Segoe UI", 7), tags="predicted",
        )
        # Update telemetry
        conf = pred.get("confidence", 0.0)
        self._tele_vars["pred_lat"].set(f"{p_lat:.5f}")
        self._tele_vars["pred_lon"].set(f"{p_lon:.5f}")
        self._tele_vars["confidence"].set(f"{conf * 100:.1f}%")

    # ── Pulse animation ───────────────────────────────────────────────────────

    def _start_pulse_animation(self):
        def _tick():
            if not self.win.winfo_exists():
                return
            self._pulse_phase = (self._pulse_phase + 0.18) % (2 * math.pi)
            self.canvas.delete("marker")
            self._draw_marker()
            self._draw_predicted_marker()
            self._update_network_status()
            self.win.after(55, _tick)
        self.win.after(55, _tick)

    def _update_network_status(self):
        if self.controller and hasattr(self.controller, "phone_has_signal"):
            has_sig = self.controller.phone_has_signal
            self._tele_vars["network"].set("Online ✅" if has_sig else "Offline ⚠️")

    # ── Custom-route click ────────────────────────────────────────────────────

    def _on_canvas_click(self, event):
        if self.route_var.get() != CUSTOM_ROUTE_LABEL:
            return
        lat, lon = map_config.pixel_to_latlon(event.x, event.y, CANVAS_W)
        self.route_points.append((lat, lon))
        self.current_index = len(self.route_points) - 1
        px, py = map_config.latlon_to_pixel(lat, lon, CANVAS_W)
        self._trail_coords.append((px, py))
        self._fire_safety_cycle(lat, lon)
        self._draw_map()
        self._update_status(f"Custom point → ({lat:.5f}, {lon:.5f})")

    # ── Route loading / resetting ─────────────────────────────────────────────

    def _load_route(self):
        self._trail_coords = []
        if self.route_var.get() == CUSTOM_ROUTE_LABEL:
            self.route_points = []
            self._update_status("Custom mode: click map or use arrow keys to move.")
        else:
            self.route_points = list(map_config.get_dynamic_routes(self.controller).get(self.route_var.get(), []))
            if self.route_points:
                map_config.auto_center_for_points(self.route_points)
            self._update_status("Route loaded. Press ▶ or hotkeys to begin.")
        self.current_index   = 0
        self.simulated_clock = time.time()
        self._deviation_active = False
        self._tele_vars["deviation"].set("OFF")
        self._draw_map()
        self._update_wp_label()

    def _on_route_change(self):
        self._pause()
        self._load_route()

    def _reset_route(self):
        self._pause()
        if self.route_var.get() == CUSTOM_ROUTE_LABEL:
            self.route_points = []
        self.current_index   = 0
        self.simulated_clock = time.time()
        self._trail_coords   = []
        self._deviation_active = False
        self._tele_vars["deviation"].set("OFF")
        self._draw_map()
        self._update_wp_label()
        self._update_status("Route reset.")
        if self.controller and self.controller.gui_app:
            self.controller.gui_app.clear_map_display()

    # ── Safety cycle dispatcher ───────────────────────────────────────────────

    def _fire_safety_cycle(self, lat: float, lon: float):
        sim_ts = self._advance_simulated_clock(lat, lon)
        try:
            result = self.controller.run_live_safety_cycle(
                simulated_lat=lat, simulated_lon=lon, simulated_timestamp=sim_ts,
            )
        except Exception as exc:
            print(f"[MapSim] Safety cycle error: {exc}")
            return

        anomaly = result.get("anomaly_check", {})
        is_threat = anomaly.get("is_threat", False)
        threat_type = anomaly.get("threat_type", "NORMAL")
        speed = result.get("speed_kmh", 0.0)
        pred  = result.get("predicted_next")

        # Telemetry updates
        if speed is not None:
            self._tele_vars["speed_kmh"].set(f"{speed:.1f} km/h")
        if hasattr(self.controller, "predictor"):
            summary = self.controller.predictor.get_history_summary()
            seg_m   = summary.get("last_segment_m", 0.0)
            cum_km  = summary.get("cumulative_distance_km", 0.0)
            self._tele_vars["hav_dist"].set(f"{seg_m:.1f} m")
            self._tele_vars["cum_dist"].set(f"{cum_km:.3f} km")

        status_text = ("⚠️ " + threat_type) if is_threat else "✅ Normal — No Threat"
        self._update_status(status_text, is_threat=is_threat)
        if is_threat and self.controller and getattr(self.controller, "gui_app", None):
            self.controller.gui_app.send_desktop_popup("⚠️ Map Alert", f"Threat detected: {threat_type}")

    def _advance_simulated_clock(self, lat: float, lon: float) -> float:
        prev_idx = self.current_index - 1
        if 0 <= prev_idx < len(self.route_points):
            prev_lat, prev_lon = self.route_points[prev_idx]
            dist_km = _haversine_km(prev_lat, prev_lon, lat, lon)
            mult    = SPEED_PRESETS[self._speed_idx]
            base_speed = max(self.speed_var.get() if hasattr(self, "speed_var") else 4, 1)
            effective_speed = base_speed * mult
            dt_hours = dist_km / effective_speed
            self.simulated_clock += dt_hours * 3600.0
        return self.simulated_clock

    # ── Play / pause / step ───────────────────────────────────────────────────

    def _toggle_play(self):
        if self.is_playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        if self.route_var.get() == CUSTOM_ROUTE_LABEL:
            self._update_status("Custom mode: click the map or use arrow keys.")
            return
        if self.current_index >= len(self.route_points) - 1:
            self._update_status("Route complete. Press R to reset.")
            return
        self.is_playing = True
        self.play_btn.config(text="⏸ Pause", bg="#f59e0b")
        self._tick()

    def _pause(self):
        self.is_playing = False
        if hasattr(self, "play_btn") and self.play_btn.winfo_exists():
            self.play_btn.config(text="▶ Play", bg=C_SAFE)
        if self.play_job:
            self.win.after_cancel(self.play_job)
            self.play_job = None

    def _tick(self):
        if not self.is_playing:
            return
        self._step_once()
        if self.current_index >= len(self.route_points) - 1:
            self._pause()
            self._update_status("✅ Route complete — all waypoints traversed.")
            return
        mult      = SPEED_PRESETS[self._speed_idx]
        base_spd  = getattr(self, "_base_speed", 4)
        delay_ms  = max(80, int(2500 / (base_spd * mult)))
        self.play_job = self.win.after(delay_ms, self._tick)

    def _step_once(self):
        if not self.route_points or self.current_index >= len(self.route_points) - 1:
            return
        self.current_index += 1
        lat, lon = self.route_points[self.current_index]
        px, py   = map_config.latlon_to_pixel(lat, lon, CANVAS_W)
        self._trail_coords.append((px, py))
        self._fire_safety_cycle(lat, lon)
        self._draw_trail()
        self._update_wp_label()

    # ── Status / labels ───────────────────────────────────────────────────────

    def _update_status(self, extra: str = "", is_threat: bool = False):
        total = max(len(self.route_points) - 1, 0)
        self.status_var.set(f"WP {self.current_index}/{total}  |  {extra}")
        if is_threat:
            self.status_lbl.configure(fg=C_THREAT)
        else:
            self.status_lbl.configure(fg=C_TEXT_MID)
        self._update_wp_label()

    def _update_wp_label(self):
        total = max(len(self.route_points) - 1, 0)
        self._tele_vars["wp_index"].set(f"{self.current_index} / {total}")

    # ── Close ─────────────────────────────────────────────────────────────────

    def _on_close(self):
        self._pause()
        self.win.destroy()


# ── speed_var shim (keeps speed_slider compatible with _advance_simulated_clock)
class _IntProxy:
    def __init__(self, val=4):
        self._val = val
    def get(self):
        return self._val
    def set(self, v):
        self._val = v


# ── Public factory ─────────────────────────────────────────────────────────────

def open_map_simulator(parent_root, controller) -> MapSimulatorWindow:
    """Open the interactive map simulator window and return the instance."""
    sim = MapSimulatorWindow(parent_root, controller)
    # Attach a default speed proxy so _advance_simulated_clock works without a slider.
    if not hasattr(sim, "speed_var"):
        sim.speed_var = _IntProxy(4)
    sim._base_speed = 4
    return sim