import time
import math
import numpy as np
from location_module import OfflineLocationEngine

class TrajectoryAnomalyEngine:
    def __init__(self, speed_threshold_kmh=80.0, deviation_threshold_km=0.20):
        self.max_speed_threshold = float(speed_threshold_kmh)
        self.max_deviation_threshold = float(deviation_threshold_km)
        self.gps_engine = OfflineLocationEngine()
        self.trajectory_history = []
        self.planned_route = []
        self.destination = None  # {"name": str, "latitude": float, "longitude": float}

        # Cooldown tracking to prevent repeated alert loops for same ongoing event
        self.cooldown_period_sec = 60.0
        self.last_speed_alert_time = 0.0
        self.last_deviation_alert_time = 0.0

    @property
    def speed_threshold_kmh(self):
        return self.max_speed_threshold

    @speed_threshold_kmh.setter
    def speed_threshold_kmh(self, val):
        self.max_speed_threshold = float(val)

    def set_speed_threshold(self, speed_kmh: float):
        self.max_speed_threshold = float(speed_kmh)

    def set_destination(self, name: str, latitude: float, longitude: float):
        self.destination = {
            "name": name,
            "latitude": float(latitude),
            "longitude": float(longitude)
        }

    def get_destination(self):
        return self.destination

    def clear_destination(self):
        self.destination = None

    def set_planned_route(self, route_points):
        self.planned_route = route_points

    def acknowledge_safe(self, threat_type: str = "ALL", cooldown_seconds: float = None):
        """Called when user confirms they are safe to reset / apply cooldown."""
        now = time.time()
        if cooldown_seconds is not None:
            self.cooldown_period_sec = float(cooldown_seconds)
        if "SPEED" in threat_type.upper() or threat_type == "ALL":
            self.last_speed_alert_time = now
        if "ROUTE" in threat_type.upper() or "DEVIATION" in threat_type.upper() or threat_type == "ALL":
            self.last_deviation_alert_time = now

    def check_for_threats(self, speed_kmh=0.0, current_lat=0.0, current_lon=0.0, predicted_point=None):
        """
        Direct threat evaluation checking speed threshold and route deviation.
        Returns: (is_threat: bool, reason_message: str)
        """
        now = time.time()
        # 1. Speed Check
        if speed_kmh > self.max_speed_threshold:
            if (now - self.last_speed_alert_time) > self.cooldown_period_sec:
                self.last_speed_alert_time = now
                return True, f"⚠️ ARE YOU SAFE? SPEED INCREASE DETECTED: {speed_kmh:.1f} km/h (Limit: {self.max_speed_threshold:.1f} km/h)"
            else:
                return False, "COOLDOWN_ACTIVE"

        # 2. Destination / Route Deviation Check
        if self.destination and current_lat and current_lon:
            d_lat = self.destination["latitude"]
            d_lon = self.destination["longitude"]
            dist_km = self.gps_engine.haversine_distance(current_lat, current_lon, d_lat, d_lon)
            if dist_km > self.max_deviation_threshold and dist_km > 0.5:
                if (now - self.last_deviation_alert_time) > self.cooldown_period_sec:
                    self.last_deviation_alert_time = now
                    return True, f"⚠️ ARE YOU SAFE? ROUTE DEVIATION FROM '{self.destination['name']}' ({dist_km:.2f} km)"
                else:
                    return False, "COOLDOWN_ACTIVE"

        return False, "NORMAL"

    def predict_next_location(self):
        if len(self.trajectory_history) < 2:
            return None

        recent_pts = self.trajectory_history[-3:]
        lats = [p["latitude"] for p in recent_pts]
        lons = [p["longitude"] for p in recent_pts]

        lat_diff = np.mean(np.diff(lats))
        lon_diff = np.mean(np.diff(lons))

        last_pt = recent_pts[-1]
        predicted_lat = round(last_pt["latitude"] + lat_diff, 6)
        predicted_lon = round(last_pt["longitude"] + lon_diff, 6)

        return {"latitude": predicted_lat, "longitude": predicted_lon}

    def evaluate_telemetry(self, current_loc, previous_loc, external_predicted_loc=None):
        """
        Evaluates speed and route deviation anomalies.
        Returns: (is_threat: bool, threat_type: str, message: str)
        """
        now = time.time()
        self.trajectory_history.append(current_loc)
        if len(self.trajectory_history) > 200:
            self.trajectory_history.pop(0)

        # 1. Evaluate speed
        speed = self.gps_engine.calculate_speed(previous_loc, current_loc)
        if speed > self.max_speed_threshold:
            if (now - self.last_speed_alert_time) > self.cooldown_period_sec:
                self.last_speed_alert_time = now
                return True, "HIGH_SPEED", f"🚨 Speed Increase Alert! Speed: {speed} km/h (Threshold: {self.max_speed_threshold} km/h)"

        # 2. Evaluate Destination Deviation (if destination is configured)
        if self.destination and previous_loc:
            prev_dist_to_dest = self.gps_engine.haversine_distance(
                previous_loc["latitude"], previous_loc["longitude"],
                self.destination["latitude"], self.destination["longitude"]
            )
            curr_dist_to_dest = self.gps_engine.haversine_distance(
                current_loc["latitude"], current_loc["longitude"],
                self.destination["latitude"], self.destination["longitude"]
            )

            # If user moved significantly further away from destination (> 250m retreat in a trip)
            if (curr_dist_to_dest - prev_dist_to_dest) > self.max_deviation_threshold and curr_dist_to_dest > 0.5:
                if (now - self.last_deviation_alert_time) > self.cooldown_period_sec:
                    self.last_deviation_alert_time = now
                    return True, "ROUTE_DEVIATION", f"⚠️ Destination Route Deviation! Moving away from '{self.destination['name']}' ({round(curr_dist_to_dest, 2)} km away)"

        # 3. Evaluate LSTM predicted location deviation
        pred = external_predicted_loc or self.predict_next_location()
        if pred:
            p_lat = pred.get("predicted_latitude") or pred.get("latitude")
            p_lon = pred.get("predicted_longitude") or pred.get("longitude")
            if p_lat is not None and p_lon is not None:
                deviation_dist = self.gps_engine.haversine_distance(
                    current_loc["latitude"], current_loc["longitude"],
                    p_lat, p_lon
                )

                if deviation_dist > self.max_deviation_threshold:
                    if (now - self.last_deviation_alert_time) > self.cooldown_period_sec:
                        self.last_deviation_alert_time = now
                        return True, "ROUTE_DEVIATION", f"⚠️ Route Deviation Alert! Deviated by {round(deviation_dist * 1000, 1)}m from expected course!"

        return False, "NORMAL", f"✅ Telemetry Normal. Speed: {speed} km/h"


# Module-level alias for backward compatibility and test suite
AnomalyEngine = TrajectoryAnomalyEngine