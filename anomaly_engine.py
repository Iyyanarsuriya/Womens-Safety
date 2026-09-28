import time
import math
import numpy as np
from location_module import OfflineLocationEngine

class TrajectoryAnomalyEngine:
    def __init__(self, speed_threshold_kmh=80.0, deviation_threshold_km=0.20):
        self.max_speed_threshold = speed_threshold_kmh
        self.max_deviation_threshold = deviation_threshold_km
        self.gps_engine = OfflineLocationEngine()
        self.trajectory_history = []
        self.planned_route = []

    def set_planned_route(self, route_points):
        self.planned_route = route_points

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

    def evaluate_telemetry(self, current_loc, previous_loc):
        self.trajectory_history.append(current_loc)

        speed = self.gps_engine.calculate_speed(previous_loc, current_loc)
        if speed > self.max_speed_threshold:
            return True, "HIGH_SPEED", f"🚨 High Speed Anomaly Detected! Speed: {speed} km/h (Limit: {self.max_speed_threshold} km/h)"

        predicted_loc = self.predict_next_location()
        if predicted_loc:
            deviation_dist = self.gps_engine.haversine_distance(
                current_loc["latitude"], current_loc["longitude"],
                predicted_loc["latitude"], predicted_loc["longitude"]
            )

            if deviation_dist > self.max_deviation_threshold:
                return True, "ROUTE_DEVIATION", f"⚠️ Route Anomaly Detected! Deviated by {round(deviation_dist * 1000, 1)} meters off target!"

        return False, "NORMAL", f"✅ Telemetry Normal. Speed: {speed} km/h"


if __name__ == "__main__":
    print("[Anomaly Engine] Initializing...")
    detector = TrajectoryAnomalyEngine(speed_threshold_kmh=80.0, deviation_threshold_km=0.15)
    
    p1 = detector.gps_engine.get_current_location()
    time.sleep(1)
    p2 = detector.gps_engine.get_current_location()
    
    is_anomaly, a_type, msg = detector.evaluate_telemetry(p2, p1)
    print(msg)

    time.sleep(1)
    p3 = detector.gps_engine.get_current_location()
    p3["latitude"] += 0.05 
    p3["longitude"] += 0.05

    is_anomaly, a_type, msg = detector.evaluate_telemetry(p3, p2)
    print(msg)