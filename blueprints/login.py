from contextlib import closing
import hashlib
import hmac
import re
import sqlite3

from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, session, url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

from blueprints.app import (
    AUTH_COOKIE, clear_auth_cookies, get_authenticated_user, issue_login,
)

login_bp = Blueprint("login", __name__, url_prefix="/login")
limiter = Limiter(key_func=get_remote_address)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@login_bp.route("/", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def login_page():
    if get_authenticated_user() is not None:
        return redirect(url_for("app.app_page"))

    if request.method == "GET":
        return render_template("login.html")

    action = request.form.get("form_action", "")
    pepper = current_app.config["PASSWORD_PEPPER"].encode("utf-8")

    with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as db:
        db.row_factory = sqlite3.Row

        if action == "register":
            tipo = request.form.get("type", "").strip()
            nome = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            senha = request.form.get("password", "")
            confirmar = request.form.get("confirm_password", "")

            if tipo not in ("pessoa", "ong", "empresa"):
                flash("Invalid account type.", "error")
            elif not (2 <= len(nome) <= 120) or not (1 <= len(email) <= 254) or not EMAIL_RE.fullmatch(email):
                flash("Please enter a valid name and email.", "error")
            elif not (8 <= len(senha) <= 256):
                flash("Password must contain 8 to 256 characters.", "error")
            elif senha != confirmar:
                flash("Passwords do not match.", "error")
            else:
                senha_pepper = hmac.new(pepper, senha.encode("utf-8"), hashlib.sha256).hexdigest()
                senha_hash = generate_password_hash(senha_pepper)
                try:
                    cursor = db.execute("""
                        INSERT INTO users (type, name, email, password)
                        VALUES (?, ?, ?, ?)
                    """, (tipo, nome, email, senha_hash))
                    user_id = cursor.lastrowid
                    db.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (user_id,))
                    db.commit()
                    # A new account is immediately authenticated.
                    return issue_login(user_id, nome, tipo, 1, remember=False)
                except sqlite3.IntegrityError:
                    db.rollback()
                    flash("This email is already registered.", "error")

        elif action == "login":
            identificador = request.form.get("identifier", "").strip()
            senha = request.form.get("password", "")
            remember = request.form.get("remember") == "on"

            usuario = None
            if identificador and senha:
                usuario = db.execute("""
                    SELECT id, name, email, type, password, active, level
                    FROM users WHERE email = ? COLLATE NOCASE LIMIT 1
                """, (identificador,)).fetchone()

                if usuario is None:
                    matches = db.execute("""
                        SELECT id, name, email, type, password, active, level
                        FROM users WHERE name = ? COLLATE NOCASE LIMIT 2
                    """, (identificador,)).fetchall()
                    if len(matches) > 1:
                        flash("Multiple accounts share that name. Sign in with your email.", "error")
                        return redirect(url_for("login.login_page"))
                    if matches:
                        usuario = matches[0]

            senha_pepper = hmac.new(pepper, senha.encode("utf-8"), hashlib.sha256).hexdigest()
            valid = bool(usuario) and check_password_hash(usuario["password"], senha_pepper)
            if not valid or not usuario["active"]:
                flash("Invalid credentials or inactive account.", "error")
            else:
                db.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (usuario["id"],))
                db.commit()
                return issue_login(
                    usuario["id"], usuario["name"], usuario["type"],
                    usuario["level"], remember=remember,
                )
        else:
            flash("Invalid form action.", "error")

    # Keep the registration tab selected if account creation needs correction.
    return redirect(url_for("login.login_page", mode="register" if action == "register" else "login"))


@login_bp.route("/logout", methods=["POST"])
def logout():
    raw_token = request.cookies.get(AUTH_COOKIE, "")
    user_id = session.get("user_id")
    if raw_token and user_id:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as db:
            db.execute("UPDATE tokens SET active=0 WHERE token=? AND user_id=?", (token_hash, user_id))
            db.commit()

    session.clear()
    return clear_auth_cookies(redirect(url_for("landing_page")))
