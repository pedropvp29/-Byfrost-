from datetime import timedelta
from pathlib import Path
import os
import sqlite3

from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, abort, make_response
from flask_wtf.csrf import CSRFProtect, CSRFError

from blueprints.app import app_bp, get_authenticated_user
from blueprints.login import login_bp, limiter

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ["SECRET_KEY"]
PASSWORD_PEPPER = os.environ["PASSWORD_PEPPER"]
if (
    len(SECRET_KEY) < 32 or len(PASSWORD_PEPPER) < 32
    or SECRET_KEY.startswith("REPLACE_")
    or PASSWORD_PEPPER.startswith("REPLACE_")
):
    raise RuntimeError("SECRET_KEY and PASSWORD_PEPPER must each have at least 32 characters.")

DB_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "data/users.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Initialize or upgrade the existing database without deleting user data.
with sqlite3.connect(DB_PATH) as db:
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("""CREATE TABLE IF NOT EXISTS users (
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
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT NOT NULL UNIQUE,
        fingerprint_hash TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    # Older Byfrost database: the existing tokens table may lack this column.
    columns = {row[1] for row in db.execute("PRAGMA table_info(tokens)")}
    if "fingerprint_hash" not in columns:
        db.execute("ALTER TABLE tokens ADD COLUMN fingerprint_hash TEXT")
        # Older tokens are deliberately invalid without a browser binding.

    db.execute("CREATE INDEX IF NOT EXISTS idx_tokens_user_id ON tokens (user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tokens_expires_at ON tokens (expires_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tokens_active ON tokens (active, expires_at)")

    db.execute("""CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        legal_name TEXT NOT NULL,
        trade_name TEXT,
        tax_id TEXT UNIQUE,
        description TEXT,
        sector TEXT,
        website TEXT,
        phone TEXT,
        address TEXT,
        city TEXT,
        state TEXT,
        country TEXT,
        postal_code TEXT,
        logo BLOB,
        verified BOOLEAN NOT NULL DEFAULT FALSE,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS ngos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        legal_name TEXT NOT NULL,
        public_name TEXT,
        tax_id TEXT UNIQUE,
        description TEXT,
        mission TEXT,
        cause TEXT,
        website TEXT,
        phone TEXT,
        address TEXT,
        city TEXT,
        state TEXT,
        country TEXT,
        postal_code TEXT,
        logo BLOB,
        verified BOOLEAN NOT NULL DEFAULT FALSE,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_companies_city ON companies (city)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_ngos_city ON ngos (city)")
    # Optional details are entered later, in the profile settings.
    user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    for column in ("country", "state", "city", "postal_code", "address"):
        if column not in user_columns:
            db.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
    # Community & logistics prototype: these tables are additive and preserve users/tokens.
    db.execute("""CREATE TABLE IF NOT EXISTS campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ngo_user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        category TEXT NOT NULL,
        target_quantity INTEGER NOT NULL DEFAULT 1 CHECK(target_quantity > 0),
        unit TEXT NOT NULL DEFAULT 'items',
        allow_money_demo INTEGER NOT NULL DEFAULT 0 CHECK(allow_money_demo IN (0,1)),
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(ngo_user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ngo_user_id INTEGER NOT NULL,
        campaign_id INTEGER,
        kind TEXT NOT NULL CHECK(kind IN ('need','giveaway')),
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        category TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        unit TEXT NOT NULL DEFAULT 'items',
        allow_dropoff INTEGER NOT NULL DEFAULT 1,
        allow_pickup INTEGER NOT NULL DEFAULT 0,
        allow_contact INTEGER NOT NULL DEFAULT 1,
        allow_claims INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(ngo_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS collection_points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ngo_user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        address TEXT NOT NULL,
        city TEXT NOT NULL,
        state TEXT NOT NULL,
        postal_code TEXT,
        latitude REAL NOT NULL CHECK(latitude BETWEEN -90 AND 90),
        longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180),
        instructions TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(ngo_user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS request_points (
        request_id INTEGER NOT NULL,
        point_id INTEGER NOT NULL,
        PRIMARY KEY(request_id, point_id),
        FOREIGN KEY(request_id) REFERENCES requests(id) ON DELETE CASCADE,
        FOREIGN KEY(point_id) REFERENCES collection_points(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_user_id INTEGER NOT NULL,
        ngo_user_id INTEGER,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        category TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        unit TEXT NOT NULL DEFAULT 'items',
        status TEXT NOT NULL DEFAULT 'available'
          CHECK(status IN ('available','reserved','delivered','cancelled')),
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(donor_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(ngo_user_id) REFERENCES users(id) ON DELETE SET NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS donations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_user_id INTEGER NOT NULL,
        ngo_user_id INTEGER NOT NULL,
        request_id INTEGER,
        offer_id INTEGER UNIQUE,
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        method TEXT NOT NULL CHECK(method IN ('dropoff','pickup','contact','offer')),
        status TEXT NOT NULL DEFAULT 'pledged'
          CHECK(status IN ('pledged','confirmed','cancelled')),
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        confirmed TIMESTAMP,
        FOREIGN KEY(donor_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(ngo_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(request_id) REFERENCES requests(id) ON DELETE SET NULL,
        FOREIGN KEY(offer_id) REFERENCES offers(id) ON DELETE SET NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        status TEXT NOT NULL DEFAULT 'reserved'
          CHECK(status IN ('reserved','collected','cancelled')),
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(request_id) REFERENCES requests(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author_user_id INTEGER NOT NULL,
        body TEXT NOT NULL,
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(author_user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_user_id INTEGER NOT NULL,
        recipient_user_id INTEGER NOT NULL,
        request_id INTEGER,
        body TEXT NOT NULL,
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(sender_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(recipient_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(request_id) REFERENCES requests(id) ON DELETE SET NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS impact_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        donation_id INTEGER NOT NULL UNIQUE,
        points INTEGER NOT NULL CHECK(points >= 0),
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(donation_id) REFERENCES donations(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS badges (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        required_confirmed INTEGER NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS user_badges (
        user_id INTEGER NOT NULL,
        badge_slug TEXT NOT NULL,
        awarded TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id,badge_slug),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(badge_slug) REFERENCES badges(slug) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS demo_payments (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        campaign_id INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        is_demo INTEGER NOT NULL DEFAULT 1 CHECK(is_demo = 1),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_ngo ON campaigns(ngo_user_id, status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_requests_ngo ON requests(ngo_user_id, status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_requests_campaign ON requests(campaign_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(status, created)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_donations_ngo ON donations(ngo_user_id, status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_donations_donor ON donations(donor_user_id, status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_user_id, created)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient_user_id, created)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_user_id, created)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_claims_request ON claims(request_id, status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_points_ngo ON collection_points(ngo_user_id, active)")
    for slug, name, threshold in (("first-bridge","First Bridge",1),("community-builder","Community Builder",5),("impact-maker","Impact Maker",10)):
        db.execute("INSERT OR IGNORE INTO badges(slug,name,required_confirmed) VALUES(?,?,?)",(slug,name,threshold))
    # Authorization rules enforced at database level as well as in Flask.
    # Existing data is not deleted or rewritten by these additive triggers.
    for table, owner, roles in (
        ("requests", "ngo_user_id", ("ong",)),
        ("campaigns", "ngo_user_id", ("ong",)),
        ("collection_points", "ngo_user_id", ("ong",)),
        ("offers", "donor_user_id", ("pessoa", "empresa")),
        ("ngos", "user_id", ("ong",)),
        ("companies", "user_id", ("empresa",)),
        ("donations", "donor_user_id", ("pessoa", "empresa")),
        ("claims", "user_id", ("pessoa",)),
    ):
        allowed = ",".join("'" + role + "'" for role in roles)
        for action in ("INSERT", "UPDATE"):
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_{action.lower()}_role
                BEFORE {action} ON {table}
                WHEN NOT EXISTS (SELECT 1 FROM users
                                 WHERE id = NEW.{owner} AND type IN ({allowed}) AND active = 1)
                BEGIN SELECT RAISE(ABORT, 'Invalid account role for this action'); END
            """)
    db.execute("""CREATE TRIGGER IF NOT EXISTS trg_request_points_same_ngo
        BEFORE INSERT ON request_points
        WHEN NOT EXISTS (
          SELECT 1 FROM requests r JOIN collection_points p
            ON r.ngo_user_id=p.ngo_user_id
          WHERE r.id=NEW.request_id AND p.id=NEW.point_id
        )
        BEGIN SELECT RAISE(ABORT, 'Collection point does not belong to this nonprofit'); END
    """)
    for action in ("INSERT", "UPDATE"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_donations_{action.lower()}_ngo
            BEFORE {action} ON donations
            WHEN NOT EXISTS (SELECT 1 FROM users
                             WHERE id=NEW.ngo_user_id AND type='ong' AND active=1)
            BEGIN SELECT RAISE(ABORT, 'Donations can only be received by nonprofits'); END
        """)
    db.execute("""CREATE TRIGGER IF NOT EXISTS trg_request_points_update_same_ngo
        BEFORE UPDATE ON request_points
        WHEN NOT EXISTS (
          SELECT 1 FROM requests r JOIN collection_points p
            ON r.ngo_user_id=p.ngo_user_id
          WHERE r.id=NEW.request_id AND p.id=NEW.point_id
        )
        BEGIN SELECT RAISE(ABORT, 'Collection point does not belong to this nonprofit'); END
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_requests_filter ON requests(status,kind,category,created)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_request_points_point ON request_points(point_id)")
    # Social giving: public profiles are opt-in for individuals.
    user_cols = {r[1] for r in db.execute("PRAGMA table_info(users)")}
    for col, definition in {
        "bio": "TEXT NOT NULL DEFAULT ''",
        "headline": "TEXT NOT NULL DEFAULT ''",
        "public_profile": "INTEGER NOT NULL DEFAULT 0",
        "leaderboard_opt_in": "INTEGER NOT NULL DEFAULT 0",
        "equipped_title_id": "INTEGER",
        "equipped_frame_id": "INTEGER",
        "equipped_accent_id": "INTEGER",
    }.items():
        if col not in user_cols:
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
    db.execute("""CREATE TABLE IF NOT EXISTS follows (
        follower_user_id INTEGER NOT NULL,
        followed_user_id INTEGER NOT NULL,
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(follower_user_id,followed_user_id),
        FOREIGN KEY(follower_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(followed_user_id) REFERENCES users(id) ON DELETE CASCADE,
        CHECK(follower_user_id != followed_user_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS post_likes (
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(post_id,user_id),
        FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS post_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        body TEXT NOT NULL CHECK(length(body) <= 500),
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS ngo_rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ngo_user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL CHECK(kind IN ('title','frame','accent')),
        symbol TEXT NOT NULL DEFAULT '✦',
        color TEXT NOT NULL DEFAULT 'violet',
        min_confirmed INTEGER NOT NULL DEFAULT 1 CHECK(min_confirmed BETWEEN 1 AND 100),
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(ngo_user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS reward_unlocks (
        user_id INTEGER NOT NULL,
        reward_id INTEGER NOT NULL,
        awarded TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id,reward_id),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(reward_id) REFERENCES ngo_rewards(id) ON DELETE CASCADE
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_follows_target ON follows(followed_user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_post_comments_post ON post_comments(post_id,created)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_rewards_ngo ON ngo_rewards(ngo_user_id,active)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_unlocks_user ON reward_unlocks(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_confirmed_rank ON donations(status,donor_user_id)")
    for action in ('INSERT','UPDATE'):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_rewards_{action.lower()}_ngo
        BEFORE {action} ON ngo_rewards
        WHEN NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.ngo_user_id AND type='ong' AND active=1)
        BEGIN SELECT RAISE(ABORT,'Only nonprofits may create rewards'); END""")
    # V4: explainable topic matching, weak view signals, post media and user controls.
    post_columns={r[1] for r in db.execute("PRAGMA table_info(posts)")}
    for column,definition in {
        "tags": "TEXT NOT NULL DEFAULT ''",
        'request_id':'INTEGER',
    }.items():
        if column not in post_columns:
            db.execute(f"ALTER TABLE posts ADD COLUMN {column} {definition}")
    db.execute("""CREATE TABLE IF NOT EXISTS post_images (
        post_id INTEGER PRIMARY KEY, image_data BLOB NOT NULL, mime TEXT NOT NULL DEFAULT 'image/jpeg',
        FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE)""")
    db.execute("""CREATE TABLE IF NOT EXISTS user_topic_scores (
        user_id INTEGER NOT NULL, tag TEXT NOT NULL, weight REAL NOT NULL DEFAULT 0,
        updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id,tag),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)""")
    db.execute("""CREATE TABLE IF NOT EXISTS user_pinned_topics (
        user_id INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY(user_id,tag),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)""")
    db.execute("""CREATE TABLE IF NOT EXISTS post_views (
        user_id INTEGER NOT NULL, post_id INTEGER NOT NULL,
        day TEXT NOT NULL DEFAULT (date('now')),
        PRIMARY KEY(user_id,post_id,day),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE)""")
    db.execute("""CREATE TABLE IF NOT EXISTS post_saves (
        user_id INTEGER NOT NULL, post_id INTEGER NOT NULL,
        PRIMARY KEY(user_id,post_id),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE)""")
    db.execute("""CREATE TABLE IF NOT EXISTS user_hidden_posts (
        user_id INTEGER NOT NULL, post_id INTEGER NOT NULL,
        PRIMARY KEY(user_id,post_id),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE)""")
    db.execute("""CREATE TABLE IF NOT EXISTS user_feed_settings (
        user_id INTEGER PRIMARY KEY, personalized INTEGER NOT NULL DEFAULT 1 CHECK(personalized IN (0,1)),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_posts_request ON posts(request_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_post_views_day ON post_views(user_id,day)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_topic_scores_user ON user_topic_scores(user_id,weight)")

    # Existing profiles are left private until the account holder opts in.
    db.commit()
db.close()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    PASSWORD_PEPPER=PASSWORD_PEPPER,
    DATABASE_PATH=str(DB_PATH),
    REMEMBER_DAYS=int(os.getenv("REMEMBER_DAYS", "30")),
    AUTH_HOURS=int(os.getenv("AUTH_HOURS", "12")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=int(os.getenv("REMEMBER_DAYS", "30"))),
    SESSION_COOKIE_NAME="bf_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SECURE_COOKIES", "false").lower() == "true",
    SESSION_COOKIE_PATH="/",
    WTF_CSRF_ENABLED=True,
    MAX_CONTENT_LENGTH=3 * 1024 * 1024,
    RATELIMIT_STORAGE_URI=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
)

hosts = os.getenv("TRUSTED_HOSTS", "").strip()
if hosts:
    app.config["TRUSTED_HOSTS"] = [host.strip() for host in hosts.split(",") if host.strip()]

csrf = CSRFProtect(app)  # All POST/PUT/PATCH/DELETE requests require valid CSRF tokens.
limiter.init_app(app)
app.register_blueprint(login_bp)
app.register_blueprint(app_bp)


def public_landing_content():
    """Show only public organizational activity; avoid presenting demo donations as real impact."""
    stats = {"organizations": 0, "requests": 0, "posts": 0}
    with sqlite3.connect(app.config["DATABASE_PATH"]) as db:
        db.row_factory = sqlite3.Row
        stats["organizations"] = db.execute("""SELECT COUNT(*) FROM users
            WHERE active=1 AND type IN ('ong','empresa')""").fetchone()[0]
        stats["requests"] = db.execute("""SELECT COUNT(*) FROM requests r
            JOIN users u ON u.id=r.ngo_user_id
            WHERE r.kind='need' AND r.status='open' AND u.active=1 AND u.type='ong'""").fetchone()[0]
        stats["posts"] = db.execute("""SELECT COUNT(*) FROM posts p
            JOIN users u ON u.id=p.author_user_id
            WHERE u.active=1 AND u.type IN ('ong','empresa')""").fetchone()[0]
        featured_orgs = db.execute("""SELECT u.id,u.type,u.name,u.city,
              COALESCE(NULLIF(n.public_name,''),NULLIF(co.trade_name,''),
                NULLIF(n.legal_name,''),NULLIF(co.legal_name,''),u.name) AS display_name,
              COALESCE(NULLIF(n.description,''),NULLIF(co.description,''),'') AS description,
              COALESCE(NULLIF(n.cause,''),NULLIF(co.sector,''),'Community') AS focus,
              (SELECT COUNT(*) FROM posts p WHERE p.author_user_id=u.id) AS post_count
              FROM users u LEFT JOIN ngos n ON n.user_id=u.id
              LEFT JOIN companies co ON co.user_id=u.id
              WHERE u.active=1 AND u.type IN ('ong','empresa')
              ORDER BY post_count DESC,u.id DESC LIMIT 6""").fetchall()
        featured_post = db.execute("""SELECT p.id,p.body,p.tags,
              COALESCE(NULLIF(n.public_name,''),NULLIF(co.trade_name,''),
                NULLIF(n.legal_name,''),NULLIF(co.legal_name,''),u.name) AS author_name,
              EXISTS(SELECT 1 FROM post_images pi WHERE pi.post_id=p.id) AS has_image,
              r.title AS request_title
              FROM posts p JOIN users u ON u.id=p.author_user_id
              LEFT JOIN ngos n ON n.user_id=u.id
              LEFT JOIN companies co ON co.user_id=u.id
              LEFT JOIN requests r ON r.id=p.request_id AND r.status='open' AND r.kind='need'
              WHERE u.active=1 AND u.type IN ('ong','empresa')
              ORDER BY has_image DESC,p.id DESC LIMIT 1""").fetchone()
    return {"public_stats": stats, "featured_orgs": featured_orgs, "featured_post": featured_post}


@app.route("/public/post-image/<int:post_id>")
def landing_post_image(post_id):
    """Public feed preview only for active nonprofit/business posts, never personal posts."""
    with sqlite3.connect(app.config["DATABASE_PATH"]) as db:
        row = db.execute("""SELECT pi.image_data,pi.mime FROM post_images pi
            JOIN posts p ON p.id=pi.post_id
            JOIN users u ON u.id=p.author_user_id
            WHERE pi.post_id=? AND u.active=1 AND u.type IN ('ong','empresa')""",
            (post_id,)).fetchone()
    if not row or row[1] not in ('image/jpeg','image/png','image/webp'):
        abort(404)
    response = make_response(row[0]); response.headers['Content-Type']=row[1]
    response.headers['Cache-Control']='public,max-age=300'
    return response


@app.route("/")
def landing_page():
    if get_authenticated_user() is not None:
        return redirect(url_for("app.app_page"))
    try:
        context = public_landing_content()
    except sqlite3.Error:
        app.logger.exception('Could not retrieve landing page community preview')
        context = {"public_stats": {"organizations": 0, "requests": 0, "posts": 0},
                   "featured_orgs": [], "featured_post": None}
    return render_template("landing.html", **context)


@app.errorhandler(CSRFError)
def csrf_error(error):
    return "Invalid or expired security token. Refresh the page and try again.", 400


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store"
    if app.config["SESSION_COOKIE_SECURE"]:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


if __name__ == "__main__":
    # Use a production WSGI server and HTTPS when deploying publicly.
    app.run(debug=False)
