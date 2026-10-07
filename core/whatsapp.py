"""Send a WhatsApp message through the WhatsApp desktop app (needs Accessibility permission)."""
import re
import subprocess
import time
import urllib.parse


def send(phone, text):
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return False, "Invalid phone number."
    subprocess.run(["open", f"whatsapp://send?phone={digits}&text={urllib.parse.quote(text)}"], check=False)
    time.sleep(4)
    script = ('tell application "WhatsApp" to activate\ndelay 0.6\n'
              'tell application "System Events" to key code 36')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()