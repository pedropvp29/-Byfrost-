from flask import Flask, render_template, redirect, url_for, session
from sqlite3 import connect
from dotenv import load_dotenv
from datetime import timedelta
from pathlib import Path
import os

from blueprints.login import login_bp
from blueprints.app import app_bp

# Environment
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ["SECRET_KEY"]
PASSWORD_PEPPER = os.environ["PASSWORD_PEPPER"]

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/users.db")
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))

DB_PATH = BASE_DIR / DATABASE_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Database
db = connect(DB_PATH)
db.execute("PRAGMA foreign_keys = ON")

db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP DEFAULT NULL,
        active BOOLEAN DEFAULT TRUE,
        level INTEGER NOT NULL DEFAULT 1,
        amount INTEGER NOT NULL DEFAULT 0,
        profile BLOB
    )
""")

db.execute("""
    CREATE TABLE IF NOT EXISTS tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT NOT NULL UNIQUE,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        FOREIGN KEY (user_id) REFERENCES users(id)
            ON DELETE CASCADE
    )
""")

db.execute("""
    CREATE INDEX IF NOT EXISTS idx_userId
    ON users (id)
""")

db.execute("""
    CREATE INDEX IF NOT EXISTS idx_tokens_user_id
    ON tokens (user_id)
""")

db.execute("""
    CREATE INDEX IF NOT EXISTS idx_tokens_expires_at
    ON tokens (expires_at)
""")

db.commit()
db.close()

# Flask
app = Flask(__name__)

app.config["SECRET_KEY"] = SECRET_KEY
app.config["PASSWORD_PEPPER"] = PASSWORD_PEPPER
app.config["DATABASE_PATH"] = str(DB_PATH)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=SESSION_DAYS)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False  # True em HTTPS

app.register_blueprint(login_bp)
app.register_blueprint(app_bp)


@app.route("/")
def landing_page():

    if session.get("user_id"):
        return redirect(url_for("app.app_page"))

    return render_template("landing.html")


if __name__ == "__main__":
    app.run()