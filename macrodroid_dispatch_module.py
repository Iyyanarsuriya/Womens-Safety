"""
macrodroid_dispatch_module.py
──────────────────────────────────────────────────────────────────────────
MacroDroid SOS Webhook Dispatcher — Production Edition
Sends a GET request to the MacroDroid webhook endpoint with:
  • p1_number  — Priority-1 emergency contact (raw 10-digit mobile)
  • p2_number  — Priority-2 emergency contact (raw 10-digit mobile)
  • maps_link  — Live Google Maps URL constructed from lat/lon telemetry

Design guarantees:
  • Always runs in a daemon thread → zero UI blocking.
  • Auto-retries up to MAX_RETRIES times with exponential back-off.
  • Fully backwards-compatible with main_controller.py's call signature:
        trigger_aura_sos(p1, p2, lat, lon)
"""

import threading
import time
import urllib.parse
import urllib.request
import urllib.error

# ── Webhook Configuration ────────────────────────────────────────────────────
MACRODROID_WEBHOOK_URL = (
    "https://trigger.macrodroid.com/"
    "63554a22-bcbd-42b0-b875-24a60ae18ac5/aura_sos"
)

MAX_RETRIES   = 3          # how many times to try before giving up
RETRY_DELAY_S = 2.0        # base seconds between retries (doubles each time)
TIMEOUT_S     = 10         # per-request socket timeout


# ── Internal helpers ─────────────────────────────────────────────────────────

def _build_url(p1: str, p2: str, lat: float, lon: float) -> str:
    """Returns the full request URL with properly URL-encoded query params."""
    maps_link = f"https://maps.google.com/?q={lat},{lon}"
    params = {
        "p1_number": p1,
        "p2_number": p2,
        "maps_link": maps_link,
    }
    return f"{MACRODROID_WEBHOOK_URL}?{urllib.parse.urlencode(params)}"


def _sanitize_number(raw) -> str:
    """Strip all non-digit characters and return the cleaned number string."""
    if raw is None:
        return ""
    return "".join(ch for ch in str(raw) if ch.isdigit())


def _send_sos_worker(p1: str, p2: str, lat: float, lon: float) -> None:
    """
    Background worker.  Builds the request URL, attempts the GET with
    retries, and prints a rich status summary.
    """
    p1 = _sanitize_number(p1)
    p2 = _sanitize_number(p2)

    if not p1 and not p2:
        print("\n[MacroDroid] Dispatch aborted — both contact numbers are empty.")
        return

    url = _build_url(p1, p2, lat, lon)
    maps_link = f"https://maps.google.com/?q={lat},{lon}"

    print("\n" + "=" * 60)
    print("AURA SOS DISPATCH - MacroDroid Webhook")
    print(f"   P1 Contact : {p1 or '-'}")
    print(f"   P2 Contact : {p2 or '-'}")
    print(f"   Location   : {maps_link}")
    print(f"   Endpoint   : {MACRODROID_WEBHOOK_URL}")
    print("=" * 60)

    delay = RETRY_DELAY_S
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"   Attempt {attempt}/{MAX_RETRIES} - sending ... ", end="", flush=True)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "AURA-Safety-System/3.0"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                status = resp.status
                if status == 200:
                    print("SUCCESS")
                    print(f"   HTTP {status} - SOS alert delivered to MacroDroid cloud.")
                    print("=" * 60 + "\n")
                    return
                else:
                    print(f"HTTP {status}")
        except urllib.error.URLError as exc:
            print(f"Network error: {exc.reason}")
        except Exception as exc:
            print(f"Unexpected error: {exc}")

        if attempt < MAX_RETRIES:
            print(f"   Retrying in {delay:.1f}s ...")
            time.sleep(delay)
            delay *= 2          # exponential back-off

    print(f"   All {MAX_RETRIES} attempts failed. SOS webhook could not be delivered.")
    print("=" * 60 + "\n")


# ── Public API ───────────────────────────────────────────────────────────────

def trigger_aura_sos(
    p1_number,
    p2_number,
    latitude: float,
    longitude: float,
) -> None:
    """
    Non-blocking SOS dispatcher.

    Spawns a daemon thread that fires the MacroDroid webhook with
    p1_number, p2_number, and a live Google Maps URL.  Returns
    immediately - the caller's thread (including the Tkinter main loop)
    is never blocked.

    Args:
        p1_number  : Priority-1 contact number (str or int, digits only).
        p2_number  : Priority-2 contact number (str or int or None).
        latitude   : Current GPS latitude  (float).
        longitude  : Current GPS longitude (float).
    """
    t = threading.Thread(
        target=_send_sos_worker,
        args=(p1_number, p2_number, float(latitude), float(longitude)),
        daemon=True,
        name="MacroDroid-SOS-Dispatcher",
    )
    t.start()


# ── Standalone test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    import json
    import sys
    print("=== MacroDroid Dispatch Module - Dynamic Webhook Dispatch ===")
    p1 = "9876543210"
    p2 = "9123456780"
    lat, lon = 0.0, 0.0
    prof_path = os.path.join("data", "user_profile.json")
    if os.path.exists(prof_path):
        try:
            with open(prof_path, "r", encoding="utf-8") as f:
                prof = json.load(f)
                cts = prof.get("contacts", [])
                if len(cts) > 0:
                    p1 = cts[0].get("phone", p1)
                if len(cts) > 1:
                    p2 = cts[1].get("phone", p2)
        except Exception:
            pass
    if len(sys.argv) >= 3:
        p1, p2 = sys.argv[1], sys.argv[2]
    print(f"Dispatching SOS to P1: {p1}, P2: {p2} (lat: {lat}, lon: {lon})...")
    trigger_aura_sos(p1, p2, lat, lon)
    time.sleep(5)
    print("Test complete.")