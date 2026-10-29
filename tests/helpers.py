import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from passat_charge.scheduler import Scheduler, ZONE
from passat_charge.vehicle import Snapshot, VehicleError


class Clock:
    def __init__(self, local="2026-10-29T16:00:00"):
        self.now = datetime.fromisoformat(local).replace(tzinfo=ZONE).timestamp()

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeVehicle:
    configured = True

    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.refresh_error = False
        self.command_error = False
        self.snapshot = Snapshot(True, True, True, 43, clock(), "Verbonden met Volkswagen")

    def refresh(self):
        if self.refresh_error:
            raise VehicleError("Volkswagen is niet bereikbaar.")
        return self.snapshot

    def command(self, action):
        self.calls.append((action, self.clock()))
        if self.command_error:
            raise VehicleError("Geen bevestiging ontvangen.")

    def measure(self, **changes):
        self.snapshot = replace(self.snapshot, measured_at=self.clock(), **changes)


class Fixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.vehicle = FakeVehicle(self.clock)
        self.database = Path(self.temp.name) / "plans.sqlite3"
        self.scheduler = Scheduler(self.database, self.vehicle, self.clock)
        self.scheduler.tick()

    def paused_plan(self):
        plan = self.scheduler.arm()
        self.scheduler.tick()
        self.clock.advance(180)
        self.vehicle.measure(charging=False)
        self.scheduler.tick()
        return plan
