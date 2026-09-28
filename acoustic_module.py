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
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(
                self.audio_dir, f"SOS_Audio_{timestamp}.wav"
            )
            print(f"🎙️ [RECORDING AUDIO] Saving evidence to '{filename}'...")

            p = pyaudio.PyAudio()
            try:
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    frames_per_buffer=1024,
                )

                frames = []
                for _ in range(0, int(16000 / 1024 * duration_seconds)):
                    data = stream.read(1024, exception_on_overflow=False)
                    frames.append(data)

                stream.stop_stream()
                stream.close()
                p.terminate()

                wf = wave.open(filename, "wb")
                wf.setnchannels(1)
                wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
                wf.setframerate(16000)
                wf.writeframes(b"".join(frames))
                wf.close()

                print(f"✅ [AUDIO SAVED]: {filename}")
                self.log_event("AUDIO RECORDED", filename)

            except Exception as e:
                print(f"❌ Audio Recording Error: {e}")
                self.log_event("AUDIO RECORD FAILED", str(e))

        threading.Thread(target=record_thread, daemon=True).start()

    # --- 📹 VIDEO RECORDING ENGINE (WINDOWS MEDIA PLAYER FIX) ---
    def record_emergency_video(self, duration_seconds=15):
        def video_thread():
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            # 🔧 FIX: MJPG Container + .avi format is 100% supported natively on Windows
            filename = os.path.join(
                self.video_dir, f"SOS_Video_{timestamp}.avi"
            )
            print(
                f"📹 [RECORDING VIDEO] Opening webcam for file: '{filename}'..."
            )

            cap = None
            used_index = None

            # Try CAP_DSHOW for fast hardware initialization on Windows
            for idx in [0, 1]:
                test_cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                if test_cap.isOpened():
                    cap = test_cap
                    used_index = idx
                    break
                test_cap.release()

            if cap is None:
                print("❌ [CAMERA ERROR] No camera detected on Index 0 or 1.")
                self.log_event("VIDEO RECORD FAILED", "No webcam available")
                return

            # Dynamically fetch native camera resolution to prevent codec mismatch
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
            fps = 20.0

            # 🔧 Motion JPEG (MJPG) codec ensures native playback on Windows Media Player
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            out = cv2.VideoWriter(filename, fourcc, fps, (width, height))

            if not out.isOpened():
                print(
                    "❌ [WRITER ERROR] MJPG Failed. Trying WMV2 codec fallback..."
                )
                filename = filename.replace(".avi", ".wmv")
                fourcc = cv2.VideoWriter_fourcc(*"WMV2")
                out = cv2.VideoWriter(filename, fourcc, fps, (width, height))

            if not out.isOpened():
                print("❌ [WRITER ERROR] Could not initialize VideoWriter.")
                self.log_event("VIDEO RECORD FAILED", "Writer Init Failed")
                cap.release()
                return

            frame_count = 0
            start_time = time.time()

            try:
                while (time.time() - start_time) < duration_seconds:
                    ret, frame = cap.read()
                    if ret:
                        out.write(frame)
                        frame_count += 1
                        time.sleep(0.03)  # Smooth capture timing sync
                    else:
                        break
            except Exception as e:
                print(f"❌ Video Capture Error: {e}")
                self.log_event("VIDEO RECORD FAILED", str(e))
            finally:
                cap.release()
                out.release()  # Flushes buffer and finalizing video file header correctly

            if frame_count > 0 and os.path.exists(filename):
                print(f"✅ [VIDEO SAVED SUCCESSFULLY]: {filename}")
                self.log_event("VIDEO RECORDED", filename)
            else:
                print(f"❌ [VIDEO ERROR] 0 frames recorded.")
                self.log_event("VIDEO RECORD FAILED", "0 frames captured")

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