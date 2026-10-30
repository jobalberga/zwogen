#!/usr/bin/env python3
"""Test one VW login in Cloud Shell and report only safe diagnostic fields."""

import argparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import logging
from pathlib import Path
import re
import signal
import subprocess
import sys
import traceback
from urllib.parse import urlsplit
import venv

ROOT = Path(__file__).resolve().parents[1]


def login_requirements():
    names = {"carconnectivity", "carconnectivity-connector-volkswagen"}
    return [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines()
            if line.partition("==")[0] in names]


def ensure_environment(project):
    requirements = login_requirements()
    try:
        ready = all(importlib.metadata.version(item.split("==")[0]) == item.split("==")[1]
                    for item in requirements)
    except importlib.metadata.PackageNotFoundError:
        ready = False
    if ready:
        return None
    fingerprint = hashlib.sha256("\n".join(requirements).encode()).hexdigest()[:12]
    directory = Path.home() / ".cache" / "passat-vw-diagnose" / fingerprint
    python = directory / "bin" / "python"
    print("Diagnoseomgeving voorbereiden met dezelfde VW-bibliotheek als de website...", flush=True)
    venv.EnvBuilder(with_pip=True).create(directory)
    subprocess.run([str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                    "--only-binary=:all:", *requirements], check=True)
    return subprocess.run([str(python), str(Path(__file__).resolve()), project], check=False).returncode


def read_credentials(project):
    result = subprocess.run([
        "gcloud", "secrets", "versions", "access", "latest", "--secret=passat-vw", "--project=" + project,
    ], text=True, capture_output=True, check=True)
    config = json.loads(result.stdout)
    if not isinstance(config, dict) or any(not isinstance(config.get(key), str) or not config[key]
                                           for key in ("username", "password")):
        raise ValueError("Incomplete credentials")
    return {key: config[key] for key in ("username", "password")}


def response_step(response, **_):
    url = urlsplit(response.url)
    if url.hostname == "emea.bff.cariad.digital":
        return "VW-aanmeldadres" if url.path == "/user-login/v1/authorize" else "VW-tokens"
    if url.hostname == "identity.vwgroup.io":
        return "VW-identiteit"
    return "Andere aanmeldstap"


def safe_failure(error):
    known_types = {"AuthenticationError", "TemporaryAuthenticationError", "APICompatibilityError",
                   "RetrievalError", "ConnectionError", "ReadTimeout", "Timeout", "TimeoutError", "SSLError",
                   "InvalidGrantError", "InvalidClientError", "InvalidRequestError"}
    kind = type(error).__name__
    origin = "onbekende locatie"
    for frame in traceback.extract_tb(error.__traceback__):
        name = Path(frame.filename).name
        if name in {"vw_web_session.py", "we_connect_session.py", "openid_session.py"}:
            origin = f"{name}:{frame.lineno}"
    # No exception text, source lines, URLs, bodies, headers or local variables.
    return {"type": kind if kind in known_types else "Overige fout", "origin": origin}


def make_session(config):
    from carconnectivity_connectors.volkswagen.auth.session_manager import SessionUser
    from carconnectivity_connectors.volkswagen.auth.we_connect_session import WeConnectSession
    return WeConnectSession(session_user=SessionUser(config["username"], config["password"]), cache={}, timeout=20)


def probe(config, session_factory=make_session):
    steps = []
    previous_logging = logging.root.manager.disable
    previous_alarm = signal.getsignal(signal.SIGALRM)
    session = None

    def expired(*_):
        raise TimeoutError()

    def observe(response, **_):
        if len(steps) < 30:
            steps.append({"step": response_step(response), "status": int(response.status_code),
                          "redirect": bool(response.headers.get("Location"))})

    # The connector can log provider responses. Discard them, including prints,
    # even if authentication fails; only fields constructed above leave here.
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            signal.signal(signal.SIGALRM, expired)
            signal.setitimer(signal.ITIMER_REAL, 90)
            try:
                session = session_factory(config)
                session.hooks.setdefault("response", []).append(observe)
                session.websession.hooks.setdefault("response", []).append(observe)
                # One fresh login. No token cache, vehicle queries or commands.
                session.login()
                failure = None
            except Exception as error:
                failure = safe_failure(error)
            finally:
                if session is not None:
                    session.websession.close()
                    session.close()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_alarm)
        logging.disable(previous_logging)
    return {"steps": steps, "failure": failure}


def print_report(report):
    print("\nVW-DIAGNOSE (Cloud Shell)")
    for index, step in enumerate(report["steps"], 1):
        redirect = "ja" if step["redirect"] else "nee"
        print(f'{index}. {step["step"]}: HTTP {step["status"]}; doorverwijzing={redirect}')
    failure = report["failure"]
    if failure:
        print(f'Uitkomst: {failure["type"]}; bron={failure["origin"]}')
    else:
        print("Uitkomst: aanmelden met de opgeslagen gegevens lukt vanuit Cloud Shell.")
        print("Een verschil met Cloud Run vraagt controle van de sessieopslag of het netwerk daar.")
    print("EINDE VW-DIAGNOSE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project_id):
        parser.error("Gebruik de project-ID.")
    status = ensure_environment(args.project_id)
    if status is not None:
        return status
    print("Opgeslagen VW-gegevens lezen en één aanmelding controleren...", flush=True)
    config = read_credentials(args.project_id)
    report = probe(config)
    print_report(report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt):
        # Also suppress credential-bearing exceptions during setup or cleanup.
        raise SystemExit("Diagnose gestopt. Controleer Cloud Shell-toegang, Secret Manager-rechten en de pakketinstallatie. "
                         "Er worden geen geheime gegevens getoond.") from None
