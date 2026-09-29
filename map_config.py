import os
import json
import random

# Dynamic Map Center and Zoom Span
CENTER_LAT = 11.4615
CENTER_LON = 79.7271
ZOOM_SPAN_DEGREES = 0.11

DATA_DIR = "data"
ZONES_FILE = os.path.join(DATA_DIR, "safe_zones.json")


def set_map_center(lat: float, lon: float, span_degrees: float = None):
    """Dynamically recenters the map coordinate projection onto user's real GPS coordinates."""
    global CENTER_LAT, CENTER_LON, ZOOM_SPAN_DEGREES
    if lat and lon and not (lat == 0.0 and lon == 0.0):
        CENTER_LAT = float(lat)
        CENTER_LON = float(lon)
        if span_degrees is not None and span_degrees > 0:
            ZOOM_SPAN_DEGREES = float(span_degrees)


def auto_center_for_points(points: list, margin_ratio: float = 1.3):
    """Calculates dynamic bounding box and zoom span to frame all provided waypoints."""
    global CENTER_LAT, CENTER_LON, ZOOM_SPAN_DEGREES
    valid_pts = [p for p in points if p and len(p) >= 2 and (p[0] != 0.0 or p[1] != 0.0)]
    if not valid_pts:
        return
    lats = [p[0] for p in valid_pts]
    lons = [p[1] for p in valid_pts]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    CENTER_LAT = (min_lat + max_lat) / 2.0
    CENTER_LON = (min_lon + max_lon) / 2.0
    lat_span = max(max_lat - min_lat, 0.005)
    lon_span = max(max_lon - min_lon, 0.005)
    ZOOM_SPAN_DEGREES = max(lat_span, lon_span) * margin_ratio


def latlon_to_pixel(lat, lon, canvas_size):
    """Converts a (lat, lon) into an (x, y) pixel position on a canvas."""
    if isinstance(canvas_size, (tuple, list)):
        w_size, h_size = canvas_size[0], canvas_size[1]
    else:
        w_size, h_size = canvas_size, canvas_size

    min_lat = CENTER_LAT - ZOOM_SPAN_DEGREES / 2
    max_lat = CENTER_LAT + ZOOM_SPAN_DEGREES / 2
    min_lon = CENTER_LON - ZOOM_SPAN_DEGREES / 2
    max_lon = CENTER_LON + ZOOM_SPAN_DEGREES / 2

    span_x = max_lon - min_lon
    span_y = max_lat - min_lat
    if span_x <= 0:
        span_x = 0.001
    if span_y <= 0:
        span_y = 0.001

    frac_x = (lon - min_lon) / span_x
    frac_y = (max_lat - lat) / span_y  # inverted: screen-down = south
    return frac_x * w_size, frac_y * h_size


def pixel_to_latlon(px, py, canvas_size):
    """Reverse of latlon_to_pixel - converts canvas click position into real (lat, lon)."""
    if isinstance(canvas_size, (tuple, list)):
        w_size, h_size = canvas_size[0], canvas_size[1]
    else:
        w_size, h_size = canvas_size, canvas_size

    min_lat = CENTER_LAT - ZOOM_SPAN_DEGREES / 2
    max_lat = CENTER_LAT + ZOOM_SPAN_DEGREES / 2
    min_lon = CENTER_LON - ZOOM_SPAN_DEGREES / 2
    max_lon = CENTER_LON + ZOOM_SPAN_DEGREES / 2

    frac_x = px / (w_size if w_size > 0 else 1)
    frac_y = py / (h_size if h_size > 0 else 1)
    lon = min_lon + frac_x * (max_lon - min_lon)
    lat = max_lat - frac_y * (max_lat - min_lat)
    return lat, lon


def _interpolate_segment(start, end, num_points, noise=0.00015):
    lat1, lon1 = start
    lat2, lon2 = end
    points = []
    for i in range(num_points + 1):
        frac = i / num_points
        lat = lat1 + (lat2 - lat1) * frac + random.uniform(-noise, noise)
        lon = lon1 + (lon2 - lon1) * frac + random.uniform(-noise, noise)
        points.append((round(lat, 6), round(lon, 6)))
    return points


def _build_multiwaypoint_route(waypoints, points_per_segment=20, deviate_at_fraction=None, deviation_m=250):
    full_route = []
    for i in range(len(waypoints) - 1):
        segment = _interpolate_segment(waypoints[i], waypoints[i + 1], points_per_segment)
        if i > 0:
            segment = segment[1:]
        full_route.extend(segment)

    if deviate_at_fraction is not None:
        n = len(full_route)
        dev_start = int(n * deviate_at_fraction)
        dev_len = max(4, n // 10)
        offset_deg = deviation_m / 111000.0
        for i in range(dev_start, min(dev_start + dev_len, n)):
            full_route[i] = (round(full_route[i][0] + offset_deg, 6), round(full_route[i][1] + offset_deg, 6))

    return full_route


def get_dynamic_landmarks(controller=None):
    """Retrieves landmarks dynamically from safe zones and current user position."""
    landmarks = {}
    # From controller safe zones if available
    if controller and hasattr(controller, 'safe_zones') and controller.safe_zones:
        for z in controller.safe_zones:
            name = z.get('name', 'Safe Zone')
            landmarks[f"📍 {name}"] = (float(z["latitude"]), float(z["longitude"]))
    elif os.path.exists(ZONES_FILE):
        try:
            with open(ZONES_FILE, "r", encoding="utf-8") as f:
                zones = json.load(f)
                for z in zones:
                    name = z.get('name', 'Safe Zone')
                    landmarks[f"📍 {name}"] = (float(z["latitude"]), float(z["longitude"]))
        except Exception:
            pass

    return landmarks


def get_dynamic_routes(controller=None):
    """Constructs dynamic routes based on safe zones or live coordinates."""
    landmarks = get_dynamic_landmarks(controller)
    pts = list(landmarks.values())
    routes = {}
    if len(pts) >= 2:
        names = list(landmarks.keys())
        route_name = f"Corridor: {names[0]} ➔ {names[-1]}"
        routes[route_name] = _build_multiwaypoint_route(pts, points_per_segment=25)
        routes[f"{route_name} (Deviated)"] = _build_multiwaypoint_route(pts, points_per_segment=25, deviate_at_fraction=0.5, deviation_m=300)
    else:
        # Default route around current center
        p1 = (CENTER_LAT - 0.015, CENTER_LON - 0.015)
        p2 = (CENTER_LAT + 0.015, CENTER_LON + 0.015)
        routes["Standard Safe Route"] = _build_multiwaypoint_route([p1, (CENTER_LAT, CENTER_LON), p2], points_per_segment=20)
        routes["High-Risk Deviated Route"] = _build_multiwaypoint_route([p1, (CENTER_LAT, CENTER_LON), p2], points_per_segment=20, deviate_at_fraction=0.5, deviation_m=300)

    return routes


# Backwards compatibility properties
class _DynamicLandmarksProxy(dict):
    def __init__(self):
        super().__init__()

    def items(self):
        return get_dynamic_landmarks().items()

    def keys(self):
        return get_dynamic_landmarks().keys()

    def values(self):
        return get_dynamic_landmarks().values()

    def __iter__(self):
        return iter(get_dynamic_landmarks())

    def __len__(self):
        return len(get_dynamic_landmarks())


class _DynamicRoutesProxy(dict):
    def __init__(self):
        super().__init__()

    def items(self):
        return get_dynamic_routes().items()

    def keys(self):
        return get_dynamic_routes().keys()

    def values(self):
        return get_dynamic_routes().values()

    def __getitem__(self, item):
        routes = get_dynamic_routes()
        return routes[item]

    def __contains__(self, item):
        return item in get_dynamic_routes()

    def __iter__(self):
        return iter(get_dynamic_routes())

    def __len__(self):
        return len(get_dynamic_routes())


LANDMARKS = _DynamicLandmarksProxy()
ROUTES = _DynamicRoutesProxy()