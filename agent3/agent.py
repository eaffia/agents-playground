import os
import time
import hashlib
import requests
from openai import OpenAI

INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "14400"))

RAW_URLS = os.getenv("CHECK_URLS", "").strip()
if not RAW_URLS:
    single = os.getenv("CHECK_URL", "https://example.com").strip()
    URLS = [single]
else:
    URLS = [u.strip() for u in RAW_URLS.split(",") if u.strip()]

API_KEY = os.getenv("OPENAI_API_KEY", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = OpenAI(api_key=API_KEY) if API_KEY else None

# Per-URL memory
last_hash = {}     # url -> content hash
last_status = {}   # url -> last HTTP status (int)
baseline_set = set()

HEADERS = {"User-Agent": "AMC-Monitor/1.0"}  # polite + consistent

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

def should_alert(url: str, status_code: int, changed: bool) -> bool:
    # On first-ever check:
    # - if status is non-200, alert (useful)
    # - if status is 200, do NOT alert (avoid noise)
    if url not in baseline_set:
        baseline_set.add(url)
        return status_code != 200

    # After baseline: alert only on status change OR content change
    prev_status = last_status.get(url)
    if prev_status is not None and status_code != prev_status:
        return True

    if status_code == 200 and changed:
        return True

    return False

def check_once(url: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    try:
        r = requests.get(url, timeout=25, headers=HEADERS)
        text = r.text or ""
        h = sha(text)
        changed = (url in last_hash and last_hash[url] != h)

        alert = should_alert(url, r.status_code, changed)

        # update memory AFTER decision (but still same cycle)
        last_hash[url] = h
        last_status[url] = r.status_code

        snippet = text[:500].replace("\n", " ").strip()

        if alert:
            if client:
                summary = ai_summary(url, r.status_code, changed, snippet)
            else:
                summary = f"ALERT {url}\nstatus={r.status_code} changed={changed}"

            msg = f"{ts} UTC\n{summary}"
            log(msg)
            send_telegram(msg)
        else:
            log(f"{ts} UTC OK | {url} | status={r.status_code} changed={changed}")

    except Exception as e:
        # Only alert on error state change (avoid spam if DNS is down for hours)
        prev_status = last_status.get(url)
        last_status[url] = -1  # represent "error"
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        msg = f"{ts} UTC ERROR | {url}\n{type(e).__name__}: {e}"

        # baseline: alert once if first check fails
        if url not in baseline_set:
            baseline_set.add(url)
            log(msg)
            send_telegram(msg)
            return

        # alert only if we weren't already in error previously
        if prev_status != -1:
            log(msg)
            send_telegram(msg)
        else:
            log(f"{ts} UTC still ERROR (suppressed repeat) | {url}")

def main():
    log(f"agent3 starting: {len(URLS)} urls | interval={INTERVAL}s")
    if not URLS:
        log("ERROR: No URLs configured. Set CHECK_URLS in .env")
        return

    while True:
        for url in URLS:
            check_once(url)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
