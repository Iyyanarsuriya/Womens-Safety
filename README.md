# 🛡️ AURA — AI-Powered Women Safety System

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-22%20Passed%20%28100%25%29-brightgreen.svg)]()
[![Status](https://img.shields.io/badge/System-Active%20%26%20Verified-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-purple.svg)]()

**AURA** is an offline-first, edge-intelligent personal safety system designed for women's security. It integrates **hardware fall detection** (accelerometer + gyroscope), **LSTM trajectory prediction with spatial clustering fallback**, **stateful geofencing**, **realistic cartographic vector mapping**, **mission control simulation**, **in-app audio/video evidence players**, and **priority-based Android phone calling & SMS dispatch** with automatic cloud/offline synchronization.

---

## 🌟 Key Features

1. **Reliable Phone Fall & Drop Detection**
   - Multi-phase fall analysis combining **freefall weightlessness** ($< 6.0\text{ m/s}^2$), **gyroscope rotational tumble** ($> 2.0\text{ rad/s}$), and **high-G impact** ($> 8.0 - 25.0\text{ m/s}^2$) within a $2.5\text{s}$ window.
   - Built-in debouncing and deduplication to prevent duplicate triggers.

2. **15s / 30s Emergency Countdown & "I'm Safe" Option**
   - Configurable countdown timer with a circular visual interface for fall detection and route deviations.
   - **"🛡️ I AM SAFE"** dismissal button or `ESC` key to immediately disarm threats and engage safe cooldown.
   - **Instant SOS bypass**: Manual SOS and direct emergencies dispatch immediately without countdown.

3. **Autonomous Emergency Escalation & Telephony**
   - **Audible Siren / Alarm**: Triggers an alert siren on the device.
   - **Real-Time GPS & Map Link**: Retrieves GPS coordinates and generates an accurate Google Maps URL.
   - **Guardian SMS Notification**: Dispatches emergency alert messages with live location links to configured guardians.
   - **Priority-Based Android Calling**: Initiates calls to Priority 1 (P1); if unanswered or restricted, escalates to Priority 2 (P2). Adheres to Android runtime policies by falling back from direct `CALL` intent to `DIAL` intent if permissions are restricted.
   - **Automated Call Escalation**: Configurable 60–120s response timeout before sequential escalation.

4. **In-App Media Player & Resilient Audio/Video Evidence**
   - **Built-in Video Player**: In-app OpenCV + Tkinter video playback with play/pause/replay and seek slider.
   - **Built-in Audio Player**: Interactive audio player with live waveform visualizer and timecode controls.
   - **Universal Hardware Fallbacks**: Automatically probes all camera backends (`CAP_DSHOW`, `CAP_MSMF`, `CAP_ANY`) and microphone devices; generates timestamped simulated video frames (with HUD overlay and telemetry watermark) and synthesized WAV audio when hardware devices are unplugged.
   - **Evidence Vault Management**: Single, batch, and bulk deletion of recordings with automatic sync queue cleanup.

5. **Realistic Cartographic City Map & Free Roaming**
   - Dark-mode vector city map rendering **Marine Riverfront Channel**, **Sanctuary Nature Reserve**, **Botanical Campus Gardens**, **NH-45 Express Highway** (with casing, divider, and route shield), and city POIs (**Police Precinct 4**, **Apex Hospital**, **Metro Central**, **Campus Sanctuary**).
   - **Free Live Roaming**: Click anywhere on the map or drag the user marker to roam freely; on-canvas interactive D-Pad and keyboard arrow keys for directional stepping.
   - **Planned Safe Route Corridor**: High-visibility green corridor with waypoints leading directly to destination.

6. **👁️ Display Only (Show Only) Feature**
   - Dedicated mode toggle: **`[ 👁️ DISPLAY ONLY (SHOW ONLY) ]`** vs **`[ 🛡️ ARMED ACTION MODE ]`**.
   - **Show Only Mode**: View tracking, speed, street names, safe corridors, and deviation lines visually without executing emergency actions (suppresses sirens, countdown screens, phone calls, and SMS dispatches).
   - **Armed Mode**: Anomaly triggers active emergency countdown and alert dispatch.

7. **🗺️ Master Map Mission Control ("Control Everything from the Map")**
   - Dedicated Mission Control window (`map_simulator.py`) allowing complete system control:
     - 🚨 **Manual SOS Trigger**: Dispatch emergency distress signal directly.
     - 💥 **Simulate Fall**: Inject freefall + impact sequence.
     - ↗️ **Route Deviate**: Shift path off-corridor to test deviation detection.
     - ⚡ **Speed Anomaly Boost**: Inject sudden excessive velocity.
     - ✅ **"I'm Safe" / Reset**: Clear all threats and reset alarms with safe cooldown.
     - 🎯 **Destination Quick Select**: Campus Sanctuary, Home Sanctuary, Metro Central, Police Precinct 4.
     - 🚶/🚴/🚗/⚡ **Pace & Speed Multipliers**: 5 km/h (Walk), 15 km/h (Cycle), 45 km/h (Drive), 80 km/h (Fast), and ×1, ×2, ×4, ×8 multipliers.
     - 🔄 **Bidirectional Live Synchronization**: Movements and actions in the control map instantly update the main dashboard, controller, and LSTM predictor in real time.

8. **Offline-First System with Automatic Backend Synchronization**
   - Offline-first storage in `data/offline_events_vault.json` with an autonomous background sync daemon.
   - Automatically uploads pending emergency logs and multipart audio recordings to the Flask/SQLite backend upon network restoration.

9. **Stateful Safe-Location Geofencing & LSTM Prediction**
   - Custom safe zones (Home, Campus, Workplace) with real-time transition detection (`ENTRY` and `EXIT`).
   - Exponentially weighted LSTM trajectory extrapolation with regional spatial cluster fallback.

10. **Enhanced Network & Hotspot Monitoring**
    - Multi-stage hysteresis debouncing (3 failures to trigger, 2 successes to recover, 1000ms ping timeout) to eliminate connected/disconnected alert loops.
    - Silent baseline initialization on startup.
    - Zero occurrences of the forbidden word "online" across all UI telemetry and badges.

---

## 📂 Project Structure

```plaintext
Safety_System/
├── app.py                         # Flask REST API & SQLite Backend Engine
├── main.py                        # System Launcher (Desktop Dashboard & Master Controller)
├── main_controller.py             # Central Safety Engine coordinating all modules
├── gui_module.py                  # Modern Tkinter Dark-Mode UI, Map Canvas & Threat Handlers
├── map_simulator.py               # Live Map Intelligence & Master Mission Control Center
├── map_config.py                  # Cartographic Projections, Coordinates & Safe Routes
├── fall_detector.py               # Accelerometer + Gyroscope Fall Detection Streamer
├── location_module.py             # GPS Maths, Haversine Speed & Stateful GeofenceManager
├── prediction_module.py           # LSTM Trajectory Predictor & Spatial Cluster Fallback
├── sync_manager.py                # Offline-First Event Queue & Background Sync Daemon
├── android_telephony_module.py    # Prioritized Calling, CALL/DIAL Fallback & SMS Dispatch
├── macrodroid_dispatch_module.py  # MacroDroid Cloud Webhook SOS Dispatcher
├── gps_bridge_module.py           # TCP Bridge receiving live GPS fixes from Android (Port 8082)
├── network_monitor_module.py      # Cellular/WiFi Connectivity & Hotspot Poller (Debounced)
├── acoustic_module.py             # Vosk Offline Voice Recognition & Audio Evidence Capture
├── sensor_module.py               # Hardware Diagnostics & Evidence Capture (Audio/Video)
├── anomaly_engine.py              # Speed and Route Deviation Detection Engine
├── reset_db.py                    # Database & Vault Reset Tool (supports --all and --fresh)
├── test_system.py                 # Automated Test Suite (22 Comprehensive Tests)
├── requirements.txt               # Python Dependencies
├── data/
│   ├── backend_safety.db          # Backend SQLite Database
│   ├── current_trip.json          # Persisted Trip & Destination
│   ├── location_log.csv           # Historical GPS Dataset
│   ├── offline_events_vault.json  # Offline Local Events Queue
│   ├── safe_zones.json            # Persisted Geofence Zones
│   └── user_profile.json          # Persisted Profile & Emergency Contacts
├── recordings/
│   ├── audio/                     # Recorded Emergency Audio Evidence (.wav)
│   └── video/                     # Recorded Emergency Video Evidence (.avi)
└── model/                         # Vosk Offline Speech Recognition Model
```

---

## ⚙️ Installation & Setup Commands

### 1. Prerequisites
- **Python**: Version 3.10, 3.11, 3.12, or 3.13 installed.
- **Operating System**: Windows 10 or 11 (fully supported with Tkinter, OpenCV, PyAudio, Pygame, and Pillow).

### 2. Environment Setup & Dependency Installation

Open PowerShell or Command Prompt in the project directory:

```powershell
# Optional: Create and activate a clean virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install all required dependencies
pip install -r requirements.txt
```

---

## 🚀 Commands to Run the System

To run the complete safety system, you will use two terminal windows:

### Terminal 1 — Start the Backend Server
```powershell
python app.py
```
> **What this does**:
> - Launches the Flask REST API on `http://127.0.0.1:5000`.
> - Creates and connects the SQLite database (`data/backend_safety.db`).
> - Listens for emergency events, audio evidence uploads, geofence breaches, and route telemetry.

### Terminal 2 — Start the Master Application & Dashboard
```powershell
python main.py
```
> **What this does**:
> - Launches the Tkinter Dark-Mode Safety Dashboard with live cartographic map.
> - Initializes master safety controller, fall detector, network monitor, GPS bridge, and offline sync manager.
> - Defaults to **`👁️ DISPLAY ONLY (SHOW ONLY)`** mode for safe, unhindered map roaming.
> - Restores your saved profile, contacts, and destinations automatically.

---

### 🧪 Automated Verification Test Suite

To verify all system features end-to-end without physical hardware:

```powershell
python -m unittest test_system.py
```
> **Runs all 22 automated integration tests (100% Passing)**:
> 1. `test_01`: Backend API & SQLite DB initialization
> 2. `test_02`: Dual-sensor Phone Fall Detection algorithm (Freefall + Gyro tumble + High-G impact)
> 3. `test_03`: GPS acquisition & Google Maps link generation
> 4. `test_04`: Stateful Geofencing (`ENTRY` & `EXIT` boundary transitions)
> 5. `test_05`: LSTM trajectory extrapolation & cluster zone fallback
> 6. `test_06`: Android telephony, CALL/DIAL fallback & SMS dispatch
> 7. `test_07`: Offline-first vault queue & backend SQLite sync
> 8. `test_08`: Master emergency execution sequence
> 9. `test_09`: Profile persistence across restarts
> 10. `test_10`: Phone USB fall detection debounce & single SMS constraint
> 11. `test_11`: Manual live map continuous movement demo isolation
> 12. `test_12`: Speed increase & route deviation safety alert with cooldown
> 13. `test_13`: Multi-contact emergency SMS with precise location links
> 14. `test_14`: Automated call escalation after 60-120s timeout & user cancellation
> 15. `test_15`: Dedicated low-battery warning SMS (<15%) without false SOS
> 16. `test_16`: Hotspot & network connectivity loss alarm, debounce, and recovery
> 17. `test_17`: Predefined trip destination persistence & clearing
> 18. `test_18`: Fake shutdown duress PIN (9999) & blackbox vault logging
> 19. `test_19`: Audio & video evidence deletion (single, batch, bulk) with sync queue cleanup
> 20. `test_20`: Countdown conditions (fall/route only), manual SOS bypass & offline phone alert
> 21. `test_21`: Realistic vector map, free movement, D-Pad & absence of forbidden 'Online' word
> 22. `test_22`: Unwanted continuous alert prevention, trip start tolerance & SOS deduplication

---

### 🗺️ Master Map Mission Control Center

Launch the standalone Master Map Mission Control window to control the entire safety system from the map:

```powershell
python map_simulator.py
```
> **Mission Control Capabilities**:
> - Click or drag anywhere on the map to roam freely.
> - Switch between **`👁️ DISPLAY ONLY (SHOW ONLY)`** and **`🛡️ ARMED ACTION MODE`**.
> - Trigger emergency actions: **`🚨 TRIGGER SOS`**, **`💥 Fall Drop`**, **`↗ Deviate`**, **`⚡ Speed Boost`**, **`✅ I'm Safe`**.
> - Quick destination selector: **Campus**, **Home**, **Metro**, **Police**.
> - Pace selector: **🚶 5 km/h**, **🚴 15 km/h**, **🚗 45 km/h**, **⚡ 80 km/h** with **×1, ×2, ×4, ×8** multipliers.
> - Bidirectional live sync with the main dashboard.

---

### 🗑️ Database & Media Reset Commands

To wipe test data, clear events, or start completely fresh:

```powershell
# 1. Reset only SQLite database tables (clears emergency events, audio metadata, logs)
python reset_db.py

# 2. Reset SQLite database + cached offline JSON vaults
python reset_db.py --all

# 3. Full Fresh Reset (wipes database, vaults, logs, and deletes all recorded audio & video files)
python reset_db.py --fresh
```

---

## 🛠️ User Guide & Interface Walkthrough

### 1. Initial Setup Screen (First-Time User)
When launching `main.py` for the first time:
1. **FULL NAME**: Enter user's name (e.g., `Priya Sharma`).
2. **MOBILE NUMBER**: Enter 10-digit mobile number.
3. **EMERGENCY CONTACTS**:
   - Click **`+ Add`** to add guardian contacts.
   - Contact at **P1** receives highest priority (called and texted first), followed by **P2**.
4. Click **`ACTIVATE SYSTEM PROTECTION ➔`**:
   - Automatically initializes the speech engine, background listeners, and monitoring loops.
   - Saves profile to `data/user_profile.json` and opens directly into the active dashboard on all future launches.

---

### 2. Live Route Map & Display-Only Mode
On the dashboard:
- **`👁️ DISPLAY ONLY (SHOW ONLY)`**: Click to toggle between Display-Only mode and Armed Action Mode.
  - When in Display-Only mode: freely click and drag the user marker across streets, test deviations, and view speed without triggering emergency sirens or SMS dispatches.
- **`🗺️ Open Interactive Map Simulator`**: Opens the Master Map Mission Control window.
- **`🔄 Clear Map Path`**: Clears the breadcrumb trail.

---

### 3. Media & Evidence Manager
Access via Quick Controls:
- **`🎥 Record 5s Video`**: On-demand camera evidence test.
- **`🎙️ Record 5s Audio`**: On-demand microphone evidence test.
- **In-App Players**: Click on any recorded `.avi` video or `.wav` audio file in the Evidence Vault to view or listen directly in the app.
- **Deletion Controls**: Select files to delete individually or purge in batches with automatic synchronization queue cleanup.

---

### 4. Disarm & Stealth Duress PIN Dialog (`🔒` Button)
Click the **`🔒 Disarm`** icon in the top-right bar:
- **Real PIN (`1234`)**: Disarms the system gracefully and deactivates emergency monitoring.
- **Duress Fake PIN (`9999`)**: Entering the fake PIN triggers **Stealth Lock Mode**:
  - The screen turns completely black with hidden cursor (mimicking a shut down / crashed PC).
  - Silently dispatches the full emergency sequence (retrieves GPS, logs map link, calls guardians, sends SMS, and alerts the backend).

---

## 📱 Connecting a Physical Android Phone (Optional)

To stream real-time accelerometer, gyroscope, and GPS data from an Android smartphone:

### Step 1: Enable USB Debugging
1. Go to **Settings $\rightarrow$ About Phone** and tap **Build Number** 7 times.
2. Go to **Developer Options** and enable **USB Debugging**.

### Step 2: Establish Port Forwarding
Connect your phone via USB cable and run in PowerShell:
```powershell
# Verify device is detected
adb devices

# Forward phone sensor stream (Accelerometer + Gyroscope)
adb forward tcp:8080 tcp:8080

# Forward phone GPS stream (Location coordinates)
adb forward tcp:8082 tcp:8082
```

### Step 3: Stream Sensors from Phone
- **Sensors (Port 8080)**: Stream sensor JSON payloads (`accelerometer`, `gyroscope`).
- **GPS (Port 8082)**: Stream GPS location packets (`{"latitude": ..., "longitude": ...}`).
- **Phone Calls & SMS**: Calls initiate automatically via Android Intents (`CALL` intent, with fallback to `DIAL`), while SMS dispatches via local SIM or MacroDroid webhook.

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
- **Encrypted Evidence Vault**: Files can be encrypted using Fernet symmetric encryption.
- **Duress Deactivation PIN**: Entering the fake PIN (`9999`) activates stealth lock mode while silently triggering the emergency dispatch sequence.
- **Local-First Architecture**: Audio recordings, video clips, and location traces remain strictly on the local machine and your private backend server.
