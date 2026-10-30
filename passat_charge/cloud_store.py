"""Transactional cloud state. No Volkswagen credentials are stored here."""

import copy
import random
import time

from .scheduler import PlanError


def initial_state():
    from .vehicle import Snapshot
    return {"plan": None, "snapshot": Snapshot().to_dict(), "configured": False,
            "last_refresh": None, "outbox": None, "lease": None, "queue_error": None}


class FirestoreStore:
    def __init__(self, project, database="(default)"):
        from google.cloud import firestore
        self.client = firestore.Client(project=project, database=database)
        self.reference = self.client.collection("charging").document("main")

    def read(self):
        document = self.reference.get(timeout=15)
        return {**initial_state(), **(document.to_dict() or {})}

    def mutate(self, callback):
        def change(value):
            state = {**initial_state(), **value}
            result = callback(state)
            return state, result
        return self._compare_and_write(self.reference, change)

    def _compare_and_write(self, reference, change):
        # All authoritative scheduling state fits in one document. Conditional
        # writes give serializable updates without holding a read lock across
        # concurrent requests (or ever across Volkswagen/network operations).
        from google.api_core.exceptions import AlreadyExists, FailedPrecondition, NotFound, Aborted
        for attempt in range(8):
            document = reference.get(timeout=15)
            value, result = change(document.to_dict() or {})
            try:
                if document.exists:
                    reference.update(value, option=self.client.write_option(last_update_time=document.update_time),
                                     retry=None, timeout=15)
                else:
                    reference.create(value, retry=None, timeout=15)
                return copy.deepcopy(result)
            except (AlreadyExists, FailedPrecondition, NotFound, Aborted):
                time.sleep(random.uniform(0.01, min(0.3, 0.02 * 2 ** attempt)))
        raise PlanError("De planning wordt bijgewerkt. Probeer het zo opnieuw.")

    def allow_login(self, bucket, now):
        reference = self.client.collection("login_limits").document(bucket)
        def reserve(value):
            attempts = [stamp for stamp in value.get("attempts", []) if stamp > now - 900]
            if len(attempts) >= 5:
                return {"attempts": attempts}, False
            return {"attempts": [*attempts, now]}, True
        return self._compare_and_write(reference, reserve)

    def clear_login(self, bucket):
        self.client.collection("login_limits").document(bucket).delete(timeout=15)


class TaskQueue:
    def __init__(self, project, region, queue, worker_url, caller, audience):
        from google.cloud import tasks_v2
        if worker_url and not worker_url.startswith("https://"):
            raise ValueError("Cloud worker requires HTTPS")
        self.client = tasks_v2.CloudTasksClient()
        self.parent = self.client.queue_path(project, region, queue)
        self.worker_url, self.caller, self.audience = (worker_url or "").rstrip("/"), caller, audience

    def with_url(self, url):
        queue = copy.copy(self)
        queue.worker_url = url
        return queue

    def publish(self, task):
        import json
        from google.api_core.exceptions import AlreadyExists
        from google.protobuf.timestamp_pb2 import Timestamp
        if not self.worker_url.startswith("https://"):
            raise ValueError("Missing HTTPS worker URL")
        timestamp = Timestamp()
        timestamp.FromSeconds(int(task["due"]))
        # Round upwards: never ask the platform to deliver before the due time.
        if timestamp.seconds < task["due"]:
            timestamp.seconds += 1
        try:
            self.client.create_task(parent=self.parent, task={
                "name": self.parent + "/tasks/" + task["id"],
                "schedule_time": timestamp,
                "dispatch_deadline": {"seconds": 260},
                "http_request": {
                    "http_method": "POST", "url": self.worker_url + "/tasks/step",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"task_id": task["id"]}).encode(),
                    "oidc_token": {"service_account_email": self.caller, "audience": self.audience},
                },
            }, timeout=15)
        except AlreadyExists:
            pass


class TokenVault:
    """Private bucket is readable only by the worker service account."""

    def __init__(self, bucket):
        from google.cloud import storage
        self.blob = storage.Client().bucket(bucket).blob("volkswagen-tokens.json")

    def restore(self, path):
        from google.api_core.exceptions import NotFound
        try:
            path.write_bytes(self.blob.download_as_bytes(timeout=15))
            path.chmod(0o600)
        except NotFound:
            pass

    def save(self, path):
        if path.exists():
            self.blob.upload_from_filename(str(path), content_type="application/json", timeout=15)
