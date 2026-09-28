import time
import math
import random

class OfflineLocationEngine:
    def __init__(self, default_lat=13.0827, default_lon=80.2707, auto_simulate=False):
        self.current_lat = default_lat
        self.current_lon = default_lon
        self.last_timestamp = time.time()
        self.location_history = []

        self.auto_simulate = auto_simulate

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        """ Calculates distance in KM using pure Haversine Math """
        R = 6371.0  # Earth radius in KM

        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)

        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def get_current_location(self):
        current_time = time.time()

        if self.auto_simulate:
            self.current_lat += random.uniform(-0.0005, 0.0005)
            self.current_lon += random.uniform(-0.0005, 0.0005)

        location_data = {
            "latitude": round(self.current_lat, 6),
            "longitude": round(self.current_lon, 6),
            "timestamp": current_time,
            "maps_url": f"https://maps.google.com/?q={round(self.current_lat, 6)},{round(self.current_lon, 6)}"
        }

        self.location_history.append(location_data)
        if len(self.location_history) > 50:
            self.location_history.pop(0)

        self.last_timestamp = current_time
        return location_data

    def calculate_speed(self, prev_loc, curr_loc):
        dist_km = self.haversine_distance(
            prev_loc["latitude"], prev_loc["longitude"],
            curr_loc["latitude"], curr_loc["longitude"]
        )
        time_hours = (curr_loc["timestamp"] - prev_loc["timestamp"]) / 3600.0

        if time_hours <= 0:
            return 0.0

        return round(dist_km / time_hours, 2)


if __name__ == "__main__":
    print("[Location Engine] Testing Offline GPS Acquisition (auto_simulate=True for this test only)...")
    gps = OfflineLocationEngine(auto_simulate=True)

    loc1 = gps.get_current_location()
    print(f"📍 GPS Point 1: Lat {loc1['latitude']}, Lon {loc1['longitude']}")

    time.sleep(2)
    loc2 = gps.get_current_location()
    print(f"📍 GPS Point 2: Lat {loc2['latitude']}, Lon {loc2['longitude']}")

    speed = gps.calculate_speed(loc1, loc2)
    print(f"🚗 Calculated Speed: {speed} km/h")
    print(f"🔗 Google Maps Link: {loc2['maps_url']}")