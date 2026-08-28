"""
airport_wx.py

Look up current METAR, TAF, and D-ATIS (Digital ATIS) for any airport.

Data sources:
  - METAR / TAF : aviationweather.gov Data API  (https://aviationweather.gov/data/api/)
  - D-ATIS      : datis.clowd.io public D-ATIS mirror (https://datis.clowd.io/)
    (D-ATIS is only broadcast at larger/towered airports that have the
     digital ATIS system installed -- smaller fields simply won't have one.)

Usage:
  python3 airport_wx.py
  Then just type the airport code(s) when prompted, e.g.:
    Enter airport code(s): KJFK
    Enter airport code(s): jfk atl mco

Accepts either a 4-letter ICAO code (KJFK, EGLL, KATL) or a bare 3-letter
US identifier (JFK, ATL, MCO) -- 3-letter US codes are automatically
prefixed with "K" to form the ICAO identifier.
"""

import json
import platform
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request

METAR_URL = "https://aviationweather.gov/api/data/metar"
TAF_URL = "https://aviationweather.gov/api/data/taf"
DATIS_URL = "https://datis.clowd.io/api/{icao}"

HEADERS = {"User-Agent": "airport-wx-lookup/1.0 (personal use)"}
TIMEOUT = 10


def _macos_keychain_pem() -> str:
    """Export certificates trusted in the macOS System keychains as PEM text.

    Corporate laptops, VPN clients, and security software often install a
    custom root certificate into the *system* trust store (used by Safari,
    Chrome, etc.) without it ever reaching Python's own bundled CA list.
    That mismatch is exactly what produces a
    "self-signed certificate in certificate chain" error. Pulling those
    certs in directly, straight from macOS, fixes it without needing any
    internet access or extra packages.
    """
    keychains = [
        "/Library/Keychains/System.keychain",
        "/System/Library/Keychains/SystemRootCertificates.keychain",
    ]
    pem_chunks = []
    for keychain in keychains:
        try:
            result = subprocess.run(
                ["security", "find-certificate", "-a", "-p", keychain],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.stdout:
                pem_chunks.append(result.stdout)
        except Exception:
            pass
    return "\n".join(pem_chunks)


def _build_ssl_context() -> ssl.SSLContext:
    """Default trust store, extended with the macOS system trust store on Mac."""
    ctx = ssl.create_default_context()
    if platform.system() == "Darwin":
        pem = _macos_keychain_pem()
        if pem:
            try:
                ctx.load_verify_locations(cadata=pem)
            except ssl.SSLError:
                pass
    return ctx


_SSL_CONTEXT = _build_ssl_context()


def _get(url: str, params: dict | None = None):
    """Simple GET helper using only the standard library.

    Returns (status_code, text). Raises urllib.error.URLError on
    connection-level failures (no internet, DNS, etc.).
    """
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL_CONTEXT) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def normalize_icao(code: str) -> str:
    """Turn user input into a best-guess ICAO identifier."""
    code = code.strip().upper()
    if len(code) == 3:
        # Bare 3-letter US identifiers map to K-prefixed ICAO codes
        # (e.g. JFK -> KJFK, ATL -> KATL, MCO -> KMCO).
        return "K" + code
    return code


def get_metar(icao: str) -> str:
    try:
        status, text = _get(METAR_URL, {"ids": icao, "format": "raw"})
        text = text.strip()
        if status >= 400 or not text:
            return "No METAR available for this station."
        return text
    except urllib.error.URLError as exc:
        return f"Error fetching METAR: {exc}"


def get_taf(icao: str) -> str:
    try:
        status, text = _get(TAF_URL, {"ids": icao, "format": "raw"})
        text = text.strip()
        if status >= 400 or not text:
            return "No TAF available for this station."
        return text
    except urllib.error.URLError as exc:
        return f"Error fetching TAF: {exc}"


def get_datis(icao: str):
    """Return a list of D-ATIS text blocks (combined, or separate arrival/departure)."""
    try:
        status, text = _get(DATIS_URL.format(icao=icao))
        if status == 404:
            return ["No D-ATIS available for this station."]
        if status >= 400:
            return [f"Error fetching D-ATIS: HTTP {status}"]
        data = json.loads(text) if text else None
        if not data:
            return ["No D-ATIS available for this station."]
        blocks = []
        for entry in data:
            atype = entry.get("type", "").upper()
            code = entry.get("code", "")
            atis_text = entry.get("datis", "").strip()
            label = f"{atype} ATIS {code}".strip()
            blocks.append(f"[{label}]\n{atis_text}" if atis_text else f"[{label}] (empty)")
        return blocks
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        return [f"Error fetching D-ATIS: {exc}"]


def report(airport_code: str) -> None:
    icao = normalize_icao(airport_code)
    print("=" * 70)
    print(f"WEATHER BRIEFING: {icao}")
    print("=" * 70)

    print("\n--- METAR ---")
    print(get_metar(icao))

    print("\n--- TAF ---")
    print(get_taf(icao))

    print("\n--- D-ATIS ---")
    for block in get_datis(icao):
        print(block)
    print()


def main():
    while True:
        raw = input(
            "Enter airport code(s) (ICAO or 3-letter, space-separated), "
            "or 'q' to quit: "
        ).strip()

        if not raw:
            print("No airport code entered. Try again.")
            continue

        if raw.lower() in ("q", "quit", "exit"):
            break

        codes = raw.split()
        for code in codes:
            report(code)


if __name__ == "__main__":
    main()
