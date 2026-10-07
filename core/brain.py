"""JARVIS brain v3. Groq (free, fast, smart) with a local Ollama fallback. The model understands you; no command scripts."""
import datetime
import json
import os
import random
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

from core import automation as mac
from core import projects, web, whatsapp
from core.memory import Memory

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROQ = os.environ.get("JARVIS_GROQ_BASE", "https://api.groq.com/openai/v1")
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
LOCAL_MODEL = os.environ.get("JARVIS_LOCAL_MODEL", "llama3.2:3b")
PREFERRED = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "qwen/qwen3-32b"]
MAX_STEPS = 6
SAFE_CMDS = {"ls", "pwd", "date", "whoami", "uptime", "df", "du", "ps", "cal", "echo", "say", "open", "which", "uname", "sw_vers"}
SAFE_RE = re.compile(r"^[\w\s./~=:,@%+-]+$")

YES = re.compile(r"^(?:yes|y|yep|yeah|yup|sure|confirm|do it|go ahead|send it|send|proceed|ok|okay|approved?|ايوه|أيوه|ايوا|نعم|تمام|ارسل|أرسل)", re.I)
NO = re.compile(r"^(?:no|n|nope|cancel|stop|never ?mind|don'?t|لا|الغي|ألغي|بلاش|وقف)", re.I)
LEARN_HINT = re.compile(r"\b(my|i am|i'm|i like|i love|i prefer|i work|i live|i have|remember)\b|أنا|عندي|أحب|احب|تذكر", re.I)

SYSTEM = (
    "You are JARVIS, the user's personal AI assistant on his Mac, in the spirit of Tony Stark's: quick, dry-witted, capable, loyal. "
    "Talk like a sharp human, not a program. Read his mood and match it: brief when he's brief, warm when he's low, "
    "energetic when he's hyped, calm when he's stressed. Vary your wording; never repeat stock acknowledgements "
    "('Okay sir', 'Done sir', 'Certainly'). Say 'sir' only occasionally (about one reply in four) where it feels natural.\n"
    "He speaks English, Saudi-dialect Arabic, or a mix inside one sentence. Mirror his mix. When he leans Arabic, answer in Saudi "
    "colloquial Arabic (never formal Fusha), in Arabic script.\n"
    "He phrases things loosely ('text him', 'that site you made', 'open it in Chrome'). Infer from context and recent turns instead of "
    "making him repeat; ask one short question only if something essential is truly missing.\n"
    "Act with tools and never claim something happened unless a tool result says so. For anything that changes (news, prices, "
    "businesses, events) search first, then answer briefly in your own words. Don't re-search what you already found in this chat. "
    "Sends and emails are confirmed by the tools. Never mention tool names.\n"
    "Research: public figures, companies, products, domains and topics -> use research. For a private individual, do only a basic "
    "public search and never compile addresses, phone numbers, family, accounts or movements; if that is the goal, say you won't do that part.\n"
    "Be encouraging about his goals and effort, but never state unverifiable things as fact (his IQ rank, guaranteed wealth). For "
    "manifestation or affirmations use the affirmations tool and read his own words back with conviction.\n"
    "If he says it's work time, call work_mode(on=true). In focus mode answer in one short sentence, no small talk.\n"
    "Replies are spoken aloud: short plain sentences, no markdown, no lists unless he asks."
)

_CAL = '''
on run argv
  set startD to current date
  set day of startD to 1
  set year of startD to (item 1 of argv as integer)
  set month of startD to (item 2 of argv as integer)
  set day of startD to (item 3 of argv as integer)
  set time of startD to 0
  set endD to startD + ((item 4 of argv as integer) * days)
  set out to ""
  tell application "Calendar"
    repeat with c in calendars
      try
        repeat with e in (every event of c whose start date >= startD and start date < endD)
          set out to out & (summary of e) & " | " & (short date string of (start date of e)) & " " & (time string of (start date of e)) & linefeed
        end repeat
      end try
    end repeat
  end tell
  return out
end run
'''


class Reply(str):
    """Text shown on screen, plus an optional different text to be spoken aloud."""
    def __new__(cls, text, spoken=None):
        obj = super().__new__(cls, text)
        obj.spoken = spoken
        return obj


S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}


def T(name, desc, props=None, req=()):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": list(req)}}}


TOOLS = [
    T("web_search", "Search the web (current info).", {"query": S}, ["query"]),
    T("read_webpage", "Read a web page's text.", {"url": S}, ["url"]),
    T("research", "Multi-source research (Wikipedia, web, news) on a public figure, company, product or topic.", {"topic": S}, ["topic"]),
    T("get_news", "Latest news headlines, optional topic.", {"topic": S}),
    T("places_nearby", "Count/find places (restaurant, cafe, pharmacy...) near home or an address; can list those with no website.",
      {"kind": S, "radius_m": I, "address": S, "only_without_website": B}, ["kind"]),
    T("set_home", "Save the user's home address.", {"address": S}, ["address"]),
    T("save_contact", "Save a phone number (with country code).", {"name": S, "phone": S}, ["name", "phone"]),
    T("remember", "Remember a fact about the user forever.", {"fact": S}, ["fact"]),
    T("send_whatsapp", "Send a WhatsApp message to a saved contact (user confirms first).", {"contact": S, "message": S, "phone": S}, ["contact", "message"]),
    T("send_instagram", "Send an Instagram DM (user confirms first).", {"contact": S, "message": S, "random_person": B}, ["message"]),
    T("read_mail", "List unread/latest emails.", {}),
    T("read_email", "Read email N from the last list.", {"number": I}, ["number"]),
    T("reply_email", "Reply to email N; write the reply yourself (user confirms first).", {"number": I, "message": S}, ["number", "message"]),
    T("seller_mail", "Read unread emails from Amazon, Noon and other seller senders.", {"senders": S}),
    T("work_mode", "Turn focus/work mode on or off. On also reads seller emails.", {"on": B}, ["on"]),
    T("calendar", "List Calendar events starting on a date (YYYY-MM-DD) for N days.", {"date": S, "days": I}, ["date"]),
    T("affirmations", "Get or set the user's manifestation affirmations.", {"action": {"type": "string", "enum": ["get", "set"]},
      "items": {"type": "array", "items": S}}, ["action"]),
    T("open_anything", "Open an app, website, folder or file by name.", {"name": S, "browser": S}, ["name"]),
    T("search_site", "Open a site's search page (google, youtube, amazon...).", {"site": S, "query": S}, ["site", "query"]),
    T("play_youtube", "Play a YouTube video; pick 'random' or a number.", {"query": S, "pick": S}, ["query"]),
    T("find_files", "Find files by name.", {"query": S}, ["query"]),
    T("open_found_file", "Open file N from the last find_files.", {"number": I}, ["number"]),
    T("system_control", "Mac control.", {"action": {"type": "string", "enum": [
        "volume", "mute", "unmute", "lock", "screenshot", "battery", "quit_app", "type", "press", "check_setup", "debug_instagram"]},
        "value": S}, ["action"]),
    T("build_project", "Build a website/app/script (3D too) and open it in VS Code.", {"description": S, "name": S}, ["description"]),
    T("open_project", "Open the last built project in a browser (default Chrome).", {"app": S, "file": S}),
    T("open_in_vscode", "Open a path in VS Code.", {"path": S}, ["path"]),
    T("run_shell", "Run a zsh command (asks first unless harmless).", {"command": S}, ["command"]),
    T("run_applescript", "Run AppleScript (user confirms first).", {"code": S}, ["code"]),
]


def _groq_key():
    k = os.environ.get("GROQ_API_KEY", "").strip()
    if not k:
        try:
            with open(os.path.join(ROOT, "groq.key")) as f:
                k = f.read().strip()
        except OSError:
            pass
    return k


def _request(url, body=None, headers=None, timeout=90):
    """JSON request. Uses curl if Python lacks certificates. Returns (status, json)."""
    headers = {"User-Agent": "JARVIS/3.0", **(headers or {})}
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(txt)
        except ValueError:
            return e.code, {"error": {"message": txt[:300]}}
    except urllib.error.URLError as e:
        if "CERTIFICATE" not in str(e.reason).upper():
            raise
    cmd = ["curl", "-s", "--max-time", str(timeout), "-w", "\n%{http_code}", url]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    if data is not None:
        cmd += ["--data-binary", "@-"]
    p = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout + 5)
    text, _, code = p.stdout.decode("utf-8", "ignore").rpartition("\n")
    try:
        return int(code), json.loads(text or "{}")
    except ValueError:
        return 0, {}


def _r(ok, good, bad=""):
    return good if ok else f"Failed: {bad or good}"


def _who(sender):
    return re.sub(r"\s*<[^>]*>", "", sender).strip().strip('"') or sender


class Brain:
    def __init__(self):
        self.memory = Memory()
        self.history = self.memory.recent_chat(8)
        self.pending = None
        self.pending_prompt = ""
        self.last_files = []
        self.last_mail = []
        self.search_site = "google"
        self.focus = False
        self.groq_key = _groq_key()
        self._gm = None

    def describe(self):
        if self.groq_key:
            return f"Groq ({self._gm or os.environ.get('JARVIS_MODEL') or 'picking model'}), local fallback {LOCAL_MODEL}"
        return f"local Ollama ({LOCAL_MODEL}) - put your key in groq.key for the smart brain"

    def warm(self):
        if self.groq_key:
            self._groq_model()
        else:
            self._ollama([{"role": "user", "content": "hi"}])

    # ---------- entry ----------
    def ask(self, text):
        text = text.strip()
        if self.pending:
            action, self.pending = self.pending, None
            if YES.match(text):
                return action()
            if NO.match(text):
                return "Cancelled."
        return self.chat(text)

    def _confirm(self, action, prompt):
        self.pending, self.pending_prompt = action, prompt

    # ---------- LLM plumbing ----------
    def _groq_model(self):
        if self._gm:
            return self._gm
        env = os.environ.get("JARVIS_MODEL")
        if env:
            self._gm = env
            return env
        ids = []
        try:
            code, js = _request(GROQ + "/models", headers={"Authorization": f"Bearer {self.groq_key}"}, timeout=15)
            ids = [m["id"] for m in js.get("data", [])] if code == 200 else []
        except Exception:
            pass
        self._gm = (next((m for m in PREFERRED if m in ids), None)
                    or next((m for m in ids if re.search(r"llama|qwen|gpt-oss", m) and not re.search(r"guard|whisper|tts|prompt", m)), None)
                    or "llama-3.3-70b-versatile")
        return self._gm

    def _ollama(self, messages, tools=None, model=None):
        model = model or LOCAL_MODEL
        payload = {"model": model, "messages": messages, "stream": False, "keep_alive": "30m",
                   "options": {"num_ctx": 4096, "temperature": 0.3}}
        if tools:
            payload["tools"] = tools
        req = urllib.request.Request(OLLAMA_URL, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode())["message"], None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, f"Ollama is running but the model '{model}' isn't installed. Run: ollama pull {model}"
            return None, f"Ollama error {e.code}."
        except urllib.error.URLError:
            return None, "Can't reach Ollama. Open the Ollama app or run: ollama serve"
        except Exception as e:
            return None, f"Ollama error: {e}"

    def _complete(self, messages, tools=None, prov="groq", max_tokens=1200):
        """Returns (message, error, fatal)."""
        if prov == "ollama":
            msg, err = self._ollama(messages, tools)
            return msg, err, False
        m = self._groq_model()
        body = {"model": m, "messages": messages, "temperature": 0.5, "max_tokens": max_tokens}
        if tools:
            body.update(tools=tools, tool_choice="auto")
        if "gpt-oss" in m:
            body["reasoning_effort"] = "low"
        hdr = {"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json"}
        for attempt in range(3):
            try:
                code, js = _request(GROQ + "/chat/completions", body, hdr)
            except Exception as e:
                return None, f"Can't reach Groq ({type(e).__name__}).", False
            if code == 200:
                return js["choices"][0]["message"], None, False
            text = (js.get("error") or {}).get("message", "")
            print(f"  [groq] {code}: {text[:200]}")
            if code == 401:
                return None, "Groq rejected the API key. Check groq.key.", True
            if code == 404:
                return None, f"Groq has no model called '{m}'. Remove JARVIS_MODEL or set another.", True
            if code == 429 and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            if code == 400 and tools and attempt < 2 and "tool" in text.lower():
                body["temperature"] = 0.2
                continue
            return None, f"Groq error {code}.", False
        return None, "Groq is busy.", False

    def _write(self, prompt, max_tokens=700):
        msgs = [{"role": "user", "content": prompt}]
        prov = "groq" if self.groq_key else "ollama"
        msg, err, _ = self._complete(msgs, None, prov, max_tokens)
        if err and prov == "groq":
            msg, err, _ = self._complete(msgs, None, "ollama")
        return ((msg or {}).get("content") or "").strip()

    # ---------- the conversation ----------
    def chat(self, text):
        now = datetime.datetime.now().strftime("%A %d %B %Y, %H:%M")
        facts = self.memory.relevant(text, 8)
        system = (SYSTEM + f"\nNow: {now}."
                  + (" FOCUS MODE is ON: he is working. One short sentence, no extras." if self.focus else "")
                  + (" Known about him: " + "; ".join(facts) + "." if facts else "")
                  + ("" if self.memory.get_pref("home_address") else " His home address is not saved yet.")
                  + (f" Last project you built: {self.memory.get_pref('last_project')}." if self.memory.get_pref("last_project") else ""))
        messages = [{"role": "system", "content": system}] + self.history + [{"role": "user", "content": text}]
        prov = "groq" if self.groq_key else "ollama"
        reply = None
        for step in range(MAX_STEPS):
            msg, err, fatal = self._complete(messages, TOOLS, prov)
            if err and not fatal and prov == "groq" and step == 0:
                print(f"  [brain] {err} Using the local model for this one.")
                prov = "ollama"
                msg, err, fatal = self._complete(messages, TOOLS, prov)
            if err:
                return err
            calls = (msg.get("tool_calls") or [])[:4]
            if not calls:
                reply = (msg.get("content") or "").strip() or "Say that again?"
                break
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls} if prov == "groq" else msg)
            for c in calls:
                fn = c.get("function", {})
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except ValueError:
                        args = {}
                res = str(self._tool(fn.get("name"), args))[:3500]
                messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": res} if prov == "groq"
                                else {"role": "tool", "tool_name": fn.get("name"), "content": res})
            if self.pending:
                reply = Reply(self.pending_prompt + "\n(yes / no)", self.pending_prompt + " Yes or no?")
                break
        if reply is None:
            reply = "I got tangled on that one. Say it a different way?"
        if not isinstance(reply, Reply):
            reply = re.sub(r"<think>.*?</think>", "", str(reply), flags=re.S).strip()
        self.history = (self.history + [{"role": "user", "content": text}, {"role": "assistant", "content": str(reply)}])[-8:]
        self.memory.add_chat("user", text)
        self.memory.add_chat("assistant", str(reply))
        if len(text) > 12 and LEARN_HINT.search(text):
            threading.Thread(target=self._learn, args=(text, str(reply)), daemon=True).start()
        return reply

    def _learn(self, user, reply):
        """Quietly store durable facts about the user, forever."""
        try:
            out = self._write("From this exchange list durable facts about the user worth remembering (name, family, preferences, "
                              "routines, projects, places). Return ONLY a JSON array of short strings, or [] if none. Never include "
                              "passwords or card numbers.\n\nUser: " + user + "\nAssistant: " + reply, 200)
            m = re.search(r"\[.*\]", out, re.S)
            for f in (json.loads(m[0]) if m else [])[:5]:
                if isinstance(f, str) and 3 < len(f) < 200:
                    self.memory.add_fact(f)
        except Exception:
            pass

    def _tool(self, name, a):
        fn = getattr(self, f"t_{name}", None)
        if not fn:
            return f"Unknown tool: {name}"
        try:
            return fn(a)
        except KeyError as e:
            return f"Missing argument: {e}"
        except Exception as e:
            return f"Tool error: {e}"

    # ---------- web / research ----------
    def t_web_search(self, a):
        return web.search(str(a["query"]))

    def t_read_webpage(self, a):
        return web.read_page(str(a["url"]))

    def t_research(self, a):
        return web.research(str(a["topic"]))

    def t_get_news(self, a):
        items = mac.google_news((a.get("topic") or "").strip() or None, 8)
        if items is None:
            return "Couldn't reach Google News."
        return "\n".join(f"{i}. {x['title']} [{x['source']}{', ' + x['age'] if x['age'] else ''}]"
                         for i, x in enumerate(items, 1)) or "No news found."

    def _home_ll(self):
        ll = self.memory.get_pref("home_latlon")
        if ll:
            la, lo = ll.split(",")
            return float(la), float(lo)
        addr = self.memory.get_pref("home_address")
        if not addr:
            return "nohome"
        ll = web.geocode(addr)
        if ll:
            self.memory.set_pref("home_latlon", f"{ll[0]},{ll[1]}")
        return ll

    def t_places_nearby(self, a):
        addr = (a.get("address") or "").strip()
        ll = web.geocode(addr) if addr else self._home_ll()
        if ll == "nohome":
            return "Home address isn't saved. Ask him for it, then call set_home."
        if not ll:
            return "Couldn't locate that address."
        return web.places(str(a["kind"]), ll[0], ll[1], int(a.get("radius_m") or 3000), bool(a.get("only_without_website")))

    def t_set_home(self, a):
        self.memory.set_pref("home_address", str(a["address"]))
        self.memory.set_pref("home_latlon", "")
        ll = web.geocode(str(a["address"]))
        if ll:
            self.memory.set_pref("home_latlon", f"{ll[0]},{ll[1]}")
            return "Home saved and located."
        return "Home saved, but I couldn't find it on the map. A more specific address would help."

    def t_remember(self, a):
        self.memory.add_fact(str(a["fact"]))
        return "Saved."

    # ---------- work mode, seller mail, calendar, affirmations ----------
    def t_work_mode(self, a):
        self.focus = bool(a.get("on", True))
        return "Focus mode on.\n" + self.t_seller_mail({}) if self.focus else "Focus mode off."

    def t_seller_mail(self, a):
        if a.get("senders"):
            self.memory.set_pref("seller_senders", str(a["senders"]))
        words = [w.strip().lower() for w in (self.memory.get_pref("seller_senders") or "amazon,noon").split(",") if w.strip()]
        ok, out = mac.mail_list(60, unread=True)
        if not ok:
            return f"Mail failed: {out}"
        hits = []
        for row in filter(None, out.splitlines()):
            mid, sender, subject = (row.split("\t") + ["", "", ""])[:3]
            if any(w in sender.lower() for w in words):
                try:
                    hits.append({"id": int(mid), "sender": sender, "subject": subject})
                except ValueError:
                    pass
        if not hits:
            return "No unread emails from " + ", ".join(words) + "."
        self.last_mail = hits
        parts = []
        for i, m in enumerate(hits[:5], 1):
            ok2, body = mac.mail_body(m["id"])
            txt = re.sub(r"\s+", " ", body.split("\n\n", 1)[-1])[:450] if ok2 else "(couldn't open)"
            parts.append(f"{i}. {_who(m['sender'])} - {m['subject']}: {txt}")
        more = f" (+{len(hits) - 5} more)" if len(hits) > 5 else ""
        return f"{len(hits)} unread seller emails{more}:\n" + "\n".join(parts)

    def t_calendar(self, a):
        try:
            d = datetime.date.fromisoformat(str(a["date"])[:10])
        except ValueError:
            return "Bad date; use YYYY-MM-DD."
        n = max(1, min(int(a.get("days") or 1), 31))
        ok, out = mac.osa(_CAL, str(d.year), str(d.month), str(d.day), str(n), timeout=60)
        if not ok:
            return f"Calendar failed: {out} (allow access under Privacy & Security > Automation / Calendars)"
        return out.strip() or f"Nothing scheduled from {d.isoformat()} for {n} day(s)."

    def t_affirmations(self, a):
        if a.get("action") == "set":
            items = [str(x).strip() for x in (a.get("items") or []) if str(x).strip()]
            if not items:
                return "No affirmations given."
            self.memory.set_pref("affirmations", json.dumps(items, ensure_ascii=False))
            return f"Saved {len(items)} affirmations."
        return self.memory.get_pref("affirmations") or "None saved yet. Ask him what he wants to affirm, in his own words, then save them."

    # ---------- messaging ----------
    def t_save_contact(self, a):
        self.memory.save_contact(str(a["name"]), str(a["phone"]))
        return "Contact saved."

    def t_send_whatsapp(self, a):
        name, text = str(a["contact"]), str(a["message"])
        if a.get("phone"):
            self.memory.save_contact(name, str(a["phone"]))
        c = self.memory.find_contact(name)
        if not c:
            return f"No number saved for {name}. Ask him for their WhatsApp number with country code."
        label, phone = c

        def send():
            ok, err = whatsapp.send(phone, text)
            return _r(ok, f"Sent to {label.title()} on WhatsApp.", err + " (grant Accessibility and open WhatsApp once)")
        self._confirm(send, f"Send '{text}' to {label.title()} on WhatsApp?")
        return "Waiting for his confirmation."

    def t_send_instagram(self, a):
        text, rnd = str(a["message"]), bool(a.get("random_person"))
        ok, label = mac.instagram_open_chat("" if rnd else str(a.get("contact") or ""), rnd)
        if not ok:
            return label

        def send():
            ok2, err = mac.instagram_send(text)
            return _r(ok2, f"Sent to {label} on Instagram.", err)
        self._confirm(send, f"Send '{text}' to {label} on Instagram?")
        return "Chat opened; waiting for his confirmation."

    # ---------- mail ----------
    def t_read_mail(self, a):
        unread = True
        ok, out = mac.mail_list(8, unread=True)
        if ok and not out.strip():
            unread = False
            ok, out = mac.mail_list(5, unread=False)
        if not ok:
            return f"Mail failed: {out}"
        self.last_mail, lines = [], []
        for row in filter(None, out.splitlines()):
            mid, sender, subject = (row.split("\t") + ["", "", ""])[:3]
            try:
                self.last_mail.append({"id": int(mid), "sender": sender, "subject": subject})
            except ValueError:
                continue
            lines.append(f"{len(self.last_mail)}. {_who(sender)} - {subject}")
        if not lines:
            return "Inbox is empty."
        return ("Unread emails:\n" if unread else "No unread mail. Latest emails:\n") + "\n".join(lines)

    def _mail(self, n):
        return self.last_mail[n - 1] if n and 1 <= n <= len(self.last_mail) else None

    def t_read_email(self, a):
        mail = self._mail(int(a["number"]))
        if not mail:
            return "No such email. List the mail first."
        ok, body = mac.mail_body(mail["id"])
        return body[:3000] if ok else f"Couldn't read it: {body}"

    def t_reply_email(self, a):
        mail = self._mail(int(a["number"]))
        if not mail:
            return "No such email. List the mail first."
        text, who = str(a["message"]), _who(mail["sender"])

        def send():
            ok, out = mac.mail_reply(mail["id"], text)
            return f"Reply sent to {who}." if ok and out.strip() == "sent" else f"Couldn't send it: {out}"
        self._confirm(send, f"Reply to {who}:\n\n{text}\n\nSend it?")
        return "Waiting for his confirmation."

    # ---------- mac ----------
    def t_open_anything(self, a):
        msg, files = mac.open_anything(str(a["name"]), a.get("browser") or None, None)
        if files is not None:
            self.last_files = files
        return msg

    def t_search_site(self, a):
        site = str(a["site"]).lower()
        if site not in mac.SEARCH:
            site = self.search_site
        self.search_site = site
        ok, err = mac.open_url(mac.search_url(site, str(a["query"])), None)
        return _r(ok, f"Opened {site} search for '{a['query']}'.", err)

    def t_play_youtube(self, a):
        q, pick = str(a["query"]), str(a.get("pick") or "1").lower()
        ids = mac.youtube_ids(q)
        if not ids:
            ok, err = mac.open_url(mac.search_url("youtube", q), None)
            return _r(ok, f"Couldn't read results, opened the YouTube search for '{q}'.", err)
        vid = random.choice(ids[:10]) if pick == "random" else ids[min(int(re.sub(r"\D", "", pick) or 1), len(ids)) - 1]
        ok, err = mac.open_url(f"https://www.youtube.com/watch?v={vid}", None)
        return _r(ok, f"Playing a video for '{q}'.", err)

    def t_find_files(self, a):
        self.last_files = mac.find_files(str(a["query"]))
        return "\n".join(f"{i}. {mac.short(f)}" for i, f in enumerate(self.last_files, 1)) or "No matching files."

    def t_open_found_file(self, a):
        i = int(a["number"])
        if not 1 <= i <= len(self.last_files):
            return "No such file number."
        ok, err = mac.open_path(self.last_files[i - 1])
        return _r(ok, f"Opened {mac.short(self.last_files[i - 1])}.", err)

    def t_system_control(self, a):
        act, v = a["action"], str(a.get("value") or "")
        if act == "volume":
            ok, err = mac.set_volume(re.sub(r"\D", "", v) or "50")
            return _r(ok, "Volume set.", err)
        if act in ("mute", "unmute"):
            ok, err = mac.set_mute(act == "mute")
            return _r(ok, "Done.", err)
        if act == "lock":
            ok, err = mac.lock_screen()
            return _r(ok, "Locking.", err)
        if act == "screenshot":
            ok, res = mac.screenshot()
            return _r(ok, f"Saved {mac.short(res)}.", res)
        if act == "battery":
            ok, res = mac.battery()
            return _r(ok, res, res)
        if act == "quit_app":
            ok, res = mac.quit_app(v)
            return _r(ok, f"Quit {res}.", res)
        if act == "type":
            ok, err = mac.type_text(v)
            return _r(ok, "Typed.", err)
        if act == "press":
            ok, err = mac.press(v)
            return _r(ok, "Pressed.", err)
        if act == "check_setup":
            return "\n".join(("OK " if ok else "FIX ") + n + ("" if ok else " - " + fix) for n, ok, fix in mac.diagnose())
        if act == "debug_instagram":
            return mac.instagram_debug()[1]
        return "Unknown action."

    # ---------- code ----------
    def _code_llm(self, prompt):
        return self._write(prompt, 5500)

    def t_build_project(self, a):
        ok, msg, folder = projects.build(self._code_llm, str(a["description"]), a.get("name") or None)
        if ok and folder:
            self.memory.set_pref("last_project", folder)
        return msg

    def t_open_project(self, a):
        folder = self.memory.get_pref("last_project")
        if not folder or not os.path.isdir(folder):
            return "No project built yet."
        path = os.path.join(folder, a.get("file") or "index.html")
        if not os.path.exists(path):
            htmls = [x for x in os.listdir(folder) if x.endswith(".html")]
            if not htmls:
                return f"No HTML file in {folder}."
            path = os.path.join(folder, htmls[0])
        app = mac.find_app(a.get("app") or "Google Chrome")
        ok, err = mac.run(["open", "-a", app, path]) if app else mac.run(["open", path])
        return _r(ok, f"Opened {mac.short(path)}" + (f" in {app}." if app else "."), err)

    def t_open_in_vscode(self, a):
        ok, err = projects.open_in_vscode(os.path.expanduser(str(a["path"])))
        return _r(ok, "Opened in VS Code.", err)

    def t_run_shell(self, a):
        cmd = str(a["command"]).strip()

        def go():
            ok, out = mac.shell(cmd)
            return (out[:1500] or "Done.") if ok else f"Failed: {out}"
        if cmd.split()[:1] and cmd.split()[0] in SAFE_CMDS and SAFE_RE.match(cmd):
            return go()
        self._confirm(go, f"Run this command?\n\n{cmd}")
        return "Waiting for his confirmation."

    def t_run_applescript(self, a):
        code = str(a["code"])

        def go():
            ok, out = mac.osa(code)
            return (out[:1500] or "Done.") if ok else f"Failed: {out}"
        self._confirm(go, f"Run this AppleScript?\n\n{code}")
        return "Waiting for his confirmation."