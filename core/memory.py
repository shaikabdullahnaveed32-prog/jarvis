"""Permanent memory: SQLite on disk. Nothing is ever auto-deleted."""
import os
import re
import sqlite3
import threading
import time

DB = os.path.expanduser(os.environ.get("JARVIS_DB", "~/.jarvis/memory.db"))
_W = re.compile(r"[a-z0-9\u0600-\u06ff]{3,}")


class Memory:
    def __init__(self):
        os.makedirs(os.path.dirname(DB), exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(DB, check_same_thread=False)
        self.db.executescript("""
            create table if not exists facts(id integer primary key, text text unique, ts real);
            create table if not exists chat(id integer primary key, role text, text text, ts real);
            create table if not exists prefs(key text primary key, value text);
            create table if not exists contacts(name text primary key, phone text);
        """)
        self.db.commit()

    def _run(self, sql, args=()):
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
            self.db.commit()
            return rows

    # facts
    def add_fact(self, text):
        text = text.strip()[:300]
        if text:
            self._run("insert or ignore into facts(text, ts) values(?, ?)", (text, time.time()))

    def facts(self, n=10):
        return [r[0] for r in self._run("select text from facts order by ts desc limit ?", (n,))]

    def relevant(self, query, k=10):
        q = set(_W.findall(query.lower()))
        rows = self._run("select text, ts from facts")
        scored = sorted(rows, key=lambda r: (len(q & set(_W.findall(r[0].lower()))), r[1]), reverse=True)
        hits = [r[0] for r in scored if q & set(_W.findall(r[0].lower()))][:k]
        recent = [r[0] for r in sorted(rows, key=lambda r: r[1], reverse=True)[:4]]
        return list(dict.fromkeys(hits + recent))[:k]

    # chat log
    def add_chat(self, role, text):
        self._run("insert into chat(role, text, ts) values(?, ?, ?)", (role, text, time.time()))

    def recent_chat(self, n=8):
        rows = self._run("select role, text from chat order by id desc limit ?", (n,))
        return [{"role": r, "content": t} for r, t in reversed(rows)]

    # settings
    def set_pref(self, key, value):
        self._run("insert or replace into prefs(key, value) values(?, ?)", (key, value))

    def get_pref(self, key):
        rows = self._run("select value from prefs where key=?", (key,))
        return rows[0][0] if rows else None

    # contacts
    def save_contact(self, name, phone):
        self._run("insert or replace into contacts(name, phone) values(?, ?)", (name.strip().lower(), phone.strip()))

    def find_contact(self, name):
        name = name.strip().lower()
        rows = self._run("select name, phone from contacts")
        for n, p in rows:
            if n == name:
                return n, p
        for n, p in rows:
            if name in n or n in name:
                return n, p
        return None