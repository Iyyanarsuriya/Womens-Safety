# 🛡️ AURA — AI-Powered Women Safety System

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/System-Active%20%26%20Verified-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-purple.svg)]()

**AURA** is an offline-first, edge-intelligent personal safety system designed for women's security. It integrates **hardware fall detection** (accelerometer + gyroscope), **LSTM trajectory prediction with spatial clustering fallback**, **stateful geofencing**, **loud emergency sirens**, **audio evidence collection**, and **priority-based Android phone calling and SMS dispatch** with automatic cloud/offline synchronization.

---

## 🌟 Key Features

1. **Reliable Phone Fall & Drop Detection**
   - Multi-phase fall analysis combining **freefall weightlessness** ($< 6.0\text{ m/s}^2$), **gyroscope rotational tumble** ($> 2.0\text{ rad/s}$), and **high-G impact** ($> 8.0 - 25.0\text{ m/s}^2$) within a $2.5\text{s}$ window.
   - Built-in debouncing to eliminate false alarms.

2. **15s / 30s Emergency Countdown & "I'm Safe" Option**
   - Configurable countdown timer with a circular visual interface.
   - **"🛡️ I AM SAFE"** dismissal button or `ESC` key to immediately disarm threats.
   - If unanswered, the system **automatically escalates to full emergency mode**.

3. **Autonomous Emergency Escalation**
   - **Audible Siren / Alarm**: Triggers an alert siren on the device.
   - **Real-Time GPS & Map Link**: Retrieves GPS coordinates (or last-known fix) and generates a Google Maps URL.
   - **Guardian SMS Notification**: Dispatches emergency alert messages with live location links to configured guardians.
   - **Priority-Based Android Calling**: Attempts an immediate call to Priority 1 (P1). If unanswered or restricted, escalates to Priority 2 (P2). Adheres to Android runtime policies by falling back from direct `CALL` intent to `DIAL` intent if permissions are restricted.
   - **Audio Evidence Recording**: Automatically captures $15\text{s}$ emergency audio saved in `recordings/audio/`.

4. **Offline-First System with Automatic Backend Synchronization**
   - All emergency events, audio evidence, and geofence logs are written locally first to `data/offline_events_vault.json`.
   - Autonomous background synchronization daemon monitors backend connectivity.
   - Automatically uploads pending emergency logs and multipart audio recordings to the Flask/SQLite backend upon network restoration.

5. **Stateful Safe-Location Geofencing**
   - Define custom safe zones (e.g., Home, Campus, Workplace) with configurable radii.
   - Tracks real-time boundary transitions: triggers breach alarms on **EXIT** and safe notifications on **ENTRY**.
   - Persists safe zones in `data/safe_zones.json`.

6. **LSTM Next-Location Prediction & Cluster Zone Fallback**
   - Exponentially weighted sequence extrapolation approximating an LSTM recurrent state.
   - Spatial clustering mines historical waypoints from `data/location_log.csv` into regional clusters.
   - **Practical Fallback**: Automatically anchors to the nearest cluster centroid when GPS history is minimal ($< 2$ points) or erratic.
   - **Adaptive Sampling**: Filters duplicate points when stationary to minimize battery usage and storage footprint.

7. **Interactive Route Map & Simulator**
   - Main dashboard includes an embedded live route canvas with position markers, breadcrumb trail, and predicted beacons.
   - Includes a standalone **Interactive Map Simulator** with hotkeys (`↑↓←→` movement, `D` deviation jump, `S` speed multiplier, `Space` play/pause).

8. **Profile Persistence Across Restarts**
   - User profile, contact lists, safe zones, and countdown timers are stored in `data/user_profile.json`.
   - Reopening the app restores all settings and protection without requiring re-setup.

---

## 📂 Project Structure

```plaintext
Safety_System/
├── app.py                         # Flask REST API & SQLite Backend Engine
├── main.py                        # System Launcher (Desktop Dashboard & Master Controller)
├── main_controller.py             # Central Safety Engine coordinating all modules
├── gui_module.py                  # Modern Tkinter Dark-Mode UI & Threat Popups
├── fall_detector.py               # Accelerometer + Gyroscope Fall Detection Streamer
├── location_module.py             # GPS Maths, Haversine Speed & Stateful GeofenceManager
├── prediction_module.py           # LSTM Trajectory Predictor & Spatial Cluster Fallback
├── sync_manager.py                # Offline-First Event Queue & Background Sync Daemon
├── android_telephony_module.py    # Prioritized Calling, CALL/DIAL Fallback & SMS Dispatch
├── macrodroid_dispatch_module.py  # MacroDroid Cloud Webhook SOS Dispatcher
├── gps_bridge_module.py           # TCP Bridge receiving live GPS fixes from Android (Port 8082)
├── network_monitor_module.py      # Cellular/WiFi Connectivity & Hotspot Poller
├── acoustic_module.py             # Vosk Offline Voice Recognition & Audio Evidence Capture
├── sensor_module.py               # Hardware System Diagnostics & Evidence Capture
├── anomaly_engine.py              # Speed and Route Deviation Detection
├── map_simulator.py               # Standalone Interactive Canvas Route Simulator
├── map_config.py                  # Geocoordinates, Waypoints & Pixel-to-GPS Projection
├── test_system.py                 # Automated Test Suite (9 Tests covering all features)
├── requirements.txt               # Python Dependencies
├── data/
│   ├── backend_safety.db          # Backend SQLite Database
│   ├── location_log.csv           # Historical GPS Dataset
│   ├── offline_events_vault.json  # Offline Local Events Queue
│   ├── safe_zones.json            # Persisted Geofence Zones
│   └── user_profile.json          # Persisted Profile & Emergency Contacts
├── recordings/
│   ├── audio/                     # Recorded Emergency Audio Evidence (.wav)
│   └── video/                     # Recorded Silent Video Evidence (.avi)
└── model/                         # Vosk Offline Speech Recognition Model
```

---

## ⚙️ Installation & Prerequisites

### 1. Requirements
- Python 3.10, 3.11, 3.12, or 3.13
- Windows 10/11 (with Tkinter and audio support)

### 2. Install Python Dependencies
Open PowerShell or Command Prompt in the project folder and run:
```powershell
pip install -r requirements.txt
```

---

## 🚀 Running the System

### Step 1: Start the Backend Server
In the first terminal window, start the Flask REST API and SQLite database engine:
```powershell
python app.py
```
*Runs on `http://127.0.0.1:5000` and creates `data/backend_safety.db`.*

### Step 2: Start the Safety Application
In a second terminal window, launch the master safety dashboard:
```powershell
python main.py
```
*Launches the GUI dashboard, loads your profile, and begins active safety monitoring.*

---

## 🧪 Automated Testing

A test suite covers the entire safety pipeline:
```powershell
python test_system.py
```

### Verified Test Cases:
| Test ID | Component Verified | Expected Outcome |
| :--- | :--- | :--- |
| `test_01` | Backend Health & SQLite DB | HTTP 200, database tables initialized |
| `test_02` | Phone Fall Detection | Freefall + Gyro Tumble + Impact fires emergency callback |
| `test_03` | GPS & Maps Link | Generates valid GPS coordinate maps link |
| `test_04` | Stateful Geofencing | Detects discrete `EXIT` breach and `ENTRY` safe events |
| `test_05` | LSTM & Cluster Prediction | Generates trajectory extrapolation + cluster zone fallback |
| `test_06` | Android Telephony & Permissions | Priority call escalation (P1 $\rightarrow$ P2), CALL/DIAL fallback, SMS |
| `test_07` | Offline Storage & Sync | Queues locally, syncs to backend SQLite, marks `SYNCED` |
| `test_08` | Master Emergency Sequence | Siren + GPS + SMS + Calls + Audio + Sync execution |
| `test_09` | Profile Persistence | Settings restored across application restarts |

---

## 📱 Connecting a Physical Android Phone (Optional)

To connect an Android phone for physical hardware sensor streaming and calling:

1. **Enable Developer Options & USB Debugging** on the phone.
2. **Connect Phone via USB** and run port forwarding:
   ```powershell
   adb forward tcp:8080 tcp:8080
   adb forward tcp:8082 tcp:8082
   ```
3. **Sensor Streaming**:
   - Stream accelerometer and gyroscope JSON telemetry to port `8080` (via Termux, Sensor Node, or IP Webcam).
   - Stream GPS NMEA/JSON telemetry to port `8082`.
4. **Emergency Calling & SMS**:
   - Calls execute via Android Intent (`CALL`, falling back to `DIAL` if unprivileged).
   - Emergency SMS dispatches via local SIM (Termux API) or the MacroDroid webhook.

---

## 📡 REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/status` | `GET` | Health check and database record metrics |
| `/update_location` | `POST` | Ingests GPS telemetry, computes speed, checks route deviation |
| `/fall_detected` | `POST` | Hardware fall alert trigger |
| `/battery_status` | `POST` | Logs host and mobile device battery status |
| `/api/emergency/event` | `POST` | Saves complete emergency dispatch details |
| `/api/emergency/upload_audio` | `POST` | Multipart upload for emergency audio files |
| `/api/emergency/events` | `GET` | Returns list of recorded emergency events |
| `/api/geofence/event` | `POST` | Logs safe zone `ENTRY` or `EXIT` transitions |
| `/api/sync` | `POST` | Batch synchronization endpoint for offline edge devices |

---

## 🔒 Security & Privacy
- **Encrypted Evidence Vault**: Files can be encrypted using Fernet symmetric encryption ([vault.key](file:///c:/Users/iyyan/Downloads/Safety_System%20%282%29/Safety_System/vault.key)).
- **Duress Deactivation PIN**: Entering the fake PIN (`9999`) activates stealth lock mode while silently triggering the emergency dispatch sequence.
- **Local-First Architecture**: Audio recordings and location traces remain strictly on the local machine and your private backend server.
