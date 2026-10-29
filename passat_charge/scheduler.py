"""Durable, single-vehicle one-shot scheduling; all timestamps are UTC epochs."""

import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .vehicle import Snapshot, VehicleError

ACTIVE = ("pending_stop", "confirm_stop", "scheduled", "pending_start", "confirm_start")
POLL_SECONDS = 180
CONFIRM_SECONDS = 600
MAX_ATTEMPTS = 3
ZONE = ZoneInfo("Europe/Amsterdam")


class PlanError(Exception):
    pass


def next_midnight(now):
    local = datetime.fromtimestamp(now, ZONE)
    # Advance the local calendar date, not a fixed number of seconds: a day
    # around the DST transition can contain 23 or 25 hours.
    return (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class Scheduler:
    def __init__(self, database, vehicle, clock=time.time):
        self.database = str(database)
        self.vehicle = vehicle
        self.clock = clock
        self.lock = threading.Lock()
        self.snapshot = Snapshot()
        self.last_refresh = None
        self.last_heartbeat = None
        self.stop_event = threading.Event()
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY, due REAL NOT NULL, deadline REAL NOT NULL,
                    state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    command_at REAL, next_action REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, error TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_plan ON plans ((1))
                    WHERE state IN ('pending_stop', 'confirm_stop', 'scheduled', 'pending_start', 'confirm_start');
                CREATE TABLE IF NOT EXISTS login_attempts (bucket TEXT NOT NULL, at REAL NOT NULL);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def latest(self):
        with self.db() as db:
            row = db.execute("SELECT * FROM plans ORDER BY created DESC, rowid DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def _update(self, plan, state=None, **fields):
        if state is not None:
            fields["state"] = state
        fields["updated"] = self.clock()
        with self.db() as db:
            db.execute("UPDATE plans SET " + ", ".join(key + "=?" for key in fields) + " WHERE id=?",
                       [*fields.values(), plan["id"]])
        plan.update(fields)

    def _acquire(self):
        if not self.lock.acquire(blocking=False):
            raise PlanError("De auto verwerkt nog een opdracht. Probeer het zo nog eens.")

    def arm(self):
        self._acquire()
        try:
            now = self.clock()
            if not self.vehicle.configured:
                raise PlanError("Koppel eerst je Volkswagen voordat je laden inplant.")
            if self.last_heartbeat is None or now - self.last_heartbeat > 60:
                raise PlanError("De planner is nog niet actief. Probeer het zo nog eens.")
            snapshot = self.snapshot
            if not snapshot.available or self.last_refresh is None or now - self.last_refresh > 300:
                raise PlanError("Wacht tot de laadstatus van Volkswagen beschikbaar is.")
            if snapshot.plugged is not True:
                raise PlanError("Sluit eerst de laadkabel aan en wacht op bevestiging van de auto.")
            if snapshot.measured_at is None or not -60 <= now - snapshot.measured_at <= 900:
                raise PlanError("De laadstatus is te oud. Open de VW-app om de auto te verversen.")
            due = next_midnight(now)
            with self.db() as db:
                try:
                    db.execute("""INSERT INTO plans (id, due, deadline, state, created, updated)
                                  VALUES (?, ?, ?, ?, ?, ?)""",
                               (str(uuid.uuid4()), due, due + 3600,
                                "pending_stop", now, now))
                except sqlite3.IntegrityError:
                    raise PlanError("Er staat al een eenmalige laadopdracht klaar.") from None
            return self.latest()
        finally:
            self.lock.release()

    def cancel(self, plan_id):
        self._acquire()
        try:
            plan = self.latest()
            if plan is None or plan["id"] != plan_id or plan["state"] not in ACTIVE:
                raise PlanError("Deze planning is niet meer actief. Ververs de pagina.")
            self._update(plan, "cancelled", error=None)
            return plan
        finally:
            self.lock.release()

    def status(self):
        now = self.clock()
        worker_ok = self.last_heartbeat is not None and now - self.last_heartbeat < 60
        return {
            "now": now, "target": next_midnight(now), "timezone": "Europe/Amsterdam",
            "configured": self.vehicle.configured, "worker_ok": worker_ok,
            "busy": self.lock.locked(), "vehicle": self.snapshot.to_dict(),
            "last_refresh": self.last_refresh, "plan": self.latest(),
        }

    def _refresh(self, now):
        try:
            self.snapshot = self.vehicle.refresh()
        except VehicleError as error:
            self.snapshot = replace(self.snapshot, available=False, message=str(error))
        self.last_refresh = now

    def tick(self):
        with self.lock:
            self.last_heartbeat = self.clock()
            if not self.vehicle.configured:
                return
            now = self.clock()
            if self.last_refresh is None or now - self.last_refresh >= POLL_SECONDS:
                self._refresh(now)
            # Time may advance considerably during an authentication or HTTP call.
            now = self.clock()
            plan = self.latest()
            if plan is None or plan["state"] not in ACTIVE:
                return
            if now > plan["deadline"]:
                self._update(plan, "expired", error="Het startvenster is voorbij. Er wordt niet alsnog of morgen gestart.")
                return
            if plan["state"] in ("pending_stop", "confirm_stop", "scheduled") and now >= plan["due"]:
                self._update(plan, "pending_start", attempts=0, next_action=0, error=None)

            # Only a measurement newer than the command can confirm it.
            confirmed = (self.snapshot.available and self.snapshot.measured_at is not None
                         and plan["command_at"] is not None
                         and self.snapshot.measured_at <= now + 60
                         and self.snapshot.measured_at > plan["command_at"])
            if plan["state"] == "confirm_stop":
                if confirmed and self.snapshot.charging is False:
                    self._update(plan, "scheduled", error=None)
                elif now - plan["command_at"] >= CONFIRM_SECONDS:
                    self._update(plan, "failed", error="VW bevestigt het pauzeren niet. Er is geen automatische start meer gepland. Controleer de VW-app.")
                return
            if plan["state"] == "confirm_start":
                if confirmed and self.snapshot.charging is True:
                    self._update(plan, "started", error=None)
                elif now - plan["command_at"] >= CONFIRM_SECONDS:
                    self._update(plan, "failed", error="De startopdracht is verzonden, maar de auto bevestigt het laden niet. Controleer de VW-app.")
                return
            if plan["state"] == "scheduled":
                # Detect charging resumed by another timer or replugging. This
                # is monitoring, not a physical guarantee when the car is offline.
                if (self.snapshot.available and self.snapshot.charging is True
                        and self.snapshot.measured_at is not None
                        and self.snapshot.measured_at > plan["updated"]):
                    self._update(plan, "pending_stop", attempts=0, next_action=0)
                else:
                    return
            if plan["state"] not in ("pending_stop", "pending_start") or now < plan["next_action"]:
                return
            action = "stop" if plan["state"] == "pending_stop" else "start"
            if plan["attempts"] >= MAX_ATTEMPTS:
                self._update(plan, "failed", error="Het maximale aantal pogingen is bereikt. Controleer de laadstatus in de VW-app.")
                return
            # Persist command intent before sending. Recovery may re-send the
            # same idempotent start/stop action; never a toggle.
            attempts = plan["attempts"] + 1
            self._update(plan, attempts=attempts, command_at=now, next_action=now + POLL_SECONDS)
            try:
                if not self.snapshot.available:
                    raise VehicleError("Volkswagen is niet bereikbaar. De opdracht wordt opnieuw geprobeerd.")
                if action == "start" and self.snapshot.plugged is False:
                    raise VehicleError("De laadkabel is niet aangesloten. Sluit hem opnieuw aan.")
                self.vehicle.command(action)
                self._update(plan, "confirm_" + action, error=None)
            except VehicleError as error:
                if attempts >= MAX_ATTEMPTS:
                    self._update(plan, "failed", error=str(error) + " Controleer de VW-app; automatisch proberen is gestopt.")
                else:
                    self._update(plan, error=str(error))

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as error:
                # Provider exception strings can contain sensitive responses.
                logging.error("Planner iteration failed (%s)", type(error).__name__)
            self.stop_event.wait(5)
