#!/usr/bin/env python3
import os
import time
import json
import sys
from typing import List, Tuple

import requests
import serial
from serial.serialutil import SerialException
from dotenv import load_dotenv

# -------------------- Config loading --------------------
load_dotenv()  # loads .env in current working directory

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM5")
BAUDRATE = int(os.getenv("BAUDRATE", "115200"))
GOVEE_API_KEY = os.getenv("GOVEE_API_KEY", "").strip()
GOVEE_DEVICES_RAW = os.getenv("GOVEE_DEVICES", "").strip()
COOLDOWN_MS = int(os.getenv("COOLDOWN_MS", "800"))

if not GOVEE_API_KEY:
    print("[ERR] GOVEE_API_KEY missing in .env", file=sys.stderr)
    sys.exit(1)

# -------------------- Govee API --------------------
# Control endpoint used later to send on/off commands
GOVEE_CONTROL_URL = "https://developer-api.govee.com/v1/devices/control"
# Devices list endpoint (used when GOVEE_DEVICES env is empty)
GOVEE_DEVICES_URL = "https://openapi.api.govee.com/router/api/v1/user/devices"
HEADERS = {
    "Content-Type": "application/json",
    "Govee-API-Key": GOVEE_API_KEY,
}
SESSION = requests.Session()

def fetch_devices_from_api() -> List[Tuple[str, str]]:
    # Ask the Govee Open API for the devices and return list of (device_id, model)
    # Returns empty list on network error or unexpected response.
    try:
        resp = SESSION.get(GOVEE_DEVICES_URL, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"[WARN] Could not fetch devices from Govee API: {e}")
        return []

    # Normalize different possible response shapes (see govee_request.py)
    devices_raw = []
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], dict) and "devices" in data["data"]:
            devices_raw = data["data"]["devices"] or []
        elif "devices" in data and isinstance(data["devices"], list):
            devices_raw = data["devices"]
        elif "data" in data and isinstance(data["data"], list):
            devices_raw = data["data"]
        else:
            print(f"[WARN] Unexpected API response shape (dict). Keys: {list(data.keys())}")
            devices_raw = []
    elif isinstance(data, list):
        devices_raw = data
    else:
        print(f"[WARN] Unexpected API response type: {type(data)}")
        devices_raw = []

    out: List[Tuple[str, str]] = []
    for d in devices_raw:
        if not isinstance(d, dict):
            continue
        # Device id key can be 'device', sometimes 'deviceId' in other APIs
        device_id = d.get("device") or d.get("deviceId") or d.get("id")
        model = d.get("model") or d.get("sku") or d.get("productModel") or ""
        if not device_id or not model:
            continue
        out.append((device_id, model))
    return out

# Parse devices helper (from GOVEE_DEVICES env string)
def parse_devices(s: str) -> List[Tuple[str, str]]:
    # Parse GOVEE_DEVICES string of the form
    #   "aa:bb:cc:dd:ee:ff:H6104;11:22:33:44:55:66:H6003"
    # into list of (device_id, model) tuples.
    out: List[Tuple[str, str]] = []
    if not s:
        return out
    for chunk in s.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        # Device IDs are MAC-like (6 bytes -> 6 parts) and last token is the model.
        if len(parts) < 7:
            print(f"[WARN] Skipping malformed device entry: {chunk}")
            continue
        device = ":".join(parts[:6])
        model = parts[6]
        out.append((device, model))
    return out


# Try parse from env first, fallback to API if empty
GOVEE_DEVICES = parse_devices(GOVEE_DEVICES_RAW)
if not GOVEE_DEVICES:
    print("[INFO] GOVEE_DEVICES env empty; trying Govee API to discover devices...")
    fetched = fetch_devices_from_api()
    if fetched:
        GOVEE_DEVICES = fetched
        print(f"[INFO] Fetched {len(GOVEE_DEVICES)} devices from API")
    else:
        print("[ERR] GOVEE_DEVICES empty and API fetch failed or returned no devices", file=sys.stderr)
        sys.exit(1)

# Filter devices to only control a specific model to avoid controlling other devices (like TV backlights)
# ALLOWED_MODEL can be set in `.env` (e.g. ALLOWED_MODEL=H6006). If empty, no filtering is applied.
ALLOWED_MODEL = os.getenv("ALLOWED_MODEL", "H6006").strip().upper()
orig_count = len(GOVEE_DEVICES)
if ALLOWED_MODEL:
    GOVEE_DEVICES = [(d, m) for (d, m) in GOVEE_DEVICES if (m or "").upper() == ALLOWED_MODEL]
    if len(GOVEE_DEVICES) < orig_count:
        print(f"[INFO] Filtered devices to only model {ALLOWED_MODEL}: {len(GOVEE_DEVICES)} kept, {orig_count - len(GOVEE_DEVICES)} ignored")
else:
    print("[INFO] ALLOWED_MODEL not set; not filtering devices.")

if not GOVEE_DEVICES:
    # Don't exit here: it's valid to start the bridge without devices configured. The bridge
    # will run, but govee_turn_all() will be a no-op until devices are configured or discovered.
    print(f"[WARN] No devices of model {ALLOWED_MODEL} found. Continuing without devices; bridge will start but won't send Govee commands.", file=sys.stderr)

def govee_turn_all(value: str) -> bool:
    # value can be "on" or "off", sends a command to all configured devices
    # returns True if all succeed
    ok_all = True
    for device, model in GOVEE_DEVICES:
        payload = {
            "device": device,
            "model": model,
            "cmd": {"name": "turn", "value": value}
        }
        try:
            resp = SESSION.put(GOVEE_CONTROL_URL, headers=HEADERS, data=json.dumps(payload), timeout=8)
            if resp.status_code == 200:
                print(f"[OK] {device} ({model}) -> {value.upper()}")
            else:
                ok_all = False
                print(f"[ERR] {device} ({model}) HTTP {resp.status_code}: {resp.text}")
        except requests.RequestException as e:
            ok_all = False
            print(f"[ERR] {device} ({model}) request failed: {e}")
    return ok_all

# Serial listener 
TRIGGER_ON = "LIGHTS_ON"
TRIGGER_OFF = "LIGHTS_OFF"

def normalize_line(b: bytes) -> str:
    # Handle CRLF/CR/UTF-8 issues robustly
    return b.decode("utf-8", errors="ignore").strip()

def main():
    print("[INFO] Starting Govee serial bridge.")
    print(f"[INFO] Serial: {SERIAL_PORT} @ {BAUDRATE}")
    print(f"[INFO] Devices: {', '.join([f'{d}({m})' for d, m in GOVEE_DEVICES])}")
    print("[INFO] Commands: LIGHTS_ON | LIGHTS_OFF")

    lights_on_state = None  # unknown at start; we will still act on commands
    last_action_ms = 0

    while True:
        try:
            with serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1) as ser:
                print("[INFO] Listening...")
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue
                    msg = normalize_line(raw)
                    if not msg:
                        continue

                    now_ms = int(time.time() * 1000)
                    # Cooldown to avoid rapid duplicates (optional)
                    if COOLDOWN_MS > 0 and (now_ms - last_action_ms) < COOLDOWN_MS:
                        # still print for debug but skip action
                        print(f"[SKIP] {msg} (cooldown)")
                        continue

                    if msg == TRIGGER_ON:
                        govee_turn_all("on")
                        lights_on_state = True
                        last_action_ms = now_ms
                    elif msg == TRIGGER_OFF:
                        govee_turn_all("off")
                        lights_on_state = False
                        last_action_ms = now_ms
                    else:
                        # can also pipe raw distance text here
                        print(f"[UART] {msg}")

        except SerialException as e:
            print(f"[WARN] Serial error: {e}. Reconnecting in 3s...")
            time.sleep(3)
        except KeyboardInterrupt:
            print("\n[INFO] Exiting.")
            break

if __name__ == "__main__":
    main()