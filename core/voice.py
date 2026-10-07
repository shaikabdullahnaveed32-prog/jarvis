"""JARVIS voice. Engines tried in order: ElevenLabs (if key set) -> Kokoro (offline neural) -> macOS `say`.
Arabic text is spoken with a macOS Arabic voice."""
import json
import os
import re
import subprocess
import tempfile
import threading
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "models", "kokoro-v1.0.onnx")
VOICES = os.path.join(ROOT, "models", "voices-v1.0.bin")
KOKORO_VOICE = os.environ.get("JARVIS_VOICE", "bm_george")          # calm British male
SPEED = float(os.environ.get("JARVIS_SPEED", "0.95"))
SAY_RATE = os.environ.get("JARVIS_RATE", "180")
ELEVEN_VOICE = os.environ.get("JARVIS_ELEVEN_VOICE", "JBFqnCBsd6RMkjVDRZzb")   # "George", British male
ARABIC = re.compile(r"[\u0600-\u06ff]")


def _eleven_key():
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        try:
            with open(os.path.join(ROOT, "eleven.key")) as f:
                key = f.read().strip()
        except OSError:
            pass
    return key


def speakable(text, lines=4, chars=400):
    t = re.sub(r"<[^>]*>", "", text)                                         # e-mail addresses
    t = re.sub(r"[*_`#>]", "", t)
    t = re.sub(r"(?:~|/Users)/\S+", lambda m: os.path.basename(m.group(0).rstrip(".,")) or "that folder", t)
    t = re.sub(r"https?://\S+", "the link", t)
    rows = [l.strip() for l in t.splitlines() if l.strip()]
    return re.sub(r"\s+", " ", " ".join(l if l[-1] in ".!?:" else l + "." for l in rows[:lines]))[:chars]


def sentences(text):
    """Split into natural phrases; merge tiny ones (neural voices sound better on longer phrases)."""
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    out = []
    for s in parts:
        if out and len(out[-1]) < 40:
            out[-1] += " " + s
        else:
            out.append(s)
    return out


class Speaker:
    def __init__(self):
        self.gen = 0
        self.busy = False
        self.proc = None
        self.lock = threading.Lock()
        self.kokoro = None
        self.sf = None
        self.np = None
        self.say_voice = self._pick_say_voice()
        self.ar_voice = self._pick_ar_voice()
        self.kokoro_voice, self.speed = KOKORO_VOICE, SPEED
        self.eleven_key = _eleven_key()
        self.notes = []
        self.engines = []
        if self.eleven_key:
            self.engines.append("eleven")
        if os.path.exists(MODEL) and os.path.exists(VOICES):
            try:
                import numpy
                import soundfile
                from kokoro_onnx import Kokoro
                self.kokoro, self.sf, self.np = Kokoro(MODEL, VOICES), soundfile, numpy
                self.engines.append("kokoro")
            except Exception as e:
                self.notes.append(f"Kokoro OFF: {type(e).__name__}: {e}")
        else:
            self.notes.append("Kokoro OFF: model files missing (run python3 setup_voice.py)")
        self.engines.append("say")

    @staticmethod
    def _pick_say_voice():
        try:
            out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        names = [l.split("  ")[0].strip() for l in out.splitlines() if l.strip()]
        matches = [n for n in names if n.startswith("Daniel")]
        for tag in ("Premium", "Enhanced"):
            for n in matches:
                if tag in n:
                    return n
        return matches[0] if matches else None

    @staticmethod
    def _pick_ar_voice():
        try:
            out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        for line in out.splitlines():
            if re.search(r"\bar[_-]", line):
                return line.split("  ")[0].strip()
        return None

    def describe(self):
        label = {"eleven": "ElevenLabs", "kokoro": f"Kokoro neural ({self.kokoro_voice}, speed {self.speed:.2f})",
                 "say": f"macOS ({self.say_voice or 'default'}) - robotic"}
        ar = f"  |  Arabic: {self.ar_voice or 'no Arabic voice installed'}"
        return " -> ".join(label[e] for e in self.engines) + ar + ("  |  " + "; ".join(self.notes) if self.notes else "")

    def is_speaking(self):
        return self.busy

    def stop(self):
        with self.lock:
            self.gen += 1
            self.busy = False
        p = self.proc
        if p and p.poll() is None:
            p.terminate()

    def warm(self):
        """Pre-load the voice so the first sentence isn't slow."""
        if self.kokoro:
            try:
                self.kokoro.create("Ready.", voice=self.kokoro_voice, speed=self.speed, lang="en-gb")
            except Exception:
                pass

    def speak(self, text, long=False):
        t = speakable(text, 16, 1600) if long else speakable(text)
        self.stop()
        if not t:
            return
        with self.lock:
            self.gen += 1
            g = self.gen
            self.busy = True
        threading.Thread(target=self._run, args=(t, g), daemon=True).start()

    # ---- internals ----
    def _run(self, text, g):
        try:
            if self.ar_voice and ARABIC.search(text):
                self._say(text, g, self.ar_voice)
                return
            for engine in self.engines:
                try:
                    if engine == "eleven":
                        self._chunks([text], g, self._synth_eleven)
                    elif engine == "kokoro":
                        self._chunks(sentences(text), g, self._synth_kokoro)
                    else:
                        self._say(text, g)
                    return
                except Exception as e:
                    print(f"[voice] {engine} failed: {type(e).__name__}: {e}")
        finally:
            with self.lock:
                if self.gen == g:
                    self.busy = False

    def _synth_kokoro(self, sentence):
        np = self.np
        x, rate = self.kokoro.create(sentence, voice=self.kokoro_voice, speed=self.speed, lang="en-gb")
        x = np.asarray(x, dtype=np.float32).copy()
        fade = int(rate * 0.015)                                    # removes clicks/crackle at chunk edges
        if len(x) > 2 * fade:
            x[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            x[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        x *= 0.89 / (float(np.max(np.abs(x))) or 1.0)
        x = np.concatenate([np.zeros(int(rate * .02), np.float32), x, np.zeros(int(rate * .12), np.float32)])
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="jarvis_")
        os.close(fd)
        self.sf.write(path, x, rate, subtype="PCM_16")
        return path

    def _synth_eleven(self, text):
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}?output_format=mp3_44100_128",
            data=json.dumps({"text": text, "model_id": "eleven_turbo_v2_5",
                             "voice_settings": {"stability": 0.55, "similarity_boost": 0.75}}).encode(),
            headers={"xi-api-key": self.eleven_key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = r.read()
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="jarvis_")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return path

    def _chunks(self, chunks, g, synth):
        if not chunks:
            return
        path = synth(chunks[0])
        for i in range(len(chunks)):
            if self.gen != g:
                os.remove(path)
                return
            self.proc = subprocess.Popen(["afplay", path])
            nxt = synth(chunks[i + 1]) if i + 1 < len(chunks) else None   # prepare next while this plays
            self.proc.wait()
            os.remove(path)
            path = nxt

    def _say(self, text, g, voice=None):
        if self.gen != g:
            return
        voice = voice or self.say_voice
        self.proc = subprocess.Popen(["say"] + (["-v", voice] if voice else []) + ["-r", SAY_RATE, text])
        if self.gen != g:
            self.proc.terminate()
        self.proc.wait()