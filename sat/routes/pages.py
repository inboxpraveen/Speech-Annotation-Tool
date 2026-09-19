"""HTML pages. All data comes from the JSON API; pages only carry the shell."""
from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from sat import auth, db, engines

bp = Blueprint("pages", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = auth.authenticate(request.form.get("username"), request.form.get("password"))
        if user:
            session.permanent = True
            session["uid"] = user["id"]
            target = request.args.get("next") or url_for("pages.dashboard")
            if not target.startswith("/"):
                target = url_for("pages.dashboard")
            return redirect(target)
        error = "Wrong username or password"
    if auth.current_user() and request.method == "GET":
        return redirect(url_for("pages.dashboard"))
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    user = auth.current_user()
    if user:
        auth.drop_presence(user["id"])
    session.clear()
    return redirect(url_for("pages.login"))


@bp.route("/")
@auth.login_required
def dashboard():
    return render_template("dashboard.html", engines=engines.catalog_with_status(), page="dashboard")


@bp.route("/projects/<int:project_id>")
@auth.login_required
def project(project_id):
    row = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        abort(404)
    return render_template("project.html", project=row, engines=engines.catalog_with_status(), page="project")


@bp.route("/models")
@auth.login_required
def models():
    return render_template("models.html", page="models")


@bp.route("/providers")
@auth.login_required
def providers():
    return render_template("providers.html", page="providers")


@bp.route("/jobs")
@auth.login_required
def jobs():
    return render_template("jobs.html", page="jobs")


@bp.route("/users")
@auth.admin_required
def users():
    return render_template("users.html", page="users")


@bp.route("/settings")
@auth.admin_required
def settings():
    return render_template("settings.html", page="settings")
