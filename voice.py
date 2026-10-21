"""
Voice input/output for NOVA.

If listening keeps timing out, your default microphone (device index 0,
usually "Microsoft Sound Mapper - Input") may be a virtual routing device
that does not actually capture audio. Set MIC_INDEX below to a real
hardware device instead.

Find your device list and indexes with:
    python -c "import speech_recognition as sr; [print(i, n) for i, n in enumerate(sr.Microphone.list_microphone_names())]"

Then set the index of your real microphone here, e.g.:
    MIC_INDEX = 7

NOVA now listens continuously in the background (like Siri/JARVIS) instead
of requiring you to press LISTEN every time. See start_background_listening().
"""

import threading

# None = auto (device index 0). Set to an int to force a specific device.
MIC_INDEX = 2

# Seconds to wait for you to start speaking before giving up.
# None = wait forever (never times out before you start talking).
LISTEN_TIMEOUT = None

# Max seconds of speech to capture once you start talking.
# None = no limit; it keeps recording until you stop talking.
PHRASE_TIME_LIMIT = None

# How many seconds of silence counts as "you're done talking".
# Higher = more tolerant of natural pauses mid-sentence before it cuts you off.
PAUSE_THRESHOLD = 1.6

# Ignore phrases shorter than this many characters once transcribed
# (filters out coughs/background noise that Google STT turns into "uh" etc).
MIN_PHRASE_LENGTH = 2


class VoiceEngine:
    def __init__(self):
        self.available = True
        # Set for as long as NOVA is talking, so the always-on mic ignores
        # NOVA's own voice instead of hearing itself and looping.
        self._speaking = threading.Event()
        # Set/cleared manually via mute()/unmute() (e.g. the LISTEN button).
        self._manual_mute = threading.Event()
        self._stop_listening = None

    # ------------------------------------------------------------------
    # Speaking
    # ------------------------------------------------------------------
    def speak(self, text, on_start=None, on_done=None):
        """Speak text out loud asynchronously. Mic is auto-muted meanwhile
        so NOVA doesn't transcribe its own voice."""
        if not text or not text.strip():
            return

        def run():
            self._speaking.set()
            if on_start:
                try:
                    on_start()
                except Exception:
                    pass
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", 175)
                engine.setProperty("volume", 0.85)
                engine.say(text)
                engine.runAndWait()
            except Exception:
                pass
            finally:
                self._speaking.clear()
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------
    # Manual mute control (used by the LISTEN button as an override)
    # ------------------------------------------------------------------
    def mute(self):
        self._manual_mute.set()

    def unmute(self):
        self._manual_mute.clear()

    def is_muted(self):
        return self._manual_mute.is_set()

    # ------------------------------------------------------------------
    # One-shot listen (kept for compatibility / manual re-trigger)
    # ------------------------------------------------------------------
    def listen(self):
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            recognizer.energy_threshold = 300
            recognizer.dynamic_energy_threshold = True
            recognizer.pause_threshold = PAUSE_THRESHOLD

            with sr.Microphone(device_index=MIC_INDEX) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.6)
                print(f"[NOVA voice] ambient energy threshold: {recognizer.energy_threshold:.0f}")
                audio = recognizer.listen(
                    source, timeout=LISTEN_TIMEOUT, phrase_time_limit=PHRASE_TIME_LIMIT
                )
            return recognizer.recognize_google(audio)
        except Exception as e:
            return f"[Voice input unavailable: {e}]"

    # ------------------------------------------------------------------
    # Always-on background listening
    # ------------------------------------------------------------------
    def start_background_listening(self, on_heard, on_error=None):
        """
        Starts a persistent background thread (via SpeechRecognition's
        listen_in_background) that keeps the mic open all the time NOVA is
        running. Every time you finish speaking a phrase, on_heard(text) is
        called automatically - no button press needed.

        While NOVA itself is talking, or while manually muted, incoming
        audio is discarded so it never hears/transcribes itself.

        Returns a stop() function you can call to shut listening down.
        """
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = PAUSE_THRESHOLD

        mic = sr.Microphone(device_index=MIC_INDEX)
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.6)

        def process(rec, audio):
            if self._speaking.is_set() or self._manual_mute.is_set():
                return
            try:
                text = rec.recognize_google(audio)
            except sr.UnknownValueError:
                return
            except Exception as e:
                if on_error:
                    on_error(str(e))
                return
            if text and len(text.strip()) >= MIN_PHRASE_LENGTH:
                on_heard(text.strip())

        self._stop_listening = recognizer.listen_in_background(
            mic, process, phrase_time_limit=PHRASE_TIME_LIMIT
        )
        return self._stop_listening

    def stop_background_listening(self):
        if self._stop_listening:
            self._stop_listening(wait_for_stop=False)
            self._stop_listening = None


def list_microphones():
    """Run this file directly to print every microphone and its index."""
    import speech_recognition as sr
    for i, name in enumerate(sr.Microphone.list_microphone_names()):
        print(f"{i:>3}  {name}")


if __name__ == "__main__":
    list_microphones()