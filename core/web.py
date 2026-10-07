"""Live web access: search, read pages, Wikipedia, research, and nearby places (OpenStreetMap, cached). No API keys."""
import html
import json
import math
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) JARVIS/3.0"
CACHE = os.path.expanduser("~/.jarvis/places_cache.json")
TTL = 7 * 86400
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]


def _http(url, data=None, timeout=20):
    """GET/POST as text. Falls back to curl (uses macOS certificates) if Python's SSL fails."""
    try:
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "en,ar;q=0.8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(2_000_000)
            return raw.decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception as e:
        cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", UA] + (["--data-binary", "@-"] if data is not None else [])
        try:
            p = subprocess.run(cmd + [url], input=data, capture_output=True, timeout=timeout + 5)
        except Exception:
            raise e
        if p.returncode == 0 and p.stdout:
            return p.stdout[:2_000_000].decode("utf-8", "replace")
        raise e


def _clean(s):
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def search(query, n=6):
    try:
        page = _http("https://html.duckduckgo.com/html/", urllib.parse.urlencode({"q": query}).encode())
    except Exception as e:
        return f"Search failed: {e}"
    out = []
    for blk in page.split('class="result results_links')[1:]:
        a = re.search(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>', blk, re.S)
        if not a:
            continue
        s = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', blk, re.S)
        url = a[1]
        m = re.search(r"uddg=([^&]+)", url)
        if m:
            url = urllib.parse.unquote(m[1])
        out.append((_clean(a[2]), url, _clean(s[1]) if s else ""))
        if len(out) >= n:
            break
    if not out:
        return "No results."
    return "\n".join(f"{i}. {t}\n   {u}\n   {s}" for i, (t, u, s) in enumerate(out, 1))


def read_page(url, limit=4500):
    if not url.startswith(("http://", "https://")):
        return "Invalid URL."
    try:
        text = _clean(_http(url))
    except Exception as e:
        return f"Couldn't open the page: {e}"
    return text[:limit] or "The page had no readable text."


def wikipedia(q):
    lang = "ar" if re.search(r"[\u0600-\u06ff]", q) else "en"
    try:
        js = json.loads(_http(f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=1&srsearch="
                              + urllib.parse.quote(q)))
        hits = js["query"]["search"]
        if not hits:
            return ""
        title = hits[0]["title"]
        s = json.loads(_http(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"))))
        return f"Wikipedia - {s.get('title')}: {s.get('extract', '')[:800]}"
    except Exception:
        return ""


def research(topic):
    """Wikipedia + web + news + the top page, in one call. Public information only."""
    parts = []
    w = wikipedia(topic)
    if w:
        parts.append(w)
    found = search(topic, 5)
    parts.append("Web results:\n" + found)
    parts.append("News results:\n" + search(topic + " news", 3))
    urls = re.findall(r"\n   (https?://\S+)", found)
    if urls:
        parts.append(f"Top page {urls[0]}:\n" + read_page(urls[0], 1000))
    return "\n\n".join(parts)[:3400]


def geocode(address):
    try:
        data = json.loads(_http("https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + urllib.parse.quote(address)))
        return (float(data[0]["lat"]), float(data[0]["lon"])) if data else None
    except Exception:
        return None


KINDS = {
    "restaurant": '["amenity"="restaurant"]', "cafe": '["amenity"="cafe"]', "coffee": '["amenity"="cafe"]',
    "fast food": '["amenity"="fast_food"]', "pharmacy": '["amenity"="pharmacy"]',
    "hospital": '["amenity"="hospital"]', "atm": '["amenity"="atm"]', "bank": '["amenity"="bank"]',
    "gas": '["amenity"="fuel"]', "petrol": '["amenity"="fuel"]', "fuel": '["amenity"="fuel"]',
    "supermarket": '["shop"="supermarket"]', "grocery": '["shop"="supermarket"]',
    "mosque": '["amenity"="place_of_worship"]["religion"="muslim"]', "hotel": '["tourism"="hotel"]',
    "mall": '["shop"="mall"]', "bakery": '["shop"="bakery"]', "gym": '["leisure"="fitness_centre"]',
    "barber": '["shop"="hairdresser"]', "salon": '["shop"="hairdresser"]', "clinic": '["amenity"="clinic"]',
}


def _dist(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


def _cache():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except Exception:
        return {}


def place_data(kind, lat, lon, radius):
    """Returns (items, from_cache, error). Cached for a week so repeat questions are instant."""
    key = f"{kind.lower().strip()}|{round(lat, 3)}|{round(lon, 3)}|{radius}"
    c = _cache()
    hit = c.get(key)
    if hit and time.time() - hit["t"] < TTL:
        return hit["items"], True, None
    k = kind.lower().strip()
    flt = next((v for key_, v in KINDS.items() if key_ in k), f'["amenity"="{re.sub(r"[^a-z]+", "_", k).strip("_")}"]')
    q = urllib.parse.urlencode({"data": f"[out:json][timeout:25];nwr{flt}(around:{radius},{lat},{lon});out center tags 500;"}).encode()
    data, err = None, None
    for url in OVERPASS:
        try:
            data = json.loads(_http(url, q, 40))
            break
        except Exception as e:
            err = e
    if data is None:
        return None, False, f"Places lookup failed: {err}"
    items = []
    for e in data.get("elements", []):
        la = e.get("lat") or e.get("center", {}).get("lat")
        lo = e.get("lon") or e.get("center", {}).get("lon")
        if la is None or lo is None:
            continue
        t = e.get("tags", {})
        items.append({"n": t.get("name") or t.get("name:en") or "(unnamed)", "c": t.get("cuisine", ""),
                      "d": int(_dist(lat, lon, la, lo)), "la": la, "lo": lo,
                      "w": bool(t.get("website") or t.get("contact:website") or t.get("url"))})
    items.sort(key=lambda i: i["d"])
    c[key] = {"t": time.time(), "items": items}
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w") as f:
            json.dump(c, f)
    except OSError:
        pass
    return items, False, None


def places(kind, lat, lon, radius=3000, no_website=False):
    items, cached, err = place_data(kind, lat, lon, radius)
    if err:
        return err
    if not items:
        return f"No {kind} found within {radius} m in OpenStreetMap (coverage can be incomplete; try a web search too)."
    nw = [i for i in items if not i["w"]]
    pool = nw if no_website else items
    lines = [f"{n}. {i['n']}{' (' + i['c'] + ')' if i['c'] else ''} - {i['d']} m - https://maps.google.com/?q={i['la']},{i['lo']}"
             for n, i in enumerate(pool[:8], 1)]
    return (f"{len(items)} {kind} within {radius} m; {len(nw)} have no website listed in OpenStreetMap "
            f"({'saved' if cached else 'live'} data; a missing website tag often just means nobody added it). "
            + ("Nearest without a website:\n" if no_website else "Nearest:\n") + "\n".join(lines))