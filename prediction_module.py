import os
import json
import math
import time
import numpy as np
from datetime import datetime

# ── Persistence path ──────────────────────────────────────────────────────────
_DATA_DIR          = "data"
_HISTORY_FILE      = os.path.join(_DATA_DIR, "location_history.json")
_MAX_PERSISTED     = 1000   # keep last N entries in the JSON file


# ── Haversine (pure NumPy for batch use) ─────────────────────────────────────

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Returns distance in metres between two WGS-84 coordinate pairs."""
    R = 6_371_000.0  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlam  = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _haversine_batch_m(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """
    Vectorised Haversine for consecutive waypoint pairs.
    Given N-point arrays, returns (N-1,) distances in metres.
    """
    R = 6_371_000.0
    lat1, lat2 = np.radians(lats[:-1]), np.radians(lats[1:])
    lon1, lon2 = np.radians(lons[:-1]), np.radians(lons[1:])
    dphi = lat2 - lat1
    dlam = lon2 - lon1
    a = np.sin(dphi / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))


# ── Main predictor class ──────────────────────────────────────────────────────

class LSTMTrajectoryPredictor:
    """
    Stateful exponentially-weighted sequence extrapolator.

    The model maintains a history ring-buffer of GPS coordinates.  On
    every call to predict_next_coordinate() it:
      1. Computes per-step displacement vectors (Δlat, Δlon).
      2. Applies exponentially-increasing weights (most-recent step
         gets the highest weight) — equivalent to LSTM's recency bias.
      3. Extrapolates the weighted mean velocity by one time-step.
      4. Returns the predicted coordinate together with confidence,
         segment distance, and cumulative trip distance.
    """

    def __init__(self, sequence_length: int = 10):
        self.sequence_length    = sequence_length
        self._lats: list[float] = []
        self._lons: list[float] = []
        self._timestamps: list[float] = []
        self._cumulative_dist_km: float = 0.0
        self._last_segment_m: float     = 0.0

        # Load persisted history so the predictor "remembers" across restarts.
        os.makedirs(_DATA_DIR, exist_ok=True)
        self._load_history()

    # ── History management ────────────────────────────────────────────────────

    def update_history(self, lat: float, lon: float, timestamp: float = None) -> None:
        """
        Push a new GPS fix into the history buffer.
        Automatically trims to `sequence_length` and persists to disk.
        """
        ts = timestamp if timestamp is not None else time.time()

        # Compute segment distance before appending (need previous point).
        if self._lats:
            seg_m = _haversine_m(self._lats[-1], self._lons[-1], lat, lon)
            self._last_segment_m   = seg_m
            self._cumulative_dist_km += seg_m / 1000.0
        else:
            self._last_segment_m = 0.0

        self._lats.append(float(lat))
        self._lons.append(float(lon))
        self._timestamps.append(float(ts))

        # Keep only the last `sequence_length` points in RAM.
        if len(self._lats) > self.sequence_length:
            self._lats.pop(0)
            self._lons.pop(0)
            self._timestamps.pop(0)

        self._persist_entry(lat, lon, ts)

    def predict_next_coordinate(self) -> dict | None:
        """
        Returns a prediction dict or None if insufficient history.

        Return keys:
            predicted_latitude    : float
            predicted_longitude   : float
            confidence            : float  (0.0 – 1.0)
            segment_distance_m    : float  (last step distance in metres)
            cumulative_distance_km: float  (total trip distance in km)
        """
        n = len(self._lats)
        if n < 2:
            return None

        lats = np.array(self._lats, dtype=np.float64)
        lons = np.array(self._lons, dtype=np.float64)

        # Exponential weights — weight[i] grows toward the most recent step.
        weights = np.exp(np.linspace(-2.0, 0.0, n - 1))
        weights /= weights.sum()

        # Displacement vectors between consecutive waypoints.
        diff_lats = np.diff(lats)
        diff_lons = np.diff(lons)

        # Haversine-corrected segment distances for confidence scoring.
        seg_dists_m = _haversine_batch_m(lats, lons)      # shape (n-1,)

        # Weighted mean velocity (degrees per step).
        pred_dlat = float(np.dot(diff_lats, weights))
        pred_dlon = float(np.dot(diff_lons, weights))

        predicted_lat = round(lats[-1] + pred_dlat, 7)
        predicted_lon = round(lons[-1] + pred_dlon, 7)

        # Confidence: rises with history depth; penalised by high variance
        # in segment distances (erratic movement = less certain prediction).
        depth_score = min(n / self.sequence_length, 1.0)
        if len(seg_dists_m) > 1:
            cv = float(np.std(seg_dists_m) / (np.mean(seg_dists_m) + 1e-9))
            variance_penalty = max(0.0, 1.0 - cv * 0.3)
        else:
            variance_penalty = 1.0
        confidence = round(depth_score * variance_penalty, 3)

        return {
            "predicted_latitude":     predicted_lat,
            "predicted_longitude":    predicted_lon,
            "confidence":             confidence,
            "segment_distance_m":     round(self._last_segment_m, 2),
            "cumulative_distance_km": round(self._cumulative_dist_km, 4),
        }

    # ── Persistence helpers ───────────────────────────────────────────────────

    def _persist_entry(self, lat: float, lon: float, ts: float) -> None:
        """Appends a single entry to the on-disk history file (non-blocking
        and exception-safe so a disk error never crashes the safety system)."""
        try:
            existing: list = []
            if os.path.exists(_HISTORY_FILE):
                with open(_HISTORY_FILE, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)

            existing.append({
                "timestamp": datetime.fromtimestamp(ts).isoformat(),
                "latitude":  round(lat, 7),
                "longitude": round(lon, 7),
            })

            # Trim to avoid unbounded file growth.
            if len(existing) > _MAX_PERSISTED:
                existing = existing[-_MAX_PERSISTED:]

            with open(_HISTORY_FILE, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, separators=(",", ":"))
        except Exception as exc:
            print(f"[Predictor] Persist warning: {exc}")

    def _load_history(self) -> None:
        """Seeds the in-memory buffer from the persisted history file on
        startup so the model benefits from prior trajectory context."""
        if not os.path.exists(_HISTORY_FILE):
            return
        try:
            with open(_HISTORY_FILE, "r", encoding="utf-8") as fh:
                entries: list = json.load(fh)
            # Take only the last `sequence_length` entries.
            recent = entries[-self.sequence_length:]
            for e in recent:
                ts = time.mktime(datetime.fromisoformat(e["timestamp"]).timetuple())
                self._lats.append(float(e["latitude"]))
                self._lons.append(float(e["longitude"]))
                self._timestamps.append(float(ts))
            print(f"[Predictor] Loaded {len(recent)} historical waypoints from disk.")
        except Exception as exc:
            print(f"[Predictor] History load warning: {exc}")

    # ── Utility ───────────────────────────────────────────────────────────────

    def get_history_summary(self) -> dict:
        """Returns a snapshot of the current in-memory trajectory state."""
        return {
            "buffer_depth":           len(self._lats),
            "sequence_length":        self.sequence_length,
            "cumulative_distance_km": round(self._cumulative_dist_km, 4),
            "last_segment_m":         round(self._last_segment_m, 2),
            "last_known_lat":         self._lats[-1] if self._lats else None,
            "last_known_lon":         self._lons[-1] if self._lons else None,
        }

    def reset(self) -> None:
        """Clears the in-memory buffer (does not delete the persisted file)."""
        self._lats.clear()
        self._lons.clear()
        self._timestamps.clear()
        self._cumulative_dist_km = 0.0
        self._last_segment_m     = 0.0


# ── Standalone smoke-test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("[LSTM Predictor] Running standalone smoke-test …")
    predictor = LSTMTrajectoryPredictor(sequence_length=8)

    # Simulate a walk along a real street in Parangipettai area.
    sample_route = [
        (11.4889, 79.7538),
        (11.4875, 79.7520),
        (11.4861, 79.7502),
        (11.4847, 79.7484),
        (11.4833, 79.7466),
        (11.4819, 79.7448),
        (11.4805, 79.7430),
        (11.4791, 79.7412),
    ]

    for lat, lon in sample_route:
        predictor.update_history(lat, lon)

    result = predictor.predict_next_coordinate()
    print(f"  Last GPS:         {sample_route[-1]}")
    print(f"  Predicted Next:   Lat {result['predicted_latitude']}, "
          f"Lon {result['predicted_longitude']}")
    print(f"  Confidence:       {result['confidence'] * 100:.1f}%")
    print(f"  Segment dist:     {result['segment_distance_m']:.1f} m")
    print(f"  Trip distance:    {result['cumulative_distance_km']:.4f} km")
    print(f"  Summary: {predictor.get_history_summary()}")