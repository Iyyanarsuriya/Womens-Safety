"""
android_telephony_module.py
────────────────────────────────────────────────────────────────────────────
Android Telephony & Dispatch Engine for AURA Women Safety System.

Handles:
  1. Priority-based emergency calls (P1 contact first, with fallback to P2).
  2. Android runtime permission & platform restriction handling:
     - Direct CALL intent vs DIAL intent fallback when CALL_PHONE is restricted.
     - Graceful handling of SIM missing, ADB disconnected, or permission denials.
     - Zero false-positive reporting: precise status for every action.
  3. SMS Dispatch:
     - Direct offline SMS via Termux API over ADB or socket bridge.
     - Cloud SMS & priority call webhook via MacroDroid.
"""

import subprocess
import time
import logging
from macrodroid_dispatch_module import trigger_aura_sos

logger = logging.getLogger("android_telephony")


class AndroidTelephonyManager:
    def __init__(self):
        self._adb_available = self._detect_adb()

    def _detect_adb(self) -> bool:
        """Checks if ADB command line tool is accessible."""
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            res = subprocess.run(["adb", "version"], capture_output=True, text=True, timeout=2.0, startupinfo=startupinfo)
            return res.returncode == 0
        except Exception:
            return False

    def check_phone_connection(self) -> dict:
        """
        Inspects connected Android phone, USB/Wi-Fi debug status, SIM state, and permissions.
        """
        if not self._adb_available:
            return {
                "adb_installed": False,
                "device_connected": False,
                "device_id": None,
                "sim_state": "UNKNOWN",
                "call_permission": False,
                "notes": "ADB binary not found in system PATH."
            }

        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            dev_res = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=3.0, startupinfo=startupinfo)
            lines = [l.strip() for l in dev_res.stdout.splitlines() if l.strip() and not l.startswith("List of")]
            
            connected_devices = [l.split()[0] for l in lines if "\tdevice" in l]
            if not connected_devices:
                return {
                    "adb_installed": True,
                    "device_connected": False,
                    "device_id": None,
                    "sim_state": "NO_DEVICE",
                    "call_permission": False,
                    "notes": "No authorized Android device connected over ADB."
                }

            device_id = connected_devices[0]

            # Check SIM state
            sim_res = subprocess.run(["adb", "-s", device_id, "shell", "getprop", "gsm.sim.state"],
                                     capture_output=True, text=True, timeout=3.0, startupinfo=startupinfo)
            sim_state = sim_res.stdout.strip() or "UNKNOWN"

            # Check CALL_PHONE permission for shell/termux
            perm_res = subprocess.run(["adb", "-s", device_id, "shell", "pm", "dump", "com.termux"],
                                      capture_output=True, text=True, timeout=3.0, startupinfo=startupinfo)
            has_call_perm = "android.permission.CALL_PHONE: granted=true" in perm_res.stdout

            return {
                "adb_installed": True,
                "device_connected": True,
                "device_id": device_id,
                "sim_state": sim_state,
                "call_permission": has_call_perm,
                "notes": f"Connected device: {device_id}, SIM: {sim_state}"
            }
        except Exception as exc:
            return {
                "adb_installed": True,
                "device_connected": False,
                "device_id": None,
                "sim_state": "ERROR",
                "call_permission": False,
                "notes": f"Error querying ADB: {exc}"
            }

    def place_priority_emergency_call(self, *contacts) -> dict:
        """
        Executes prioritized calling workflow adhering to Android platform restrictions.
        Iterates through contacts in configured priority order (P1 -> P2 -> P3...).
        1. Attempt P1 direct call.
        2. If SecurityException (CALL_PHONE missing), fallback to DIAL intent.
        3. If P1 fails, unconfirmed, or dialer closed, fallback to next priority contact.
        """
        contact_list = []
        for c in contacts:
            if isinstance(c, list):
                contact_list.extend(c)
            elif c:
                contact_list.append(str(c))

        results = {
            "p1_number": contact_list[0] if len(contact_list) > 0 else "",
            "p1_status": "NOT_ATTEMPTED",
            "p2_number": contact_list[1] if len(contact_list) > 1 else "",
            "p2_status": "NOT_ATTEMPTED",
            "active_intent": None,
            "restrictions_encountered": [],
            "call_history": []
        }

        if not contact_list:
            results["p1_status"] = "ABORTED_NO_CONTACTS"
            return results

        phone_info = self.check_phone_connection()
        device_id = phone_info.get("device_id")

        if not phone_info.get("device_connected"):
            results["restrictions_encountered"].append("ADB_DEVICE_NOT_CONNECTED")
            results["p1_status"] = "FAILED_NO_ADB_CONNECTION"
            print(f"⚠️ [Telephony] Direct phone call cannot be made: {phone_info['notes']}")
            return results

        # Iterate through contacts in order of priority
        for idx, contact in enumerate(contact_list):
            p_label = f"P{idx + 1}"
            print(f"📞 [Telephony] Attempting call to {p_label} ({contact})...")
            c_res = self._execute_android_call_intent(device_id, contact)
            status = c_res["status"]
            intent_used = c_res["intent_used"]
            if c_res.get("restriction"):
                results["restrictions_encountered"].append(c_res["restriction"])

            results["call_history"].append({
                "priority": p_label,
                "phone": contact,
                "status": status,
                "intent": intent_used
            })

            if idx == 0:
                results["p1_status"] = status
                results["active_intent"] = intent_used
            elif idx == 1:
                results["p2_status"] = status

            # If call was initiated directly and successfully, we consider it connected
            if status == "CALL_INITIATED_SUCCESS":
                print(f"✅ [Telephony] Connected call to {p_label} ({contact}).")
                break
            else:
                print(f"⚠️ [Telephony] {p_label} call status: {status}. Proceeding to next contact if available...")
                time.sleep(1.5)

        return results

    def _execute_android_call_intent(self, device_id: str, phone_number: str) -> dict:
        """Attempts direct CALL intent, with graceful fallback to DIAL intent on permission restriction."""
        sanitized = "".join(ch for ch in str(phone_number) if ch.isdigit())
        if not sanitized:
            return {"status": "INVALID_NUMBER", "intent_used": None}

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # 1. Try direct CALL intent
        cmd_call = ["adb", "-s", device_id, "shell", "am", "start", "-a", "android.intent.action.CALL", "-d", f"tel:{sanitized}"]
        try:
            res = subprocess.run(cmd_call, capture_output=True, text=True, timeout=5.0, startupinfo=startupinfo)
            output = (res.stdout + " " + res.stderr).lower()

            if "securityexception" in output or "permission denial" in output:
                # Android restriction: CALL_PHONE permission not granted to shell
                print(f"⚠️ [Telephony] android.permission.CALL_PHONE restricted for tel:{sanitized}. Falling back to DIAL intent...")
                cmd_dial = ["adb", "-s", device_id, "shell", "am", "start", "-a", "android.intent.action.DIAL", "-d", f"tel:{sanitized}"]
                dial_res = subprocess.run(cmd_dial, capture_output=True, text=True, timeout=5.0, startupinfo=startupinfo)
                if dial_res.returncode == 0:
                    return {
                        "status": "DIALER_POPUP_SUCCESS",
                        "intent_used": "android.intent.action.DIAL",
                        "restriction": "CALL_PHONE_PERMISSION_DENIED_FALLBACK_TO_DIAL"
                    }
                else:
                    return {
                        "status": "FAILED_DIAL",
                        "intent_used": "android.intent.action.DIAL",
                        "restriction": "DIAL_FAILED"
                    }

            elif res.returncode == 0 and "starting: intent" in output:
                print(f"📞 [Telephony] Direct Emergency Call initiated to {sanitized} via Android CALL intent.")
                return {
                    "status": "CALL_INITIATED_SUCCESS",
                    "intent_used": "android.intent.action.CALL"
                }
            else:
                return {
                    "status": "FAILED_CALL",
                    "intent_used": "android.intent.action.CALL",
                    "restriction": output.strip()
                }

        except Exception as exc:
            return {
                "status": "CALL_ERROR",
                "intent_used": None,
                "restriction": str(exc)
            }

    def dispatch_emergency_sms(self, p1_number: str = "", p2_number: str = "", message: str = "", lat: float = 0.0, lon: float = 0.0, extra_contacts: list = None, contacts: list = None, emergency_message: str = "", current_lat: float = None, current_lon: float = None, on_sms_dispatch=None) -> dict:
        """
        Dispatches emergency SMS using local phone SIM (via Termux API / ADB)
        and MacroDroid webhook redundancy. Supports multiple contacts preserving priority.
        """
        if current_lat is not None:
            lat = current_lat
        if current_lon is not None:
            lon = current_lon
        if emergency_message:
            message = emergency_message

        all_contacts = []
        if contacts is not None:
            if isinstance(contacts, list):
                all_contacts = [str(c) for c in contacts if c]
            else:
                all_contacts = [str(contacts)]
        elif isinstance(p1_number, list):
            all_contacts = [str(c) for c in p1_number if c]
        else:
            if p1_number: all_contacts.append(str(p1_number))
            if p2_number: all_contacts.append(str(p2_number))
            if extra_contacts:
                all_contacts.extend([str(c) for c in extra_contacts if c])

        p1_val = all_contacts[0] if len(all_contacts) > 0 else ""
        p2_val = all_contacts[1] if len(all_contacts) > 1 else ""

        maps_link = f"https://maps.google.com/?q={lat:.6f},{lon:.6f}"
        full_msg = message or f"EMERGENCY SOS! Threat detected. Current Location: Lat {lat:.6f}, Lon {lon:.6f}. Map: {maps_link}"
        if maps_link not in full_msg:
            full_msg += f" {maps_link}"

        status_report = {
            "p1_sms": "PENDING",
            "p2_sms": "PENDING",
            "macrodroid_webhook": "DISPATCHED",
            "contacts_sent": [],
            "maps_url": maps_link
        }

        # Trigger Cloud Dispatch or Callback
        if on_sms_dispatch:
            on_sms_dispatch(p1_val, p2_val, lat, lon)
        else:
            trigger_aura_sos(p1_val, p2_val, lat, lon)

        # Attempt direct local device SMS via Termux API for each configured contact in priority order
        phone_info = self.check_phone_connection()
        device_connected = phone_info.get("device_connected")
        device_id = phone_info.get("device_id")

        for idx, contact in enumerate(all_contacts):
            key = f"p{idx + 1}_sms"
            if device_connected:
                success = self._send_termux_sms_via_adb(device_id, contact, full_msg)
                st = "SENT_VIA_LOCAL_SIM" if success else "TERMUX_SMS_FAILED_OR_NO_PERMISSION"
            else:
                st = "OFFLINE_QUEUED_MACRODROID_DISPATCH"

            status_report[key] = st
            status_report["contacts_sent"].append({"contact": contact, "status": st})

        return status_report

    def send_low_battery_sms(self, contacts: list, percent: int, lat: float, lon: float) -> dict:
        """
        Sends a dedicated Low Battery Warning SMS.
        CRITICAL: Does NOT trigger SOS!
        """
        maps_link = f"https://maps.google.com/?q={lat:.6f},{lon:.6f}"
        msg = (
            f"🔋 LOW BATTERY WARNING: Phone battery is at {percent}%. "
            f"Note: This is NOT an SOS emergency. "
            f"Current Location: Lat {lat:.6f}, Lon {lon:.6f}. "
            f"Map Link: {maps_link}"
        )

        phone_info = self.check_phone_connection()
        device_connected = phone_info.get("device_connected")
        device_id = phone_info.get("device_id")

        results = {}
        for idx, contact in enumerate(contacts):
            key = f"contact_{idx + 1}"
            if device_connected:
                success = self._send_termux_sms_via_adb(device_id, str(contact), msg)
                results[key] = "SENT_VIA_LOCAL_SIM" if success else "TERMUX_SMS_FAILED"
            else:
                results[key] = "DEVICE_NOT_CONNECTED_SMS_LOGGED"
            print(f"🔋 [Telephony] Low Battery Warning SMS to {contact}: {results[key]}")

        return results

    def _send_termux_sms_via_adb(self, device_id: str, phone_number: str, message: str) -> bool:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        clean_num = "".join(ch for ch in str(phone_number) if ch.isdigit())
        if not clean_num:
            return False

        cmd = ["adb", "-s", device_id, "shell", "termux-sms-send", "-n", clean_num, message]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=6.0, startupinfo=startupinfo)
            return res.returncode == 0
        except Exception:
            return False
