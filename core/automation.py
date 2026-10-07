"""Mac control layer. Standard library only. Every function returns plain values, never raises."""
import datetime
import difflib
import email.utils
import json
import os
import re
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import quote

HOME = os.path.expanduser("~")
APP_DIRS = ["/Applications", "/System/Applications", "/System/Applications/Utilities",
            "/Applications/Utilities", os.path.join(HOME, "Applications")]

SITES = {
    "google": "https://www.google.com", "youtube": "https://www.youtube.com",
    "reddit": "https://www.reddit.com", "instagram": "https://www.instagram.com",
    "insta": "https://www.instagram.com", "github": "https://github.com",
    "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    "x": "https://x.com", "twitter": "https://x.com", "facebook": "https://www.facebook.com",
    "whatsapp": "https://web.whatsapp.com", "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.com", "netflix": "https://www.netflix.com",
    "gmail": "https://mail.google.com", "maps": "https://maps.google.com",
}
SEARCH = {
    "google": "https://www.google.com/search?q=",
    "youtube": "https://www.youtube.com/results?search_query=",
    "reddit": "https://www.reddit.com/search/?q=",
    "amazon": "https://www.amazon.com/s?k=",
    "github": "https://github.com/search?q=",
}
FOLDERS = {"downloads": "~/Downloads", "desktop": "~/Desktop", "documents": "~/Documents",
           "pictures": "~/Pictures", "home": "~", "applications": "/Applications"}
ALIASES = {"vscode": "visual studio code", "vs code": "visual studio code", "term": "terminal",
           "settings": "system settings", "preferences": "system settings"}
DOMAIN_RE = re.compile(r"^[\w-]+(\.[\w-]+)+(/\S*)?$")
NEWS_EDITION = os.environ.get("JARVIS_NEWS_EDITION", "US:en")       # e.g. SA:en, GB:en, AE:en

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# ---------- low level ----------
def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout if p.returncode == 0 else p.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, str(e)


def osa(script, *args, timeout=30):
    """Run AppleScript. Arguments arrive safely as `argv` (no string escaping bugs)."""
    return run(["osascript", "-e", script, *args], timeout)


def shell(cmd):
    return run(["/bin/zsh", "-c", cmd], timeout=60)


def fetch(url, timeout=15):
    """GET a URL as text. Falls back to curl (which uses the macOS certificates) if Python's SSL fails."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        try:
            p = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", _UA, url],
                               capture_output=True, timeout=timeout + 5)
            return p.stdout.decode("utf-8", "ignore") if p.returncode == 0 else ""
        except Exception:
            return ""


# ---------- apps / sites / files ----------
_apps = None


def installed_apps():
    global _apps
    if _apps is None:
        _apps = {}
        for d in APP_DIRS:
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.endswith(".app"):
                        _apps[f[:-4].lower()] = f[:-4]
    return _apps


def find_app(query, fuzzy=True):
    q = query.lower().strip()
    q = ALIASES.get(q, q)
    apps = installed_apps()
    if q in apps:
        return apps[q]
    if not fuzzy:
        return None
    if len(q) >= 3:
        hits = [n for n in apps if q in n]
        if hits:
            return apps[min(hits, key=len)]
    close = difflib.get_close_matches(q, list(apps), n=1, cutoff=0.75)
    return apps[close[0]] if close else None


def open_app(name):
    app = find_app(name)
    if not app:
        return False, f"No app matching '{name}'."
    ok, err = run(["open", "-a", app])
    return ok, app if ok else err


def open_url(url, browser=None):
    if browser:
        app = find_app(browser)
        if app:
            return run(["open", "-a", app, url])
    return run(["open", url])


def search_url(site, query):
    return SEARCH.get(site, SEARCH["google"]) + quote(query)


def open_path(path, reveal=False):
    return run(["open", "-R", path] if reveal else ["open", path])


def find_files(query, limit=8):
    ok, out = run(["mdfind", "-onlyin", HOME, "-name", query], timeout=20)
    if not ok:
        return []
    paths = [p for p in out.splitlines()[:400]
             if "/Library/" not in p and "/." not in p and ".app/" not in p]

    def mtime(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0
    return sorted(paths, key=mtime, reverse=True)[:limit]


def short(path):
    return path.replace(HOME, "~", 1)


def open_anything(name, browser=None, kind=None):
    """Open an app, site, folder, path or file by name. Returns (message, files_or_None)."""
    n = name.strip().strip("\"'")
    low = n.lower()

    if kind in (None, "folder") and low in FOLDERS:
        ok, err = open_path(os.path.expanduser(FOLDERS[low]))
        return (f"Opened {low}." if ok else f"Couldn't open {low}: {err}"), None

    if n.startswith(("/", "~")):
        p = os.path.expanduser(n)
        if os.path.exists(p):
            ok, err = open_path(p)
            return (f"Opened {short(p)}." if ok else f"Couldn't open: {err}"), None

    if kind in (None, "app"):
        app = find_app(low, fuzzy=False)
        if app:
            ok, err = run(["open", "-a", app])
            return (f"Opened {app}." if ok else f"Couldn't open {app}: {err}"), None

    if kind in (None, "site") and low in SITES:
        ok, err = open_url(SITES[low], browser)
        return (f"Opened {low}." if ok else f"Couldn't open {low}: {err}"), None

    if kind in (None, "app"):
        ok, res = open_app(n)
        if ok:
            return f"Opened {res}.", None

    if kind in (None, "site") and DOMAIN_RE.match(n):
        ok, err = open_url(n if n.startswith("http") else "https://" + n, browser)
        return (f"Opened {n}." if ok else f"Couldn't open {n}: {err}"), None

    if kind in (None, "file", "folder"):
        files = find_files(n)
        if len(files) == 1:
            ok, err = open_path(files[0])
            return (f"Opened {short(files[0])}." if ok else f"Couldn't open: {err}"), files
        if files:
            lines = "\n".join(f"{i}. {short(f)}" for i, f in enumerate(files, 1))
            return f"Several matches:\n{lines}\nSay 'open 1' (or 2, 3...).", files

    return f"I couldn't find an app, site, or file called '{n}'.", None


# ---------- system ----------
def quit_app(name):
    app = find_app(name)
    if not app:
        return False, f"No app matching '{name}'."
    ok, err = osa('on run argv\ntell application (item 1 of argv) to quit\nend run', app)
    return ok, app if ok else err


def set_volume(level):
    level = max(0, min(100, int(level)))
    return osa(f"set volume output volume {level}")


def set_mute(muted):
    return osa(f"set volume output muted {'true' if muted else 'false'}")


def screenshot():
    path = os.path.join(HOME, "Desktop", time.strftime("screenshot-%Y%m%d-%H%M%S.png"))
    ok, err = run(["screencapture", "-x", path])
    return ok, path if ok else err


def type_text(text):
    return osa('on run argv\ntell application "System Events" to keystroke (item 1 of argv)\nend run', text)


_MODS = {"cmd": "command down", "command": "command down", "shift": "shift down",
         "opt": "option down", "option": "option down", "alt": "option down",
         "ctrl": "control down", "control": "control down"}
_KEYS = {"return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "escape": 53,
         "esc": 53, "left": 123, "right": 124, "down": 125, "up": 126}


def press(combo):
    parts = [p for p in re.split(r"[+\s]+", combo.lower().strip()) if p]
    if not parts:
        return False, "No keys given."
    mods = [_MODS[p] for p in parts[:-1] if p in _MODS]
    key = parts[-1]
    using = f" using {{{', '.join(mods)}}}" if mods else ""
    if key in _KEYS:
        body = f"key code {_KEYS[key]}{using}"
    elif len(key) == 1 and key not in '"\\':
        body = f'keystroke "{key}"{using}'
    else:
        return False, f"Unknown key '{key}'."
    return osa(f'tell application "System Events" to {body}')


def battery():
    ok, out = run(["pmset", "-g", "batt"])
    if not ok:
        return False, out
    m = re.search(r"(\d+)%;\s*([\w ]+)", out)
    return (True, f"Battery {m[1]}%, {m[2].strip()}.") if m else (True, out.splitlines()[-1])


def lock_screen():
    return osa('tell application "System Events" to keystroke "q" using {control down, command down}')


# ---------- news (Google News RSS, live) ----------
def google_news(topic=None, limit=8):
    """Returns a list of {title, source, age}, [] if nothing found, or None if Google News is unreachable."""
    gl, lang = NEWS_EDITION.split(":")
    tail = f"hl={lang}&gl={gl}&ceid={gl}:{lang}"
    url = (f"https://news.google.com/rss/search?q={quote(topic)}&{tail}" if topic
           else f"https://news.google.com/rss?{tail}")
    xml = fetch(url)
    if not xml:
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    items = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        age = ""
        try:
            mins = int((now - email.utils.parsedate_to_datetime(it.findtext("pubDate"))).total_seconds() // 60)
            age = f"{mins}m ago" if mins < 60 else f"{mins // 60}h ago" if mins < 1440 else f"{mins // 1440}d ago"
        except Exception:
            pass
        if title:
            items.append({"title": title, "source": src, "age": age})
        if len(items) >= limit:
            break
    return items


# ---------- Apple Mail (bulk reads: fast even on big mailboxes) ----------
_MAIL_LIST = '''
on run argv
  set scanN to (item 1 of argv) as integer
  set onlyUnread to (item 2 of argv) is "1"
  tell application "Mail"
    set total to count of messages of inbox
    if total is 0 then return ""
    set lim to scanN
    if total < lim then set lim to total
    set ids to id of messages 1 thru lim of inbox
    set snd to sender of messages 1 thru lim of inbox
    set subs to subject of messages 1 thru lim of inbox
    set rds to read status of messages 1 thru lim of inbox
  end tell
  set out to ""
  repeat with i from 1 to lim
    if (not onlyUnread) or ((item i of rds) is false) then
      set out to out & (item i of ids) & tab & (item i of snd) & tab & (item i of subs) & linefeed
    end if
  end repeat
  return out
end run
'''

_MAIL_BODY = '''
on run argv
  set theID to (item 1 of argv) as integer
  tell application "Mail"
    set m to first message of inbox whose id is theID
    set read status of m to true
    return "From: " & (sender of m) & linefeed & "Subject: " & (subject of m) & linefeed & linefeed & (content of m)
  end tell
end run
'''

_MAIL_REPLY = '''
on run argv
  set theID to (item 1 of argv) as integer
  set theBody to item 2 of argv
  tell application "Mail"
    set m to first message of inbox whose id is theID
    set r to reply m with opening window
    delay 0.6
    set content of r to theBody & return & return & (content of r)
    send r
  end tell
  return "sent"
end run
'''


def mail_list(n=8, unread=True):
    ok, out = osa(_MAIL_LIST, "60" if unread else str(n), "1" if unread else "0", timeout=60)
    if ok:
        out = "\n".join(out.splitlines()[:n])
    return ok, out


def mail_body(mail_id):
    return osa(_MAIL_BODY, str(mail_id), timeout=60)


def mail_reply(mail_id, body):
    return osa(_MAIL_REPLY, str(mail_id), body, timeout=60)


# ---------- YouTube: pick a real video (no browser automation needed) ----------
def youtube_ids(query, limit=12):
    """Read YouTube's results page and return video ids in ranking order."""
    html = fetch("https://www.youtube.com/results?search_query=" + quote(query), timeout=10)
    ids = re.findall(r'"videoRenderer":\{"videoId":"([\w-]{11})"', html) or \
        re.findall(r'"videoId":"([\w-]{11})"', html)
    seen = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    return seen[:limit]


# ---------- run JavaScript in the browser (permission check) ----------
def _js_browser():
    return "Google Chrome" if os.path.isdir("/Applications/Google Chrome.app") else "Safari"


def browser_js(js):
    """Run JS in the FRONT tab (used only for the permission check)."""
    if _js_browser() == "Google Chrome":
        script = ('on run argv\ntell application "Google Chrome" to execute active tab of front window '
                  'javascript (item 1 of argv)\nend run')
    else:
        script = ('on run argv\ntell application "Safari" to do JavaScript (item 1 of argv) '
                  'in current tab of front window\nend run')
    ok, out = osa(script, js)
    if not ok and "avascript" in out:
        out += "  -> Chrome: View > Developer > Allow JavaScript from Apple Events (Safari: Develop menu)."
    return ok, out


# ---------- Instagram chats: JARVIS opens its OWN Chrome window, so it never mixes up tabs ----------
_ig = {"wid": None}

_CHROME_OPEN_WINDOW = """
tell application "Google Chrome"
  activate
  set w to make new window
  set URL of active tab of w to "https://www.instagram.com/direct/inbox/"
  return id of w
end tell
"""

_CHROME_WIN_JS = """
on run argv
  set wid to (item 1 of argv) as integer
  set js to item 2 of argv
  set focusIt to (item 3 of argv) is "1"
  tell application "Google Chrome"
    try
      set w to window id wid
    on error
      return "NOWINDOW"
    end try
    if focusIt then
      set index of w to 1
      activate
      delay 0.5
    end if
    return execute (active tab of w) javascript js
  end tell
end run
"""

_IG_JS = """
(function(mode, name){
  function threads(){
    var els = [].slice.call(document.querySelectorAll('a[href*="/direct/t/"]'));
    if (!els.length) {
      els = [].slice.call(document.querySelectorAll('[role="listitem"],[role="button"][tabindex="0"],[role="link"]'))
        .filter(function(e){ var r = e.getBoundingClientRect();
          return r.width > 150 && r.height > 40 && r.height < 130 && r.left < 520 && e.innerText && e.innerText.trim().length > 1; });
    }
    return els;
  }
  var t = threads();
  if (!t.length) return 'loading';
  var pick = null;
  if (mode === 'random') { pick = t[Math.floor(Math.random() * t.length)]; }
  else { for (var i = 0; i < t.length; i++) { if (t[i].innerText.toLowerCase().indexOf(name) > -1) { pick = t[i]; break; } } }
  if (!pick) return 'notfound:' + t.length;
  var label = pick.innerText.split('\\n')[0];
  pick.click();
  return 'ok:' + label;
})(__MODE__, __NAME__)
"""

_IG_FIND_BOX = ("(function(){var b=document.querySelector('div[role=\"textbox\"][contenteditable=\"true\"]')||"
                "document.querySelector('div[role=\"textbox\"]')||document.querySelector('[contenteditable=\"true\"]');"
                "if(!b)return 'nobox:'+location.pathname;b.focus();return 'ok';})()")

_IG_DEBUG = ("(function(){var a=document.querySelectorAll('a[href*=\"/direct/t/\"]').length;"
             "var tb=document.querySelectorAll('div[role=\"textbox\"]').length;"
             "var ce=document.querySelectorAll('[contenteditable=\"true\"]').length;"
             "var items=[].slice.call(document.querySelectorAll('[role=\"listitem\"],[role=\"button\"][tabindex=\"0\"],[role=\"link\"]'))"
             ".slice(0,8).map(function(e){return (e.getAttribute('role')||'')+':'+(e.innerText||'').trim().split('\\n')[0].slice(0,25);});"
             "return JSON.stringify({title:document.title,path:location.pathname,thread_links:a,textboxes:tb,editables:ce,sample:items});})()")


def _ig_js(js, focus=False):
    """Run JS in the Instagram window JARVIS opened. Returns (ok, output); output 'NOWINDOW' if it was closed."""
    if not _ig["wid"]:
        return True, "NOWINDOW"
    ok, out = osa(_CHROME_WIN_JS, str(_ig["wid"]), js, "1" if focus else "0", timeout=40)
    if not ok and "avascript" in out:
        out += "  -> Chrome: View > Developer > Allow JavaScript from Apple Events."
    return ok, out


def instagram_open_chat(name, random_pick=False):
    """Returns (True, chat label) or (False, error)."""
    if not os.path.isdir("/Applications/Google Chrome.app"):
        return False, "Instagram chat control needs Google Chrome."
    ok, out = osa(_CHROME_OPEN_WINDOW, timeout=30)
    if not ok or not out.strip().isdigit():
        return False, f"Couldn't open a Chrome window: {out}"
    _ig["wid"] = int(out.strip())
    js = (_IG_JS.replace("__MODE__", json.dumps("random" if random_pick else "name"))
                .replace("__NAME__", json.dumps(name.lower().strip())))
    label = None
    for _ in range(14):
        time.sleep(1.5)
        ok, out = _ig_js(js)
        if not ok:
            return False, out
        if out == "NOWINDOW":
            return False, "The Instagram window was closed."
        if out.startswith("ok:"):
            label = out[3:].strip() or name
            break
        if out.startswith("notfound"):
            return False, f"No chat matching '{name}' in your Instagram inbox ({out.split(':')[-1]} chats visible)."
    if label is None:
        return False, ("Instagram's inbox didn't load or I couldn't read it. Make sure you're logged in to "
                       "Instagram in Chrome, then try again.")
    path = ""
    for _ in range(6):                                   # make sure the chat really opened
        time.sleep(0.8)
        ok, path = _ig_js("location.pathname")
        if ok and "/direct/t/" in path:
            return True, label
    return False, (f"I clicked '{label}' but the chat didn't open (page is {path.strip() or 'unknown'}). "
                   "Say 'debug instagram' and send me what it prints.")


def instagram_send(text):
    out = ""
    for i in range(6):                                   # bring the window to the front, wait for the message box
        ok, out = _ig_js(_IG_FIND_BOX, focus=(i == 0))
        if not ok:
            return False, out
        if out == "NOWINDOW":
            return False, "The Instagram window was closed. Ask me to message them again."
        if out == "ok":
            break
        time.sleep(1.0)
    else:
        return False, f"Couldn't find Instagram's message box ({out}). Say 'debug instagram' and send me what it prints."
    ok, err = type_text(text)
    if not ok:
        return False, err + "  (allow VS Code/Terminal under Settings > Privacy & Security > Accessibility)"
    time.sleep(0.4)
    ok, err = osa('tell application "System Events" to key code 36')
    if not ok:
        return False, "Typed the message but couldn't press Enter: " + err
    time.sleep(1.0)                                      # verify: the box should be empty after sending
    ok, left = _ig_js("(function(){var b=document.querySelector('div[role=\"textbox\"]');"
                      "return b?String(b.innerText.trim().length):'0';})()")
    if ok and left.strip() not in ("0", ""):
        return False, "I typed the message, but Instagram didn't send it. Press Enter in the Instagram window."
    return True, ""


def instagram_debug():
    ok, out = _ig_js(_IG_DEBUG)
    if out == "NOWINDOW":
        return False, "No Instagram window yet. Run a 'message <name> on instagram' command first, then 'debug instagram'."
    return ok, out


# ---------- hand a task to Claude ----------
def claude_prompt(prompt, send=True):
    """Open Claude with the prompt filled in (official claude:// deep link), then press Enter to send."""
    q = quote(prompt, safe="")
    if find_app("claude", fuzzy=False):
        ok, err = run(["open", "claude://claude.ai/new?q=" + q])
        if not ok:
            return False, err
        if not send:
            return True, "Opened Claude with your request filled in."
        time.sleep(3.0)                                          # let Claude come to the front
        ok, err = osa('tell application "System Events" to key code 36')
        if ok:
            return True, "Asked Claude. I opened it with your request and pressed Enter."
        return True, "Opened Claude with your request filled in. Press Enter to send it (allow Accessibility to automate this)."
    ok, err = open_url("https://claude.ai/new?q=" + q)
    return ok, ("Opened claude.ai with your request. Press Enter there if it isn't sent." if ok else err)


# ---------- self-test: which permissions are missing? ----------
def diagnose():
    """Returns [(name, ok, how_to_fix)]; ok is True / False / None (couldn't test)."""
    rows = []
    ok, out = osa('tell application "Mail" to return (count of accounts)', timeout=25)
    rows.append(("Mail control", ok and out.strip() not in ("", "0"),
                 "Allow VS Code/Terminal to control Mail (Settings > Privacy & Security > Automation) "
                 "and add your account in the Mail app."))
    ok, _ = osa('tell application "System Events" to key code 56')
    rows.append(("Keyboard control (typing, Enter, lock screen)", ok,
                 "Settings > Privacy & Security > Accessibility: add VS Code (or Terminal)."))
    browser = _js_browser()
    if run(["pgrep", "-x", browser])[0]:
        ok, out = browser_js("1+1")
        rows.append((f"{browser} JavaScript (Instagram chats)", ok and out.strip() == "2",
                     "In Chrome: View > Developer > Allow JavaScript from Apple Events."))
    else:
        rows.append((f"{browser} JavaScript (Instagram chats)", None, f"{browser} isn't running. Open it, then run 'check setup' again."))
    try:
        os.listdir(os.path.join(HOME, "Documents"))
        rows.append(("File access (Documents)", True, ""))
    except PermissionError:
        rows.append(("File access (Documents)", False, "Settings > Privacy & Security > Full Disk Access: add VS Code (or Terminal)."))
    except OSError:
        rows.append(("File access (Documents)", None, "Couldn't test."))
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
        rows.append(("Ollama (AI chat)", True, ""))
    except Exception:
        rows.append(("Ollama (AI chat)", False, "Open the Ollama app, or run: ollama serve"))
    rows.append(("Microphone (voice commands)", None,
                 "Click Mic in the JARVIS window, press Allow in Chrome's prompt, and enable Chrome under Settings > Privacy & Security > Microphone."))
    return rows