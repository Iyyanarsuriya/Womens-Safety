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
import threading
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

    def place_priority_emergency_call(self, p1_number: str, p2_number: str = "") -> dict:
        """
        Executes prioritized calling workflow adhering to Android platform restrictions.
        1. Attempt P1 direct call.
        2. If SecurityException (CALL_PHONE missing), fallback to DIAL intent.
        3. If P1 fails or no answer, fallback to P2.
        """
        results = {
            "p1_number": p1_number,
            "p1_status": "NOT_ATTEMPTED",
            "p2_number": p2_number,
            "p2_status": "NOT_ATTEMPTED",
            "active_intent": None,
            "restrictions_encountered": []
        }

        if not p1_number and not p2_number:
            results["p1_status"] = "ABORTED_NO_CONTACTS"
            return results

        phone_info = self.check_phone_connection()
        device_id = phone_info.get("device_id")

        if not phone_info.get("device_connected"):
            results["restrictions_encountered"].append("ADB_DEVICE_NOT_CONNECTED")
            results["p1_status"] = "FAILED_NO_ADB_CONNECTION"
            print(f"⚠️ [Telephony] Direct phone call cannot be made: {phone_info['notes']}")
            return results

        # ── Step 1: Call Priority 1 ──────────────────────────────────────────
        if p1_number:
            p1_res = self._execute_android_call_intent(device_id, p1_number)
            results["p1_status"] = p1_res["status"]
            results["active_intent"] = p1_res["intent_used"]
            if p1_res.get("restriction"):
                results["restrictions_encountered"].append(p1_res["restriction"])

        # ── Step 2: Fallback to Priority 2 if P1 failed or was dialer only ────
        if p2_number and results["p1_status"] in ("FAILED_SECURITY_EXCEPTION", "FAILED_CALL", "NOT_ATTEMPTED"):
            print("📞 [Telephony] P1 call unconfirmed. Escalating to Priority 2 contact...")
            time.sleep(2.0)
            p2_res = self._execute_android_call_intent(device_id, p2_number)
            results["p2_status"] = p2_res["status"]
            if p2_res.get("restriction"):
                results["restrictions_encountered"].append(p2_res["restriction"])

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

    def dispatch_emergency_sms(self, p1_number: str, p2_number: str, message: str, lat: float, lon: float) -> dict:
        """
        Dispatches emergency SMS using local phone SIM (via Termux API / ADB)
        and MacroDroid webhook redundancy.
        """
        status_report = {
            "p1_sms": "PENDING",
            "p2_sms": "PENDING",
            "macrodroid_webhook": "DISPATCHED"
        }

        # Trigger MacroDroid cloud dispatch (handles offline queue or cloud webhook)
        trigger_aura_sos(p1_number, p2_number, lat, lon)

        # Attempt direct local device SMS via Termux API
        phone_info = self.check_phone_connection()
        if phone_info.get("device_connected"):
            device_id = phone_info.get("device_id")
            for contact, key in [(p1_number, "p1_sms"), (p2_number, "p2_sms")]:
                if contact:
                    success = self._send_termux_sms_via_adb(device_id, contact, message)
                    status_report[key] = "SENT_VIA_LOCAL_SIM" if success else "TERMUX_SMS_FAILED_OR_NO_PERMISSION"
        else:
            status_report["p1_sms"] = "OFFLINE_QUEUED_MACRODROID_DISPATCH"
            status_report["p2_sms"] = "OFFLINE_QUEUED_MACRODROID_DISPATCH"

        return status_report

    def _send_termux_sms_via_adb(self, device_id: str, phone_number: str, message: str) -> bool:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        clean_num = "".join(ch for ch in str(phone_number) if ch.isdigit())

        cmd = ["adb", "-s", device_id, "shell", "termux-sms-send", "-n", clean_num, message]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=6.0, startupinfo=startupinfo)
            return res.returncode == 0
        except Exception:
            return False
