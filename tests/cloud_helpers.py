import copy
import threading

from passat_charge.cloud import CloudScheduler, CloudWorker
from passat_charge.cloud_store import initial_state
from tests.helpers import Clock, FakeVehicle


class MemoryStore:
    def __init__(self):
        self.state = initial_state()
        self.logins = {}
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def mutate(self, callback):
        with self.lock:
            value = copy.deepcopy(self.state)
            result = callback(value)
            self.state = value
            return copy.deepcopy(result)

    def allow_login(self, bucket, now):
        with self.lock:
            previous = [stamp for stamp in self.logins.get(bucket, []) if stamp > now - 900]
            if len(previous) >= 5:
                return False
            self.logins[bucket] = [*previous, now]
            return True

    def clear_login(self, bucket):
        with self.lock:
            self.logins.pop(bucket, None)


class FakeQueue:
    def __init__(self):
        self.tasks = {}
        self.fail = False

    def publish(self, task):
        if self.fail:
            raise ConnectionError("test-only queue failure")
        self.tasks.setdefault(task["id"], copy.deepcopy(task))


class CloudFixture:
    def setUp(self):
        self.clock = Clock()
        self.vehicle = FakeVehicle(self.clock)
        self.store = self.make_store()
        self.queue = FakeQueue()
        self.scheduler = CloudScheduler(self.store, self.queue, self.clock)
        self.scheduler.status()
        self.step()

    def make_store(self):
        return MemoryStore()

    def step(self, task_id=None):
        task_id = task_id or self.store.read()["outbox"]["id"]
        CloudWorker(self.store, self.scheduler, self.vehicle, self.clock).run(task_id)

    def paused_plan(self):
        plan = self.scheduler.arm("22:30")
        self.step()
        self.clock.advance(180)
        self.vehicle.measure(charging=False)
        self.step()
        return plan
