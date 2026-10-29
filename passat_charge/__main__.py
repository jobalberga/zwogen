import fcntl
import logging
import os
import secrets
import threading
from pathlib import Path

from waitress import serve

from .scheduler import Scheduler
from .vehicle import Volkswagen
from .web import create_app


def main():
    os.umask(0o077)
    data = Path(os.environ.get("PASSAT_DATA_DIR", "data")).resolve()
    data.mkdir(parents=True, exist_ok=True)
    # A process-level lock prevents two workers from sending the same job.
    worker_lock = (data / "worker.lock").open("a")
    try:
        fcntl.flock(worker_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Er draait al een planner met deze datamap.") from None
    secret_file = data / "session.key"
    if not secret_file.exists():
        secret_file.write_text(secrets.token_hex(32))
    password = os.environ.get("APP_PASSWORD", "")
    if len(password) < 12:
        raise SystemExit("Stel APP_PASSWORD veilig in (minimaal 12 tekens); gebruik niet je VW-wachtwoord.")
    vehicle = Volkswagen(os.environ.get("VW_USERNAME", ""), os.environ.get("VW_PASSWORD", ""),
                         os.environ.get("VW_VIN", ""), data)
    scheduler = Scheduler(data / "plans.sqlite3", vehicle)
    app = create_app(scheduler, password, secret_file.read_text().strip(),
                     secure_cookies=os.environ.get("COOKIE_SECURE", "1") != "0")
    worker = threading.Thread(target=scheduler.run, name="charging-scheduler", daemon=True)
    worker.start()
    logging.basicConfig(level=logging.WARNING)
    try:
        serve(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")), threads=4)
    finally:
        scheduler.stop_event.set()
        worker.join(timeout=10)
        worker_lock.close()


if __name__ == "__main__":
    main()
