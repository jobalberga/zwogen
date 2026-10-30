#!/usr/bin/env python3
"""Read Smartcar v3 connection permissions and three charging signals."""

from datetime import datetime, timezone
import getpass
import json
import math
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

TOKEN_URL = "https://iam.smartcar.com/oauth2/token"
API_URL = "https://vehicle.api.smartcar.com/v3"
PERMISSIONS = ("read_battery", "read_charge", "control_charge")
SIGNALS = {
    "tractionbattery-stateofcharge": ("Accu", "read_battery"),
    "charge-detailedchargingstatus": ("Laadstatus", "read_charge"),
    "charge-ischargingcableconnected": ("Laadkabel", "read_charge"),
}


class CheckError(Exception):
    """Only locally constructed, credential-free text may be used here."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(opener, url, *, headers=None, data=None):
    # The only POST permitted by this diagnostic is the token exchange. No
    # vehicle commands or server-provided redirect/pagination URLs are followed.
    if data is not None and url != TOKEN_URL:
        raise CheckError("Alleen de aanmelding mag een POST gebruiken.")
    if not (url == TOKEN_URL or url.startswith(API_URL + "/")):
        raise CheckError("Onbekende API-bestemming.")
    request = Request(url, data=json.dumps(data).encode() if data is not None else None,
                      headers={"Accept": "application/json", **(headers or {})})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise CheckError("API-antwoord te groot.")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise CheckError("Onverwacht API-formaat.")
            return value
    except HTTPError as error:
        status = error.code
        error.close()
        raise CheckError(f"HTTP {status}") from None
    except (URLError, TimeoutError, OSError):
        raise CheckError("Netwerkverbinding mislukt.") from None
    except (ValueError, UnicodeError):
        raise CheckError("Onverwacht API-formaat.") from None


def identifier(value):
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise CheckError("Geen geldig voertuig- of gebruikerskenmerk ontvangen.") from None


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def summarize_signal(payload, code):
    signal = payload.get("data", {})
    if not isinstance(signal, dict):
        raise CheckError("Onverwacht signaalformaat.")
    attributes = signal.get("attributes", {})
    if not isinstance(attributes, dict) or attributes.get("code") != code:
        raise CheckError("Ander signaal ontvangen dan gevraagd.")
    status = attributes.get("status", {})
    if not isinstance(status, dict) or status.get("value") != "SUCCESS":
        error = status.get("error", {}) if isinstance(status, dict) else {}
        error_type = error.get("type") if isinstance(error, dict) else None
        allowed = {"PERMISSION", "CAPABILITY", "COMPATIBILITY", "BILLING", "UPSTREAM", "RATE_LIMIT"}
        return {"status": error_type if error_type in allowed else "Niet beschikbaar"}
    body = attributes.get("body", {})
    value = body.get("value") if isinstance(body, dict) else None
    if code == "tractionbattery-stateofcharge":
        safe_value = f"{value:g}%" if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100 else "Onbekend"
    elif code == "charge-ischargingcableconnected":
        safe_value = {True: "Aangesloten", False: "Losgekoppeld"}.get(value, "Onbekend") if type(value) is bool else "Onbekend"
    else:
        statuses = {"CHARGING", "NOT_CHARGING", "FULLY_CHARGED", "COMPLETE", "PAUSED", "SCHEDULED", "ERROR", "UNKNOWN"}
        safe_value = value if isinstance(value, str) and value in statuses else "Onbekend"
    metadata = signal.get("meta", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return {"status": "SUCCESS", "value": safe_value,
            "measured_at": timestamp(metadata.get("oemUpdatedAt")),
            "retrieved_at": timestamp(metadata.get("retrievedAt"))}


def probe(client_id, client_secret, *, opener=None):
    opener = opener or build_opener(NoRedirect())
    report = {"authenticated": False, "live_vehicles": 0, "permissions": {}, "signals": {}}
    try:
        auth = request_json(opener, TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret,
                                                   "grant_type": "client_credentials"})
        token = auth.get("access_token")
        if not isinstance(token, str) or not token or str(auth.get("token_type", "")).lower() != "bearer":
            raise CheckError("Geen bruikbaar toegangstoken ontvangen.")
        report["authenticated"] = True
        headers = {"Authorization": "Bearer " + token}
        query = urlencode({"filter[vehicle.mode]": "live"})
        result = request_json(opener, API_URL + "/connections?" + query, headers=headers)
        rows = result.get("data")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise CheckError("Onverwacht formaat van de autokoppelingen.")
        live = [row for row in rows if row.get("attributes", {}).get("vehicle", {}).get("mode") == "live"]
        report["live_vehicles"] = len(live)
        if len(live) != 1 or result.get("meta", {}).get("totalCount", len(rows)) != 1:
            raise CheckError("De controle vereist precies één gekoppelde echte auto.")
        row = live[0]
        vehicle = identifier(row.get("relationships", {}).get("vehicle", {}).get("data", {}).get("id"))
        user = identifier(row.get("relationships", {}).get("user", {}).get("data", {}).get("id"))
        granted = row.get("attributes", {}).get("permissions")
        if not isinstance(granted, list):
            raise CheckError("De verleende toestemmingen konden niet worden gelezen.")
        report["permissions"] = {name: name in granted for name in PERMISSIONS}
        headers["sc-user-id"] = user
        for code, (_, permission) in SIGNALS.items():
            if not report["permissions"][permission]:
                report["signals"][code] = {"status": "Niet opgevraagd: toestemming ontbreekt"}
                continue
            try:
                payload = request_json(opener, API_URL + f"/vehicles/{vehicle}/signals/{code}", headers=headers)
                report["signals"][code] = summarize_signal(payload, code)
            except CheckError as error:
                report["signals"][code] = {"status": str(error)}
                if str(error) == "HTTP 429":
                    break
    except CheckError as error:
        report["error"] = str(error)
    return report


def print_report(report):
    print("\nSMARTCAR-CONTROLE")
    print("API-aanmelding:", "geslaagd" if report["authenticated"] else "niet geslaagd")
    print("Gekoppelde echte auto's:", report["live_vehicles"])
    for name, granted in report["permissions"].items():
        print("Toestemming " + name + ": " + ("ja" if granted else "nee"))
    for code, result in report["signals"].items():
        label = SIGNALS[code][0]
        print(label + ": " + (result.get("value", "Onbekend") if result["status"] == "SUCCESS" else result["status"]))
        if result.get("measured_at"):
            print("  Tijdstip autometing (UTC): " + result["measured_at"])
        if result.get("retrieved_at"):
            print("  Door Smartcar opgehaald (UTC): " + result["retrieved_at"])
    if report.get("error"):
        print("Uitkomst: " + report["error"])
    print("Laadstart en laadstop zijn niet getest; toestemming bewijst geen werkende bediening of pakketrecht.")
    print("EINDE SMARTCAR-CONTROLE")


def main():
    if not sys.stdin.isatty():
        raise CheckError("Start deze controle rechtstreeks in de Cloud Shell-terminal voor verborgen invoer.")
    print("Leescontrole voor Smartcar. Voer Client ID en Client Secret uitsluitend hier in.")
    client_id = input("Client ID (begint met client_): ").strip()
    if not re.fullmatch(r"client_[A-Za-z0-9_-]{8,150}", client_id):
        raise CheckError("Gebruik de nieuwe Client ID voor M2M, beginnend met client_.")
    client_secret = getpass.getpass("Client Secret (verborgen invoer): ")
    if not client_secret:
        raise CheckError("Client Secret ontbreekt.")
    print_report(probe(client_id, client_secret))


if __name__ == "__main__":
    try:
        main()
    except CheckError as error:
        raise SystemExit(str(error)) from None
    except (Exception, KeyboardInterrupt):
        raise SystemExit("Controle gestopt. Er worden geen sleutels of ruwe providerantwoorden getoond.") from None
