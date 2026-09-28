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

## ⚙️ Installation & Setup Commands

### 1. Prerequisites
- **Python**: Version 3.10, 3.11, 3.12, or 3.13 installed.
- **Operating System**: Windows 10 or 11 (fully supported with Tkinter, audio mixer, and camera support).

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
> - Launches the Tkinter Dark-Mode Safety Dashboard.
> - Initializes the master safety controller, fall detector, network monitor, GPS bridge, and offline sync manager.
> - Restores your saved profile and safe zones automatically.

---

## 🧪 Command to Run Automated Verification Tests

To verify all system features end-to-end without physical hardware:

```powershell
python test_system.py
```
> **Runs all 9 automated test suites in ~8.6 seconds**:
> 1. `test_01`: Backend API & SQLite DB initialization
> 2. `test_02`: Dual-sensor Phone Fall Detection algorithm
> 3. `test_03`: GPS acquisition & Google Maps link generation
> 4. `test_04`: Stateful Geofencing (`ENTRY` & `EXIT` boundary transitions)
> 5. `test_05`: LSTM trajectory extrapolation & cluster zone fallback
> 6. `test_06`: Android telephony, CALL/DIAL fallback & SMS dispatch
> 7. `test_07`: Offline-first vault queue & backend SQLite sync
> 8. `test_08`: Master emergency execution sequence
> 9. `test_09`: Profile persistence across restarts

---

## 🛠️ Setup Functionality & User Guide

### 1. Initial Setup Screen (First-Time User)
When launching `main.py` for the first time without an existing profile:
1. **FULL NAME**: Enter the user's name (e.g., `Priya Sharma`).
2. **MOBILE NUMBER**: Enter the user's 10-digit mobile number.
3. **EMERGENCY CONTACTS**:
   - Click **`+ Add`** to add one or more contacts.
   - Enter **Contact Name** and a valid **10-digit Mobile Number**.
   - Contact at position **P1** is treated as highest priority (called and texted first), followed by **P2**.
4. Click **`ACTIVATE SYSTEM PROTECTION ➔`**:
   - Automatically initializes the speech engine, background listeners, and monitoring loop.
   - **Saves your profile to `data/user_profile.json`**.
   - **On future launches, the app automatically loads your saved profile and opens directly into the active dashboard!**

---

### 2. Settings Configuration Dialog (`⚙️` Button)
Click the **`⚙️ Settings`** icon in the top-right bar of the dashboard:
- **Change Registered Name / Mobile**: Update your personal details.
- **SOS Countdown Delay**: Choose between **15 seconds** or **30 seconds** for the emergency confirmation window.
- **Manage Contacts**:
   - Reorder priority using **`↑`** and **`↓`** buttons.
   - Delete contacts with **`✖`**.
   - Add new contacts with **`+ Add Emergency Contact`**.
- **Safe Zones / Geofences**:
   - View active safe zones and their radius.
   - Click **`+ Add Current Location as Safe Zone`** to register your current position (Home, College, Office) with a custom radius in kilometers.
   - Delete safe zones using **`✖`**.
- Click **`SAVE CHANGES`** to instantly apply and persist updates to disk.

---

### 3. Disarm & Stealth Duress PIN Dialog (`🔒` Button)
Click the **`🔒 Disarm`** icon in the top-right bar:
- **Real PIN (`1234`)**: Disarms the system gracefully and deactivates emergency monitoring.
- **Duress Fake PIN (`9999`)**: If forced by an attacker to turn off the app, entering the fake PIN triggers **Stealth Lock Mode**:
  - The screen turns completely black with hidden cursor (mimicking a shut down / crashed PC).
  - Silently dispatches the full emergency sequence (retrieves GPS, logs map link, calls guardians, sends SMS, and alerts the backend).

---

### 4. Interactive Route Map & Deviation Testing
On the dashboard center column:
1. Click **`🗺️ Open Interactive Map Simulator`**.
2. Select a preset route:
   - **Normal Route: Bus Stand to College** (Safe navigation).
   - **Deviated Route: High-Risk Area** (Simulates leaving route and tests alerts).
   - **Custom Route**: Click directly on the map to define waypoints.
3. **Simulator Hotkeys**:
   - `Space`: Start / Pause simulation playback.
   - `D`: Trigger an instant $\pm 250\text{ m}$ route deviation.
   - `S`: Boost speed multiplier ($1\times \rightarrow 2\times \rightarrow 4\times \rightarrow 8\times$).
   - `R`: Reset position back to route start.
   - `↑ ↓ ← →`: Manually nudge position step-by-step.

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
- **Sensors (Port 8080)**: Run Termux or any Sensor Streamer app broadcasting sensor JSON payloads (`accelerometer`, `gyroscope`).
- **GPS (Port 8082)**: Stream GPS location packets (`{"latitude": ..., "longitude": ...}`).
- **Calling & SMS**:
  - Phone calls initiate automatically via Android Intents (`CALL` intent, with fallback to `DIAL`).
  - SMS dispatches via local SIM (Termux API) or the MacroDroid webhook.

---

## 📦 Git Commands to Commit & Push Updates

To save all changes to your GitHub repository:
```powershell
git add .
git commit -m "Complete Women Safety System with setup guide, automated tests, and offline sync"
git push origin main
```

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
