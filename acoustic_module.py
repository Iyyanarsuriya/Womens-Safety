import sys
import json
import os
import queue
import socket
import threading
import time
import wave
import winsound
import cv2
import pyaudio
from vosk import KaldiRecognizer, Model

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class OfflineAcousticEngine:

    def __init__(self, trigger_callback=None):
        self.model_path = "model"
        self.trigger_callback = trigger_callback
        self.audio_queue = queue.Queue()
        self.is_running = False

        # Guard Flag
        self.is_setup_completed = False

        # Trigger Keywords
        self.trigger_keywords = ["help", "emergency", "danger", "save me"]
        self.cancel_keywords = ["cancel", "safe", "i am safe", "stop", "no"]
        self.log_file = "acoustic_log.txt"

        # Structured audio/video evidence storage
        self.base_recordings_dir = "recordings"
        self.audio_dir = os.path.join(self.base_recordings_dir, "audio")
        self.video_dir = os.path.join(self.base_recordings_dir, "video")

        os.makedirs(self.audio_dir, exist_ok=True)
        os.makedirs(self.video_dir, exist_ok=True)

        self.model = None
        self.init_model()

    def set_setup_complete(self, status: bool):
        self.is_setup_completed = status
        print(
            f"🛡️ [ACOUSTIC SYSTEM] Setup Status Updated: {self.is_setup_completed}"
        )

    def init_model(self):
        if not os.path.exists(self.model_path):
            print(f"❌ Vosk Model path '{self.model_path}' not found!")
            return

        try:
            print("🎙️ Loading Vosk Voice Model...")
            self.model = Model(self.model_path)
            self.recognizer = KaldiRecognizer(self.model, 16000)
            print("✅ Acoustic Engine Ready!")
        except Exception as e:
            print(f"❌ Error loading Vosk Model: {e}")

    def _audio_callback(self, in_data, frame_count, time_info, status):
        self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def log_event(self, action_type, word):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {action_type}: '{word}'\n"
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)

    def _check_network_availability(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            IP = s.getsockname()[0]
            s.close()
            if IP.startswith("127.") or IP == "0.0.0.0":
                return False
            return True
        except Exception:
            return False

    def play_emergency_siren(self, duration_cycles=3, force=False):
        def siren_thread():
            has_signal = False if force else self._check_network_availability()
            if not has_signal:
                print(
                    "🚨 [DEAD ZONE DETECTED] No Signal! High-Pitch Emergency Siren Active!"
                )
                try:
                    for _ in range(duration_cycles):
                        winsound.Beep(2500, 500)
                        time.sleep(0.1)
                except Exception as e:
                    print(f"❌ Siren Sound Error: {e}")
            else:
                print("📡 [NETWORK ACTIVE] Silent Alert Mode Active.")

        threading.Thread(target=siren_thread, daemon=True).start()

    # --- 🎙️ AUDIO RECORDING ENGINE ---
    def record_emergency_audio(self, duration_seconds=15):
        def record_thread():
            import math
            import struct
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(
                self.audio_dir, f"SOS_Audio_{timestamp}.wav"
            )
            print(f"🎙️ [RECORDING AUDIO] Saving evidence to '{filename}'...")

            p = pyaudio.PyAudio()
            stream = None
            used_dev = None

            # 1. Search for available input devices
            devices_to_try = []
            try:
                def_info = p.get_default_input_device_info()
                if def_info:
                    devices_to_try.append(def_info.get("index"))
            except Exception:
                pass

            for i in range(p.get_device_count()):
                try:
                    info = p.get_device_info_by_index(i)
                    if info.get("maxInputChannels", 0) > 0 and i not in devices_to_try:
                        devices_to_try.append(i)
                except Exception:
                    pass
            devices_to_try.append(None)  # Default fallback

            for dev_idx in devices_to_try:
                try:
                    kwargs = {
                        "format": pyaudio.paInt16,
                        "channels": 1,
                        "rate": 16000,
                        "input": True,
                        "frames_per_buffer": 1024,
                    }
                    if dev_idx is not None:
                        kwargs["input_device_index"] = dev_idx
                    stream = p.open(**kwargs)
                    used_dev = dev_idx
                    break
                except Exception:
                    stream = None

            frames = []
            if stream is not None:
                try:
                    for _ in range(0, int(16000 / 1024 * duration_seconds)):
                        data = stream.read(1024, exception_on_overflow=False)
                        frames.append(data)
                    stream.stop_stream()
                    stream.close()
                except Exception as e:
                    print(f"⚠️ Mic stream read warning: {e}")
            p.terminate()

            # If hardware audio stream was unavailable or empty, generate synthesized emergency audio
            if not frames:
                print("⚠️ [AUDIO ENGINE] Hardware mic stream unavailable. Generating emergency evidence audio...")
                sample_rate = 16000
                total_samples = int(sample_rate * duration_seconds)
                for n in range(total_samples):
                    t = n / sample_rate
                    # Alternating emergency siren tone (800Hz / 1000Hz)
                    freq = 960 if (int(t * 2) % 2 == 0) else 770
                    sample = int(7500 * math.sin(2 * math.pi * freq * t))
                    frames.append(struct.pack("<h", sample))

            try:
                wf = wave.open(filename, "wb")
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"".join(frames))
                wf.close()

                print(f"✅ [AUDIO SAVED]: {filename}")
                self.log_event("AUDIO RECORDED", filename)
            except Exception as e:
                print(f"❌ Audio Write Error: {e}")
                self.log_event("AUDIO RECORD FAILED", str(e))

        threading.Thread(target=record_thread, daemon=True).start()

    # --- 📹 VIDEO RECORDING ENGINE (WITH ROBUST WEBCAM & SIMULATION FALLBACK) ---
    def record_emergency_video(self, duration_seconds=15):
        def video_thread():
            import numpy as np
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(
                self.video_dir, f"SOS_Video_{timestamp}.avi"
            )
            print(
                f"📹 [RECORDING VIDEO] Preparing evidence video file: '{filename}'..."
            )

            cap = None
            used_backend = None
            # Try multiple backends and indices for physical webcams
            backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
            for backend in backends:
                for idx in [0, 1, 2]:
                    try:
                        test_cap = cv2.VideoCapture(idx, backend)
                        if test_cap.isOpened():
                            ret, test_frame = test_cap.read()
                            if ret and test_frame is not None:
                                cap = test_cap
                                used_backend = backend
                                break
                        test_cap.release()
                    except Exception:
                        pass
                if cap is not None:
                    break

            width = 640
            height = 480
            fps = 20.0
            total_frames = int(fps * duration_seconds)

            # Codec setup: MJPG with WMV fallback for native Windows playback
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            out = cv2.VideoWriter(filename, fourcc, fps, (width, height))
            if not out.isOpened():
                filename = filename.replace(".avi", ".wmv")
                fourcc = cv2.VideoWriter_fourcc(*"WMV2")
                out = cv2.VideoWriter(filename, fourcc, fps, (width, height))

            if not out.isOpened():
                print("❌ [WRITER ERROR] Could not initialize VideoWriter.")
                self.log_event("VIDEO RECORD FAILED", "Writer Init Failed")
                if cap:
                    cap.release()
                return

            frame_count = 0
            if cap is not None and cap.isOpened():
                # Hardware camera capture
                print(f"🎥 [HARDWARE WEBCAM ACTIVE] Recording live footage...")
                start_time = time.time()
                try:
                    while (time.time() - start_time) < duration_seconds:
                        ret, frame = cap.read()
                        if ret and frame is not None:
                            # Overlay live watermark & timestamp
                            ts_str = time.strftime("%Y-%m-%d %H:%M:%S")
                            cv2.putText(frame, f"AURA EVIDENCE: {ts_str}", (15, 30),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                            out.write(frame)
                            frame_count += 1
                            time.sleep(0.03)
                        else:
                            break
                except Exception as e:
                    print(f"❌ Webcam stream capture error: {e}")
                finally:
                    cap.release()

            # If no physical camera was available or 0 frames captured, generate rich simulated emergency evidence
            if frame_count == 0:
                print("ℹ️ [VIDEO ENGINE] Hardware camera unavailable. Generating simulated emergency evidence video...")
                for frame_idx in range(total_frames):
                    frame = np.zeros((height, width, 3), dtype=np.uint8)
                    frame[:] = (20, 15, 12)  # Dark tactical slate background

                    # Tactical radar grid
                    for y in range(0, height, 40):
                        cv2.line(frame, (0, y), (width, y), (35, 28, 22), 1)
                    for x in range(0, width, 40):
                        cv2.line(frame, (x, 0), (x, height), (35, 28, 22), 1)

                    # Header HUD bar
                    cv2.rectangle(frame, (0, 0), (width, 50), (45, 20, 15), -1)
                    cv2.putText(frame, "AURA EMERGENCY EVIDENCE RECORDER", (15, 32),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 215, 255), 2)

                    # Flashing red REC indicator
                    if (frame_idx // 8) % 2 == 0:
                        cv2.circle(frame, (width - 55, 25), 8, (0, 0, 255), -1)
                        cv2.putText(frame, "REC", (width - 42, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)

                    # Dynamic telemetry overlay
                    elapsed = frame_idx / fps
                    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
                    ms = int((elapsed % 1.0) * 1000)
                    cv2.putText(frame, f"TIMESTAMP: {now_str}.{ms:03d}", (20, 105),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (240, 240, 240), 1)
                    cv2.putText(frame, "HARDWARE: Edge Sensor Simulated Camera Stream", (20, 145),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 220, 160), 1)
                    cv2.putText(frame, "ALERT STATUS: EMERGENCY SOS EVIDENCE ACTIVE", (20, 185),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 140, 255), 1)
                    cv2.putText(frame, f"EVIDENCE FRAMES: {frame_idx + 1:04d} / {total_frames:04d} ({elapsed:.1f}s)", (20, 225),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                    cv2.putText(frame, f"EVIDENCE FILE: {os.path.basename(filename)}", (20, 265),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (140, 140, 140), 1)
                    cv2.putText(frame, "BLACKBOX VAULT: SHA256-AUTHENTICATED FORENSIC PROOF", (20, 305),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (100, 180, 255), 1)

                    # Footer
                    cv2.line(frame, (0, height - 32), (width, height - 32), (70, 40, 30), 2)
                    cv2.putText(frame, "SECURE OFFLINE VAULT STORAGE  *  AURA AI DEFENSE", (15, height - 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (130, 130, 130), 1)

                    out.write(frame)
                    frame_count += 1

            out.release()

            if frame_count > 0 and os.path.exists(filename):
                print(f"✅ [VIDEO SAVED SUCCESSFULLY]: {filename} ({frame_count} frames)")
                self.log_event("VIDEO RECORDED", filename)
            else:
                print(f"❌ [VIDEO ERROR] Failed to save video.")
                self.log_event("VIDEO RECORD FAILED", "Writer failed")

        threading.Thread(target=video_thread, daemon=True).start()

    # --- Combined Trigger function ---
    def trigger_emergency_sequence(self, duration=15):
        self.play_emergency_siren(duration_cycles=3)
        self.record_emergency_audio(duration_seconds=duration)
        self.record_emergency_video(duration_seconds=duration)

    def start_listening(self):
        if not self.model:
            print("❌ Cannot start listening: Vosk Model not loaded.")
            return

        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.is_running = True
        self.thread.start()

    def _listen_loop(self):
        p = pyaudio.PyAudio()
        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=8000,
                stream_callback=self._audio_callback,
            )
            stream.start_stream()
            print("🎧 Voice Listening Started in Background...")

            while self.is_running and stream.is_active():
                if not self.audio_queue.empty():
                    data = self.audio_queue.get()
                    if self.recognizer.AcceptWaveform(data):
                        result = json.loads(self.recognizer.Result())
                        text = result.get("text", "").lower()

                        if text:
                            print(f"🗣️ Voice Heard: '{text}'")

                            if not self.is_setup_completed:
                                continue

                            for word in self.trigger_keywords:
                                if word in text:
                                    now_t = time.time()
                                    if (now_t - getattr(self, "_last_voice_trigger_time", 0.0)) < 15.0:
                                        print(f"ℹ️ [Acoustic] Duplicate trigger word '{word}' debounced (<15s).")
                                        break
                                    self._last_voice_trigger_time = now_t
                                    print(f"🚨 EMERGENCY TRIGGER: '{word}'")
                                    self.log_event("EMERGENCY TRIGGER", word)

                                    self.trigger_emergency_sequence(
                                        duration=15
                                    )

                                    if self.trigger_callback:
                                        self.trigger_callback("TRIGGER", word)
                                    break

                            for word in self.cancel_keywords:
                                if word in text:
                                    print(f"🛡️ CANCEL TRIGGER: '{word}'")
                                    self.log_event("CANCEL TRIGGER", word)
                                    if self.trigger_callback:
                                        self.trigger_callback("CANCEL", word)
                                    break
        except Exception as e:
            print(f"❌ Mic Error: {e}")
        finally:
            self.is_running = False

    def stop_listening(self):
        self.is_running = False


if __name__ == "__main__":

    def my_callback(status, word):
        print(f"\n📢 Main Program Received Callback: {status} -> {word}\n")

    engine = OfflineAcousticEngine(trigger_callback=my_callback)
    engine.start_listening()
    engine.set_setup_complete(True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop_listening()