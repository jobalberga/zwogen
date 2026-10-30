import hashlib
import hmac
import logging
import secrets
from datetime import timedelta
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import HTTPException

from .scheduler import PlanError


def create_app(scheduler, password, session_secret, *, secure_cookies=True):
    if len(password) < 12:
        raise ValueError("APP_PASSWORD moet minimaal 12 tekens bevatten.")
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=session_secret, SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_SECURE=secure_cookies,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7), MAX_CONTENT_LENGTH=4096,
    )
    password_hash = generate_password_hash(password)
    auth_version = hmac.new(session_secret.encode(), password.encode(), hashlib.sha256).hexdigest()

    def is_authenticated():
        return session.get("authenticated", False) and hmac.compare_digest(session.get("auth_version", ""), auth_version)

    @app.errorhandler(Exception)
    def failed_request(error):
        if isinstance(error, HTTPException):
            return jsonify(error="Ongeldig verzoek."), error.code
        # Backend exceptions may contain provider data. Do not expose them in
        # API responses or request tracebacks.
        logging.error("Web request failed (%s)", type(error).__name__)
        return jsonify(error="Dienst tijdelijk niet beschikbaar. Controleer de status voor een nieuwe poging."), 503

    @app.before_request
    def protection():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        if request.method == "POST":
            provided = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
            if not hmac.compare_digest(provided.encode(), session["csrf"].encode()):
                return jsonify(error="Je sessie is verlopen. Ververs de pagina."), 403

    @app.after_request
    def headers(response):
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })
        if secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def authenticated(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not is_authenticated():
                return jsonify(error="Log opnieuw in."), 401
            return view(*args, **kwargs)
        return wrapped

    @app.get("/healthz")
    def health():
        return jsonify(ok=True, planner=scheduler.healthy())

    @app.route("/", methods=["GET", "POST"])
    def home():
        error = None
        code = 200
        if request.method == "POST":
            bucket = hashlib.sha256((request.remote_addr or "unknown").encode()).hexdigest()
            if not scheduler.allow_login(bucket):
                error, code = "Te veel inlogpogingen. Probeer over 15 minuten opnieuw.", 429
            elif check_password_hash(password_hash, request.form.get("password", "")):
                scheduler.clear_login(bucket)
                session.clear()
                session.update(authenticated=True, auth_version=auth_version, csrf=secrets.token_urlsafe(32))
                session.permanent = True
                return redirect(url_for("home"))
            else:
                error, code = "Dit wachtwoord klopt niet.", 401

        return render_template("index.html", authenticated=is_authenticated(),
                               csrf=session["csrf"], error=error), code

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("home"))

    @app.get("/api/status")
    @authenticated
    def status():
        return jsonify(scheduler.status())

    @app.post("/api/plan")
    @authenticated
    def plan():
        data = request.get_json(silent=True) if request.content_length else {}
        if not isinstance(data, dict):
            return jsonify(error="Ongeldige opdracht."), 400
        try:
            return jsonify(plan=scheduler.arm(data.get("start_time", "00:00"))), 201
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except PlanError as error:
            return jsonify(error=str(error)), 409

    @app.post("/api/plan/<plan_id>/cancel")
    @authenticated
    def cancel(plan_id):
        try:
            return jsonify(plan=scheduler.cancel(plan_id))
        except PlanError as error:
            return jsonify(error=str(error)), 409

    return app
