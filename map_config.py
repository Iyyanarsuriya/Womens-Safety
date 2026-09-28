import random
import math

# Centered on the midpoint between Bus Stand and College, with a span
# wide enough to comfortably fit the whole ~8-9 km route.
CENTER_LAT = 11.4615
CENTER_LON = 79.7271
ZOOM_SPAN_DEGREES = 0.11  # ~ 11-12 km across, gives margin around the route

# Real waypoints
BUS_STAND = (11.4889632, 79.7538831)        # Parangipettai Bus Stand (Home)
KEEZHAMOONGILADI = (11.4361507, 79.7015101)  # Keezhamoongiladi (village)
COLLEGE = (11.4339267, 79.7003913)           # Shree Raghavendra Arts & Science College


def latlon_to_pixel(lat, lon, canvas_size):
    """Converts a (lat, lon) into an (x, y) pixel position on a
    canvas_size x canvas_size canvas, using the shared bounding box."""
    min_lat = CENTER_LAT - ZOOM_SPAN_DEGREES / 2
    max_lat = CENTER_LAT + ZOOM_SPAN_DEGREES / 2
    min_lon = CENTER_LON - ZOOM_SPAN_DEGREES / 2
    max_lon = CENTER_LON + ZOOM_SPAN_DEGREES / 2

    frac_x = (lon - min_lon) / (max_lon - min_lon)
    frac_y = (max_lat - lat) / (max_lat - min_lat)  # inverted: screen-down = south
    return frac_x * canvas_size, frac_y * canvas_size


def pixel_to_latlon(px, py, canvas_size):
    """Reverse of latlon_to_pixel - used by the Custom Route click mode
    to turn a mouse click position back into a real (lat, lon)."""
    min_lat = CENTER_LAT - ZOOM_SPAN_DEGREES / 2
    max_lat = CENTER_LAT + ZOOM_SPAN_DEGREES / 2
    min_lon = CENTER_LON - ZOOM_SPAN_DEGREES / 2
    max_lon = CENTER_LON + ZOOM_SPAN_DEGREES / 2

    frac_x = px / canvas_size
    frac_y = py / canvas_size
    lon = min_lon + frac_x * (max_lon - min_lon)
    lat = max_lat - frac_y * (max_lat - min_lat)
    return lat, lon


def _interpolate_segment(start, end, num_points, noise=0.0002):
    lat1, lon1 = start
    lat2, lon2 = end
    points = []
    for i in range(num_points + 1):
        frac = i / num_points
        lat = lat1 + (lat2 - lat1) * frac + random.uniform(-noise, noise)
        lon = lon1 + (lon2 - lon1) * frac + random.uniform(-noise, noise)
        points.append((lat, lon))
    return points


def _build_multiwaypoint_route(waypoints, points_per_segment=20, deviate_at_fraction=None, deviation_m=250):
    """Builds a smooth path THROUGH a list of real waypoints in order
    (e.g. Bus Stand -> Keezhamoongiladi -> College), optionally
    injecting a sideways deviation partway through for the
    'high-risk' preset."""
    full_route = []
    for i in range(len(waypoints) - 1):
        segment = _interpolate_segment(waypoints[i], waypoints[i + 1], points_per_segment)
        if i > 0:
            segment = segment[1:]  # avoid duplicating the shared join point
        full_route.extend(segment)

    if deviate_at_fraction is not None:
        n = len(full_route)
        dev_start = int(n * deviate_at_fraction)
        dev_len = max(4, n // 10)
        offset_deg = deviation_m / 111000.0
        for i in range(dev_start, min(dev_start + dev_len, n)):
            full_route[i] = (full_route[i][0] + offset_deg, full_route[i][1] + offset_deg)

    return full_route


ROUTES = {
    "Normal Route: Bus Stand to College": _build_multiwaypoint_route(
        [BUS_STAND, KEEZHAMOONGILADI, COLLEGE], points_per_segment=25
    ),
    "Deviated Route: High-Risk Area": _build_multiwaypoint_route(
        [BUS_STAND, KEEZHAMOONGILADI, COLLEGE], points_per_segment=25,
        deviate_at_fraction=0.55, deviation_m=300
    ),
}

# Named landmarks, for drawing labeled markers on the map (used by map_simulator.py)
LANDMARKS = {
    "🚏 Parangipettai Bus Stand": BUS_STAND,
    "🏞️ Keezhamoongiladi": KEEZHAMOONGILADI,
    "🎓 Shree Raghavendra College": COLLEGE,
}