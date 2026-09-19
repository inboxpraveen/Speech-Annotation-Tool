"""Flask application factory."""
import logging
import logging.handlers
import sys

from flask import Flask, jsonify, request

from sat import auth, db
from sat.config import BASE_DIR, LOG_DIR, LOG_LEVEL, SECRET_KEY

VERSION = "3.0.0"


def setup_logging():
    root = logging.getLogger()
    if getattr(root, "_sat_configured", False):
        return
    root.setLevel(LOG_LEVEL)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rotating = logging.handlers.RotatingFileHandler(LOG_DIR / "app.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    rotating.setFormatter(fmt)
    root.addHandler(rotating)
    for noisy in ("urllib3", "httpx", "httpcore", "filelock", "werkzeug", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    root._sat_configured = True


def create_app(start_jobs=True):
    setup_logging()
    app = Flask(__name__, static_folder=str(BASE_DIR / "static"), template_folder=str(BASE_DIR / "templates"))
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30
    app.jinja_env.globals["app_version"] = VERSION

    db.init_db()
    auth.bootstrap_admin()

    from sat.routes.api import bp as api_bp
    from sat.routes.pages import bp as pages_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)

    @app.before_request
    def load_user():
        auth.current_user()

    @app.teardown_appcontext
    def close_db(exc):
        db.close()

    @app.errorhandler(404)
    def not_found(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not found"}), 404
        return "Not found", 404

    @app.errorhandler(Exception)
    def on_error(exc):
        from werkzeug.exceptions import HTTPException

        if isinstance(exc, HTTPException):
            if request.path.startswith("/api/"):
                return jsonify({"error": exc.description}), exc.code
            return exc
        logging.getLogger("sat").exception("unhandled error on %s", request.path)
        if request.path.startswith("/api/"):
            return jsonify({"error": str(exc)}), 500
        return "Internal error: %s" % exc, 500

    if start_jobs:
        from sat.jobs import runner
        runner.start()
    return app
