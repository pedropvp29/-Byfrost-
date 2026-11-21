from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, flash, current_app
)

from werkzeug.security import generate_password_hash, check_password_hash

import sqlite3
import hashlib
import hmac

login_bp = Blueprint("login", __name__, url_prefix="/login")


@login_bp.route("/", methods=["GET", "POST"])
def login_page():

    # Usuário já autenticado
    if session.get("user_id"):
        return redirect(url_for("app.app_page"))

    if request.method == "GET":
        return render_template("login.html")

    action = request.form.get("form_action", "")

    db = sqlite3.connect(current_app.config["DATABASE_PATH"])
    db.row_factory = sqlite3.Row

    cursor = db.cursor()
    pepper = current_app.config["PASSWORD_PEPPER"]

    try:

        # REGISTER
        if action == "register":

            tipo = request.form.get("type", "").strip()
            nome = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            senha = request.form.get("password", "")
            confirmar = request.form.get("confirm_password", "")
            lembrar = request.form.get("remember") == "on"

            if tipo not in ("pessoa", "ong", "empresa"):
                flash("Invalid account type.", "error")

            elif len(nome) < 2 or not email:
                flash("Please fill in all fields.", "error")

            elif len(senha) < 8:
                flash("Password must have at least 8 characters.", "error")

            elif senha != confirmar:
                flash("Passwords do not match.", "error")

            else:
                senha_pepper = hmac.new(
                    pepper.encode("utf-8"),
                    senha.encode("utf-8"),
                    hashlib.sha256
                ).hexdigest()

                senha_hash = generate_password_hash(senha_pepper)

                try:
                    cursor.execute("""
                        INSERT INTO users (type, name, email, password)
                        VALUES (?, ?, ?, ?)
                    """, (tipo, nome, email, senha_hash))

                    user_id = cursor.lastrowid

                    cursor.execute("""
                        UPDATE users
                        SET last_login = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (user_id,))

                    db.commit()

                    # Login automático após criar conta
                    session.clear()
                    session["user_id"] = user_id
                    session["user_name"] = nome
                    session["user_type"] = tipo
                    session["user_level"] = 1
                    session.permanent = lembrar

                    return redirect(url_for("app.app_page"))

                except sqlite3.IntegrityError:
                    db.rollback()
                    flash("This email is already registered.", "error")

        # LOGIN
        elif action == "login":

            identificador = request.form.get("identifier", "").strip()
            senha = request.form.get("password", "")
            lembrar = request.form.get("remember") == "on"

            cursor.execute("""
                SELECT * FROM users
                WHERE LOWER(email) = LOWER(?)
                LIMIT 1
            """, (identificador,))

            usuario = cursor.fetchone()

            if usuario is None:
                cursor.execute("""
                    SELECT * FROM users
                    WHERE LOWER(name) = LOWER(?)
                    LIMIT 2
                """, (identificador,))

                encontrados = cursor.fetchall()

                if len(encontrados) > 1:
                    flash(
                        "Multiple accounts have this name. Please use your email.",
                        "error"
                    )
                    return redirect(url_for("login.login_page"))

                if encontrados:
                    usuario = encontrados[0]

            senha_pepper = hmac.new(
                pepper.encode("utf-8"),
                senha.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()

            if (
                usuario is None
                or not check_password_hash(
                    usuario["password"], senha_pepper
                )
            ):
                flash("Invalid username/email or password.", "error")

            elif not usuario["active"]:
                flash("This account is disabled.", "error")

            else:
                cursor.execute("""
                    UPDATE users
                    SET last_login = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (usuario["id"],))

                db.commit()

                session.clear()
                session["user_id"] = usuario["id"]
                session["user_name"] = usuario["name"]
                session["user_type"] = usuario["type"]
                session["user_level"] = usuario["level"]
                session.permanent = lembrar

                return redirect(url_for("app.app_page"))

        else:
            flash("Invalid operation.", "error")

        return redirect(url_for("login.login_page"))

    finally:
        db.close()


@login_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("landing_page"))