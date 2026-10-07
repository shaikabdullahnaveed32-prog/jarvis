"""JARVIS backend: runs in the terminal, serves the orb UI, speaks replies in a British voice."""
import datetime
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.brain import Brain
from core.voice import Speaker

HOST, PORT = "127.0.0.1", 8765
ROOT = os.path.dirname(os.path.abspath(__file__))
TOKEN = secrets.token_urlsafe(16)   # blocks other websites from sending commands to JARVIS
LOCK = threading.Lock()             # held while the brain works on a request
GUARD = threading.Lock()            # protects LAST
BUILD = "2026-10-06-f"
SLOW_AFTER = float(os.environ.get("JARVIS_SLOW_AFTER", "90"))   # seconds before "still working" kicks in
MAX_BODY = 1_000_000
brain = None
speaker = None
LAST = {"text": None, "t": 0.0, "reply": ""}

VOICE_NAMES = {n.split("_")[1]: n for n in
               ("bm_george", "bm_lewis", "bm_fable", "bm_daniel", "bf_emma", "bf_isabella", "bf_alice", "bf_lily")}
STOP_WORDS = {"stop", "quiet", "be quiet", "shut up", "stop talking", "silence", "enough"}


def voice_command(text):
    """Voice settings are changed here, not by the LLM (it cannot change them and would make things up)."""
    t = text.strip().lower().rstrip(".!?")
    if not brain.pending and t in STOP_WORDS:          # while a yes/no is pending, "stop" means cancel
        speaker.stop()
        return "Quiet, sir."
    if re.match(r"^(?:which|what)\b.*\bvoice\b|^voice status$", t):
        return "Voice: " + speaker.describe()
    m = re.match(r"^(?:change|switch|set|use)\s+(?:the\s+|your\s+|my\s+)?voice(?:\s+(?:to\s+)?(\w+))?$", t)
    if m:
        if m[1] in VOICE_NAMES:
            speaker.kokoro_voice = VOICE_NAMES[m[1]]
            note = "" if "kokoro" in speaker.engines else " (applies once the Kokoro voice is installed)"
            return f"Voice set to {m[1].title()}.{note}"
        return "Available voices: " + ", ".join(sorted(VOICE_NAMES)) + ". Say 'change voice to lewis'."
    if re.match(r"^(?:speak |talk )?slower$", t):
        speaker.speed = max(0.7, round(speaker.speed - 0.05, 2))
        return f"Speed {speaker.speed:.2f}."
    if re.match(r"^(?:speak |talk )?faster$", t):
        speaker.speed = min(1.3, round(speaker.speed + 0.05, 2))
        return f"Speed {speaker.speed:.2f}."
    return None


def to_speech(reply):
    """What to say aloud: no links, no markdown, no long lists. Returns (text, long)."""
    spoken = getattr(reply, "spoken", None)
    if spoken:
        return spoken, True
    t = str(reply)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\(yes\s*/\s*no\)", "", t, flags=re.I)
    t = re.sub(r"[*_`#>]+", "", t)
    t = re.sub(r"^\s*\d+\.\s*", "", t, flags=re.M)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(?:\.\s*){2,}", ". ", t).strip()
    if len(t) > 380:
        cut = t[:380]
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        t = (cut[:end + 1] if end > 80 else cut.rsplit(" ", 1)[0]) + " The rest is on screen, sir."
    return t, False


def run_brain(text):
    """Run the brain in a worker. If it takes too long, answer now and speak the result when it finishes."""
    box = {}

    def work():
        try:
            box["r"] = voice_command(text) or brain.ask(text)
        except Exception as e:
            box["r"] = f"Something failed, sir: {e}"
        finally:
            LOCK.release()

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(SLOW_AFTER)
    if not th.is_alive():
        return box["r"]

    def finish():
        th.join()
        late = box.get("r", "")
        print(f"JARVIS (finished late): {late}\n")
        say, is_long = to_speech(late)
        speaker.speak(say, long=is_long)

    threading.Thread(target=finish, daemon=True).start()
    return "That's taking a while, sir. I'll tell you as soon as it's done."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def do_GET(self):
        try:
            if not self._host_ok():
                return self._send(403, "{}")
            if self.path in ("/", "/index.html"):
                with open(os.path.join(ROOT, "ui", "index.html"), encoding="utf-8") as f:
                    html = f.read().replace("__TOKEN__", TOKEN)
                return self._send(200, html, "text/html; charset=utf-8")
            if self.path == "/state" and self.headers.get("X-Token") == TOKEN:
                return self._send(200, json.dumps({"speaking": speaker.is_speaking(), "busy": LOCK.locked()}))
            if self.path == "/health" and self.headers.get("X-Token") == TOKEN:
                return self._send(200, json.dumps({"ok": True, "build": BUILD}))
            self._send(404, "{}")
        except Exception as e:
            print(f"(GET error: {e})")
            self._send(500, "{}")

    def do_POST(self):
        try:
            self._post()
        except Exception as e:
            print(f"(POST error: {e})")
            self._send(500, json.dumps({"reply": f"Something failed, sir: {e}"}))

    def _post(self):
        if not self._host_ok() or self.headers.get("X-Token") != TOKEN:
            return self._send(403, "{}")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, "{}")
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, "{}")
        if self.path == "/stop":
            speaker.stop()
            return self._send(200, "{}")
        if self.path != "/ask":
            return self._send(404, "{}")

        text = str(data.get("text", "")).strip()
        if not text:
            return self._send(400, "{}")
        print(f"You: {text}")
        with GUARD:
            if text == LAST["text"] and time.monotonic() - LAST["t"] < 2.0:
                print("(duplicate request ignored)\n")
                return self._send(200, json.dumps({"reply": LAST["reply"]}))
        if not LOCK.acquire(blocking=False):             # the worker releases it when done
            return self._send(200, json.dumps({"reply": "I'm still working on your last request, sir."}))

        t0 = time.monotonic()
        reply = run_brain(text)
        with GUARD:
            LAST.update(text=text, t=time.monotonic(), reply=reply)
        print(f"JARVIS ({time.monotonic() - t0:.1f}s): {reply}\n")
        if data.get("speak", True):
            say, is_long = to_speech(reply)
            speaker.speak(say, long=is_long)
        self._send(200, json.dumps({"reply": reply}))


def launch_window():
    if os.environ.get("JARVIS_NO_WINDOW"):
        return
    url = f"http://{HOST}:{PORT}/"
    try:
        if os.path.isdir("/Applications/Google Chrome.app"):
            subprocess.Popen(["open", "-na", "Google Chrome", "--args", f"--app={url}", "--window-size=1100,800"])
            return
    except OSError:
        pass
    webbrowser.open(url)


def main():
    global brain, speaker
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"Port {PORT} is already in use: an OLD JARVIS is still running.")
        print(f"Stop it with:  lsof -ti:{PORT} | xargs kill   then start again.")
        sys.exit(1)
    server.daemon_threads = True
    speaker = Speaker()
    brain = Brain()
    threading.Thread(target=speaker.warm, daemon=True).start()
    threading.Thread(target=brain.warm, daemon=True).start()
    print(f"JARVIS build {BUILD} online at http://{HOST}:{PORT}")
    print(f"Voice: {speaker.describe()}")
    print(f"Brain: {brain.describe()}")
    print("Conversation is mirrored here. Ctrl+C to shut down.\n")
    hour = datetime.datetime.now().hour
    part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    threading.Timer(1.5, lambda: speaker.speak(f"Good {part}, sir. All systems online.")).start()
    threading.Timer(0.8, launch_window).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        speaker.stop()
        print("\nJARVIS: Shutting down, sir.")
        server.server_close()


if __name__ == "__main__":
    main()