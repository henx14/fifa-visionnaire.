import os, time, json, random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PROXY_LIST = os.getenv("PROXY_LIST", "").split(",") if os.getenv("PROXY_LIST") else []
REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL") or 30)
if REFRESH_INTERVAL < 15:
    REFRESH_INTERVAL = 15

HEADERS_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 12; SM-G991U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117 Mobile Safari/537.36",
]

URL_1XBET_FIFA = "https://1xbet.com/sports/football"
URL_1XBET_GAMES = "https://1xbet.com/games"

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram non configuré. Message :", text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        res = requests.post(url, data=payload, timeout=10)
        if res.status_code != 200:
            print("TG send error", res.status_code, res.text)
    except Exception as e:
        print("TG exception:", e)

def build_session(proxy=None):
    s = requests.Session()
    s.headers.update({"User-Agent": random.choice(HEADERS_POOL)})
    if proxy:
        if not proxy.startswith("http"):
            proxy = "http://" + proxy
        s.proxies.update({"http": proxy, "https": proxy})
    s.timeout = 15
    return s

def get_proxy_round_robin():
    if not PROXY_LIST:
        return None
    return random.choice(PROXY_LIST)

def try_fetch_json_endpoint(session, base_url):
    candidates = [
        urljoin(base_url, "/api/odds"),
        urljoin(base_url, "/api/events"),
        urljoin(base_url, "/line/lineFeed"),
        urljoin(base_url, "/linefeed/linefeed"),
    ]
    for u in candidates:
        try:
            r = session.get(u, timeout=8)
            if r.ok and "json" in r.headers.get("content-type", "").lower():
                try:
                    return r.json()
                except Exception:
                    continue
        except Exception:
            continue
    return None

def parse_fifa_from_html(html_text):
    soup = BeautifulSoup(html_text, "lxml")
    events = []
    for block in soup.find_all(lambda tag: tag.name in ["div","li"] and ("match" in (tag.get("class") or []) or "event" in (tag.get("class") or []))):
        try:
            txt = block.get_text(" ", strip=True)
            if "vs" in txt.lower() or "-" in txt:
                events.append(txt[:200])
        except Exception:
            continue
    if not events:
        teams = soup.find_all("span")
        for i in range(len(teams)-1):
            a = teams[i].get_text(strip=True)
            b = teams[i+1].get_text(strip=True)
            if a and b and len(a) < 30 and len(b) < 30:
                events.append(f"{a} vs {b}")
    seen = []
    for e in events:
        if e not in seen:
            seen.append(e)
    return seen

def collect_fifa_once():
    proxy = get_proxy_round_robin()
    session = build_session(proxy)
    json_data = try_fetch_json_endpoint(session, URL_1XBET_FIFA)
    if json_data:
        return {"type":"json_raw","data": json_data}
    try:
        r = session.get(URL_1XBET_FIFA, timeout=12)
        if r.status_code == 200:
            parsed = parse_fifa_from_html(r.text)
            return {"type":"html","data": parsed}
        else:
            return {"type":"error","data": f"status {r.status_code}"}
    except Exception as e:
        return {"type":"exception","data": str(e)}

def collect_aviator_once():
    proxy = get_proxy_round_robin()
    session = build_session(proxy)
    try:
        r = session.get(URL_1XBET_GAMES, timeout=12)
        if r.status_code == 200:
            text = r.text.lower()
            if "aviator" in text or "crash" in text:
                lines = [ln for ln in text.splitlines() if "aviator" in ln or "crash" in ln]
                return {"type":"html","data": lines[:50]}
            else:
                return {"type":"html","data": ["no-aviator-found"]}
        else:
            return {"type":"error","data": f"status {r.status_code}"}
    except Exception as e:
        return {"type":"exception","data": str(e)}

def run_loop():
    last_sent = {"fifa": None, "aviator": None}
    send_telegram("🚀 FIFA Visionnaire collector démarré (lecture-only).")
    while True:
        try:
            res_fifa = collect_fifa_once()
            key_fifa = json.dumps(res_fifa, default=str)[:3000]
            if key_fifa and key_fifa != last_sent["fifa"]:
                last_sent["fifa"] = key_fifa
                if res_fifa.get("type") == "html":
                    items = res_fifa.get("data")[:10]
                    msg = "⚽️ FIFA - événements détectés :\n" + "\n".join(f"- {i}" for i in items)
                elif res_fifa.get("type") == "json_raw":
                    msg = "⚽️ FIFA - JSON endpoint trouvé (raw sample)."
                else:
                    msg = f"⚽️ FIFA - {res_fifa.get('data')}"
                send_telegram(msg)

            res_avi = collect_aviator_once()
            key_avi = json.dumps(res_avi, default=str)[:3000]
            if key_avi and key_avi != last_sent["aviator"]:
                last_sent["aviator"] = key_avi
                if res_avi.get("type") == "html":
                    items = res_avi.get("data")[:10]
                    msg = "✈️ Aviator - événements / mentions détectés :\n" + "\n".join(f"- {i}" for i in items)
                else:
                    msg = f"✈️ Aviator - {res_avi.get('data')}"
                send_telegram(msg)

        except Exception as e:
            print("Main loop error:", e)
            send_telegram(f"❗Collector error: {e}")

        time.sleep(REFRESH_INTERVAL)

if __name__ == "__main__":
    run_loop()
