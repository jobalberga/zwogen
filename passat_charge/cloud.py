"""Durable outbox, bounded execution lease and one-shot cloud scheduling."""

import copy
import time
import uuid
from dataclasses import replace

from .scheduler import ACTIVE, ChargeFlow, PlanError, POLL_SECONDS, next_midnight, next_start
from .vehicle import Snapshot, VehicleError

LEASE_SECONDS = 300
STALE_TASK_SECONDS = 600


class LeaseLost(Exception):
    pass


class Busy(Exception):
    pass


def new_task(due):
    return {"id": uuid.uuid4().hex, "due": due, "published_at": None}


def busy(state, now):
    return bool(state.get("lease") and state["lease"]["until"] > now)


class CloudScheduler:
    def __init__(self, store, queue, clock=time.time):
        self.store, self.queue, self.clock = store, queue, clock

    def healthy(self):
        # Public health probes must never enqueue a vehicle refresh.
        return True

    def allow_login(self, bucket):
        return self.store.allow_login(bucket, self.clock())

    def clear_login(self, bucket):
        self.store.clear_login(bucket)

    def flush(self):
        task = self.store.read()["outbox"]
        if not task or task["published_at"] is not None:
            return
        try:
            self.queue.publish(task)
        except Exception:
            def failed(state):
                if state["outbox"] and state["outbox"]["id"] == task["id"]:
                    state["queue_error"] = "Planning opgeslagen, maar taakdienst niet bereikbaar."
            self.store.mutate(failed)
            raise PlanError("Planning opgeslagen, maar taakdienst niet bereikbaar. Controleer de status.") from None
        def published(state):
            if state["outbox"] and state["outbox"]["id"] == task["id"]:
                state["outbox"]["published_at"] = self.clock()
                state["queue_error"] = None
        self.store.mutate(published)

    def reconcile(self):
        now = self.clock()
        value = self.store.read()
        if not value["outbox"] and not (value["plan"] and value["plan"]["state"] in ACTIVE):
            return
        def repair(state):
            task = state["outbox"]
            plan = state["plan"]
            if plan and plan["state"] in ACTIVE and now > plan["deadline"] and not busy(state, now):
                plan.update(state="expired", updated=now, error="Startvenster verstreken. Er wordt niet meer gestart.")
                state["outbox"], state["lease"], state["queue_error"] = None, None, None
                return
            if task and (not plan or plan["state"] not in ACTIVE) and now - task["due"] > 900 and not busy(state, now):
                state["outbox"], state["lease"] = None, None
                state["queue_error"] = "Laadstatus ophalen mislukt. Ververs de pagina."
                return
            if task and not busy(state, now) and task["due"] < now - STALE_TASK_SECONDS:
                state["outbox"] = new_task(now)
            elif not task and state["plan"] and state["plan"]["state"] in ACTIVE:
                state["outbox"] = new_task(now)
        self.store.mutate(repair)
        self.flush()

    def status(self):
        now = self.clock()
        value = self.store.read()
        changed = False
        if (value["last_refresh"] is None or now - value["last_refresh"] >= POLL_SECONDS) and not value["outbox"]:
            def refresh(state):
                if not state["outbox"] and not busy(state, now):
                    state["outbox"] = new_task(now)
            self.store.mutate(refresh)
            changed = True
        if changed or (value["outbox"] and value["outbox"]["published_at"] is None):
            try:
                self.flush()
            except PlanError:
                pass
            value = self.store.read()
        task = value["outbox"]
        late = task and now - task["due"] > STALE_TASK_SECONDS
        return {"now": now, "target": next_midnight(now), "timezone": "Europe/Amsterdam",
                "start_times": [{"value": time_value, "due": next_start(now, time_value)}
                                for hour in range(24) for minute in (0, 30)
                                for time_value in (f"{hour:02d}:{minute:02d}",)],
                "configured": value["configured"], "worker_ok": not bool(value["queue_error"] or late),
                "busy": busy(value, now), "vehicle": value["snapshot"],
                "last_refresh": value["last_refresh"], "plan": value["plan"]}

    def arm(self, start_time="00:00"):
        now = self.clock()
        due = next_start(now, start_time)
        def create(state):
            if busy(state, now):
                raise PlanError("Er wordt een opdracht verwerkt. Probeer het zo opnieuw.")
            if state["plan"] and state["plan"]["state"] in ACTIVE:
                raise PlanError("Er is al een laadopdracht actief.")
            snapshot = state["snapshot"]
            if not state["configured"] or not snapshot["available"]:
                raise PlanError("Wacht op de Volkswagen-koppeling en laadstatus.")
            if state["last_refresh"] is None or now - state["last_refresh"] > 300:
                raise PlanError("Wacht op een actuele laadstatus.")
            if snapshot["plugged"] is not True:
                raise PlanError("Sluit eerst de laadkabel aan.")
            if snapshot["measured_at"] is None or not -60 <= now - snapshot["measured_at"] <= 900:
                raise PlanError("Laadstatus verouderd. Ververs de auto in de VW-app.")
            state["plan"] = {"id": uuid.uuid4().hex, "due": due, "deadline": due + 3600,
                             "state": "pending_stop", "created": now, "updated": now,
                             "command_at": None, "next_action": 0, "attempts": 0, "error": None}
            state["outbox"] = new_task(now)
            return state["plan"]
        plan = self.store.mutate(create)
        self.flush()
        return plan

    def cancel(self, plan_id):
        now = self.clock()
        def cancel(state):
            if busy(state, now):
                raise PlanError("Er wordt een opdracht verwerkt. Probeer het zo opnieuw.")
            plan = state["plan"]
            if not plan or plan["id"] != plan_id or plan["state"] not in ACTIVE:
                raise PlanError("Planning niet meer actief. Ververs de pagina.")
            plan.update(state="cancelled", updated=now, error=None)
            # Already-delivered task messages become harmless because their
            # identity no longer matches this durable outbox.
            state["outbox"], state["lease"] = None, None
            state["queue_error"] = None
            return plan
        return self.store.mutate(cancel)


class CloudWorker(ChargeFlow):
    def __init__(self, store, scheduler, vehicle, clock=time.time):
        self.store, self.scheduler, self.raw_vehicle, self.clock = store, scheduler, vehicle, clock
        self.task_id = self.owner = None
        self.snapshot = Snapshot()
        worker = self
        class GuardedVehicle:
            def command(self, action):
                state = worker.store.read()
                worker.assert_owner(state)
                plan = state["plan"]
                now = worker.clock()
                if not plan or plan["state"] not in ACTIVE or now > plan["deadline"]:
                    raise LeaseLost()
                if action == "start" and now < plan["due"]:
                    raise LeaseLost()
                worker.raw_vehicle.command(action)
        self.vehicle = GuardedVehicle()

    def assert_owner(self, state):
        lease, task = state["lease"], state["outbox"]
        if not task or task["id"] != self.task_id or not lease or lease["owner"] != self.owner or lease["until"] <= self.clock():
            raise LeaseLost()

    def _update(self, plan, state=None, **fields):
        if state is not None:
            fields["state"] = state
        fields["updated"] = self.clock()
        def update(value):
            self.assert_owner(value)
            if not value["plan"] or value["plan"]["id"] != plan["id"]:
                raise LeaseLost()
            value["plan"].update(fields)
        self.store.mutate(update)
        plan.update(fields)

    def run(self, task_id, persist_tokens=lambda: None):
        self.task_id, self.owner = task_id, uuid.uuid4().hex
        now = self.clock()
        def claim(state):
            task = state["outbox"]
            if not task or task["id"] != task_id:
                return False
            if task["due"] > now or busy(state, now):
                raise Busy()
            state["lease"] = {"owner": self.owner, "until": now + LEASE_SECONDS}
            return True
        if not self.store.mutate(claim):
            return
        value = self.store.read()
        self.snapshot = Snapshot(**value["snapshot"])
        if self.raw_vehicle.configured:
            try:
                self.snapshot = self.raw_vehicle.refresh()
            except VehicleError as error:
                self.snapshot = replace(self.snapshot, available=False, message=str(error))
        else:
            self.snapshot = Snapshot()
        def measured(state):
            self.assert_owner(state)
            state.update(snapshot=self.snapshot.to_dict(), last_refresh=self.clock(),
                         configured=self.raw_vehicle.configured)
        self.store.mutate(measured)
        plan = copy.deepcopy(self.store.read()["plan"])
        self.advance(plan, self.clock())
        self.assert_owner(self.store.read())
        persist_tokens()
        now = self.clock()
        def complete(state):
            self.assert_owner(state)
            plan = state["plan"]
            state["lease"] = None
            state["outbox"] = None
            if plan and plan["state"] in ACTIVE:
                due = now + POLL_SECONDS
                if plan["state"] in ("pending_stop", "confirm_stop", "scheduled"):
                    due = min(due, plan["due"])
                if plan["state"] in ("pending_stop", "pending_start"):
                    due = min(due, max(now, plan["next_action"]))
                state["outbox"] = new_task(due)
        self.store.mutate(complete)
        self.scheduler.flush()
