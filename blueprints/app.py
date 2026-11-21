from flask import Blueprint, render_template, session, redirect, url_for

app_bp = Blueprint("app", __name__, url_prefix="/app")


@app_bp.route("/")
def app_page():

    if not session.get("user_id"):
        return redirect(url_for("login.login_page"))

    return render_template("app.html")