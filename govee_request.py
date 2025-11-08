import os
import sys
import json

import requests
from dotenv import load_dotenv

# load API key, call Govee devices endpoint, print JSON and save it
load_dotenv()
GOVEE_API_KEY = os.getenv("GOVEE_API_KEY", "").strip()
if not GOVEE_API_KEY:
    print("[ERR] GOVEE_API_KEY missing in .env", file=sys.stderr)
    sys.exit(1)

GOVEE_DEVICES_URL = "https://openapi.api.govee.com/router/api/v1/user/devices"
HEADERS = {
    "Content-Type": "application/json",
    "Govee-API-Key": GOVEE_API_KEY,
}
SESSION = requests.Session()

# Fetch the devices JSON from Govee, print it, and save it to out_path
def fetch_and_save(out_path: str = "devices.json") -> int:
    try:
        resp = SESSION.get(GOVEE_DEVICES_URL, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERR] HTTP request failed: {e}", file=sys.stderr)
        return 2

    # data received from Govee API
    data = resp.json()

    # print the full raw response (formatted)
    try:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        # if response contains non-JSON-serializable stuff, print raw text
        print(resp.text)

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[ERR] Failed to write {out_path}: {e}", file=sys.stderr)
        return 3

    print(f"Wrote response to {out_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(fetch_and_save())