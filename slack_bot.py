"""Slack work bots. One app, one role per channel (#research, #writer, #support...). Runs on your Mac.
pip install slack_bolt ; set SLACK_BOT_TOKEN (xoxb-...) and SLACK_APP_TOKEN (xapp-..., Socket Mode on)."""
import json
import os
import re
import urllib.request

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from core import web

MODEL = os.environ.get("JARVIS_MODEL", "llama3.2:3b")
ROLES = {
    "research": ("You are a research analyst. Use the web results given to answer with sources.", True),
    "writer": ("You are a copywriter. Produce polished, ready-to-use text.", False),
    "support": ("You are a customer support agent. Draft clear, polite, accurate replies.", False),
}
DEFAULT = ("You are a helpful work assistant.", False)
app = App(token=os.environ["SLACK_BOT_TOKEN"])


def llm(system, prompt):
    payload = {"model": MODEL, "stream": False, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode())["message"]["content"].strip()


def answer(text, channel_name):
    try:
        return _answer(text, channel_name)
    except Exception as e:
        return f"Sorry, I hit a problem: {e}. Is Ollama running and is the model installed ({MODEL})?"


def _answer(text, channel_name):
    system, use_web = next((v for k, v in ROLES.items() if k in channel_name), DEFAULT)
    q = re.sub(r"<@\w+>", "", text).strip()
    if use_web:
        q += "\n\nWeb results:\n" + web.search(q)
    return llm(system, q)


@app.event("app_mention")
def mention(event, say, client):
    name = client.conversations_info(channel=event["channel"])["channel"].get("name", "")
    say(text=answer(event["text"], name), thread_ts=event.get("ts"))


@app.event("message")
def dm(event, say):
    if event.get("channel_type") == "im" and not event.get("bot_id"):
        say(answer(event.get("text", ""), "dm"))


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()