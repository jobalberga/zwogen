"""Cloud Run entrypoints; no scheduler threads or permanent local storage."""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path

from flask import Flask, g, jsonify, request
from waitress import serve

from .cloud import CloudScheduler, CloudWorker
from .cloud_store import FirestoreStore, TaskQueue, TokenVault
from .vehicle import Volkswagen
from .web import create_app


def components():
    project = os.environ["PASSAT_PROJECT"]
    store = FirestoreStore(project)
    queue = TaskQueue(project, os.environ["PASSAT_REGION"], os.environ["TASK_QUEUE"],
                      os.environ.get("WORKER_URL"), os.environ["TASK_SERVICE_ACCOUNT"],
                      os.environ["TASK_AUDIENCE"])
    return store, CloudScheduler(store, queue)


def read_secret(path, keys):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or not value[key] for key in keys):
        raise ValueError("Onvolledige geheime configuratie")
    return value


def verify_caller(token):
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import verify_oauth2_token
    claims = verify_oauth2_token(token, partial(Request(), timeout=5), audience=os.environ["TASK_AUDIENCE"],
                                clock_skew_in_seconds=30)
    if claims.get("email") != os.environ["TASK_SERVICE_ACCOUNT"] or claims.get("email_verified") is not True:
        raise ValueError("Wrong task identity")


def run_child(task_id, worker_url=None):
    # Cloud Run timeouts do not kill application code. A subprocess gives the
    # vehicle operation a real lifetime shorter than the durable execution lease.
    environment = dict(os.environ)
    if worker_url:
        environment["WORKER_URL"] = worker_url
    result = subprocess.run([sys.executable, "-m", "passat_charge.cloud_job", task_id],
                            capture_output=True, timeout=200, env=environment)
    if result.returncode:
        raise RuntimeError("Worker iteration failed")


def create_worker_app(scheduler, verify=verify_caller, execute=run_child, resolve_url=False):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024

    @app.get("/healthz")
    def health():
        return jsonify(ok=True)

    @app.before_request
    def authenticate():
        if request.path == "/healthz":
            return
        header = request.headers.get("Authorization", "")
        try:
            if not header.startswith("Bearer "):
                raise ValueError()
            verify(header[7:])
        except Exception:
            return jsonify(error="Unauthorized"), 401
        if resolve_url:
            # Cloud Run's frontend routes the request to this service using
            # its run.app hostname. Do not trust forwarded-host headers.
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.run\.app", request.host):
                return jsonify(error="Invalid worker host"), 400
            g.worker_url = "https://" + request.host
        else:
            g.worker_url = None

    @app.post("/tasks/step")
    def step():
        data = request.get_json(silent=True)
        task_id = data.get("task_id") if isinstance(data, dict) else None
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{32}", task_id):
            return jsonify(error="Invalid task"), 400
        try:
            execute(task_id, g.worker_url)
        except Exception as error:
            logging.error("Cloud task failed (%s)", type(error).__name__)
            return jsonify(error="Retry required"), 503
        return jsonify(ok=True)

    @app.post("/tasks/reconcile")
    def reconcile():
        try:
            current = scheduler
            if g.worker_url:
                current = CloudScheduler(scheduler.store, scheduler.queue.with_url(g.worker_url))
            current.reconcile()
        except Exception as error:
            logging.error("Cloud task recovery failed (%s)", type(error).__name__)
            return jsonify(error="Retry required"), 503
        return jsonify(ok=True)

    return app


def main(mode):
    os.umask(0o077)
    store, scheduler = components()
    if mode == "cloud-web":
        config = read_secret(os.environ["PASSAT_WEB_SECRET_FILE"], ("password", "session_secret"))
        if len(config["session_secret"]) < 32:
            raise ValueError("Sessiesleutel is te kort")
        app = create_app(scheduler, config["password"], config["session_secret"], secure_cookies=True)
    elif mode == "cloud-worker":
        app = create_worker_app(scheduler, resolve_url=True)
    else:
        raise ValueError("Unknown cloud mode")
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), threads=4)


def job(task_id):
    os.umask(0o077)
    store, scheduler = components()
    config = read_secret(os.environ["PASSAT_VW_SECRET_FILE"], ("username", "password", "vin"))
    vault = TokenVault(os.environ["TOKEN_BUCKET"])
    with tempfile.TemporaryDirectory(prefix="passat-vw-") as directory:
        path = Path(directory) / "vw-tokens.json"
        vault.restore(path)
        vehicle = Volkswagen(config["username"], config["password"], config["vin"], directory)
        worker = CloudWorker(store, scheduler, vehicle)
        worker.run(task_id, persist_tokens=lambda: vault.save(path))
