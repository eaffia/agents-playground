import os
import time
import hashlib
import requests
from openai import OpenAI

INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))

# Multi-URL support
RAW_URLS = os.getenv("CHECK_URLS", "").strip()
if not RAW_URLS:
    # Backwards compatibility if you still have CHECK_URL
    single = os.getenv("CHECK_URL", "https://example.com").strip()
    URLS = [single]
else:
    URLS = [u.strip() for u in RAW_URLS.split(",") if u.strip()]

API_KEY = os.getenv("OPENAI_API_KEY", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = OpenAI(api_key=API_KEY) if API_KEY else None

# Track page hashes per URL
last_hash = {}

def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

def send_telegram(message: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

def ai_summary(url: str, status_code: int, changed: bool, snippet: str) -> str:
    prompt = f"""
You are a monitoring assistant.

URL: {url}
HTTP status: {status_code}
Changed since last check: {changed}

Snippet:
{snippet}

Write:
1) One-line status
2) 2-4 concise bullets (what changed OR likely cause + next step)
Keep it concise.
""".strip()

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
    )
    return resp.output_text.strip()

def log(line: str):
    print(line, flush=True)

def check_once(url: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    try:
        r = requests.get(url, timeout=20)
        text = r.text or ""
        h = sha(text)
        changed = (url in last_hash and last_hash[url] != h)
        last_hash[url] = h

        snippet = text[:500].replace("\n", " ").strip()

        if r.status_code != 200 or changed:
            if client:
                summary = ai_summary(url, r.status_code, changed, snippet)
            else:
                summary = f"ALERT {url} status={r.status_code} changed={changed}"

            msg = f"{ts} UTC\n{summary}"
            log(msg)
            send_telegram(msg)
        else:
            log(f"{ts} UTC OK 200 no change | {url}")

    except Exception as e:
        msg = f"{ts} UTC ERROR | {url}\n{type(e).__name__}: {e}"
        log(msg)
        send_telegram(msg)

def main():
    log(f"agent3 starting: {len(URLS)} urls | interval={INTERVAL}s")
    if not API_KEY:
        log("WARNING: OPENAI_API_KEY not set. Will send basic alerts only.")
    if not URLS:
        log("ERROR: No URLs configured. Set CHECK_URLS in .env")
        return

    while True:
        for url in URLS:
            check_once(url)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
