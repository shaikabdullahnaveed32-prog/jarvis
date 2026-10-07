"""One-time voice setup. Run with the SAME python you use for server.py:   python3 setup_voice.py"""
import os
import subprocess
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(ROOT, "models")
BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {"kokoro-v1.0.onnx": 200_000_000, "voices-v1.0.bin": 10_000_000}   # minimum plausible sizes


def fail(msg):
    print(f"\nFAILED: {msg}")
    sys.exit(1)


def pip(*args):
    return subprocess.run([sys.executable, "-m", "pip", "install", "-U", *args]).returncode == 0


def have_packages():
    try:
        import kokoro_onnx, soundfile  # noqa: F401
        return True
    except Exception:
        return False


def download(name, min_size):
    path = os.path.join(MODELS, name)
    if os.path.exists(path):
        if os.path.getsize(path) >= min_size:
            print(f"  {name}: already downloaded")
            return
        os.remove(path)                                   # corrupt/partial from an earlier attempt
    part = path + ".part"
    print(f"  downloading {name} ...")
    for resume in (True, False):
        cmd = ["curl", "-L", "--fail", "-o", part, BASE + name]
        if resume and os.path.exists(part):
            cmd[1:1] = ["-C", "-"]
        if subprocess.run(cmd).returncode == 0 and os.path.getsize(part) >= min_size:
            os.replace(part, path)
            return
        if os.path.exists(part):
            os.remove(part)
    fail(f"could not download {name}. Check your internet connection and run this script again.")


def bootstrap_venv():
    """Your Python is too new for the voice engine: build a Python 3.12 environment next to JARVIS and re-run in it."""
    venv_py = os.path.join(ROOT, ".venv", "bin", "python")
    if not os.path.exists(venv_py):
        print("Your Python is too new for the voice engine. Creating a Python 3.12 environment (.venv) ...")
        if not (pip("uv") or pip("--break-system-packages", "uv")):
            fail("could not install 'uv'. Alternative: brew install python@3.12, then "
                 "python3.12 -m venv .venv && .venv/bin/python setup_voice.py")
        r = subprocess.run([sys.executable, "-m", "uv", "venv", "--seed", "--python", "3.12", os.path.join(ROOT, ".venv")])
        if r.returncode != 0:
            fail("could not create the Python 3.12 environment (needs internet). Alternative: brew install python@3.12, "
                 "then python3.12 -m venv .venv && .venv/bin/python setup_voice.py")
    os.execv(venv_py, [venv_py, os.path.abspath(__file__)])


print(f"Python: {sys.executable} ({sys.version.split()[0]})")
if not (3, 10) <= sys.version_info[:2] < (3, 14):
    if ".venv" in sys.executable:
        fail("the environment's Python is not 3.10-3.13.")
    bootstrap_venv()
os.makedirs(MODELS, exist_ok=True)

print("\n1/3 Python packages")
if have_packages():
    print("  already installed")
elif not (pip("kokoro-onnx", "soundfile") or pip("--break-system-packages", "kokoro-onnx", "soundfile")):
    fail("pip could not install kokoro-onnx. Try a virtual environment:\n"
         "  python3 -m venv .venv && source .venv/bin/activate && python3 setup_voice.py\n"
         "and then always start JARVIS from that activated environment.")

print("\n2/3 Model files (about 340 MB, one time)")
for name, size in FILES.items():
    download(name, size)

print("\n3/3 Test")
try:
    import soundfile as sf
    from kokoro_onnx import Kokoro
    k = Kokoro(os.path.join(MODELS, "kokoro-v1.0.onnx"), os.path.join(MODELS, "voices-v1.0.bin"))
    x, rate = k.create("Good evening, sir. All systems are online.", voice="bm_george", speed=0.95, lang="en-gb")
    sf.write("/tmp/jarvis_test.wav", x, rate)
    subprocess.run(["afplay", "/tmp/jarvis_test.wav"])
except Exception:
    traceback.print_exc()
    fail("the voice engine installed but crashed on the test (error above).")

print("\nDONE. Start JARVIS with:  ./run.sh   then type:  what voice are you using")
