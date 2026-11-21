"""Byfrost app: validated sessions, account dashboard and profile updates."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import hmac
import re
import secrets
import sqlite3

from flask import (
    Blueprint, abort, current_app, flash, g, make_response, redirect,
    render_template, request, session, url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError
from blueprints.recommend import ranked_feed, tags_for, add_affinity, POPULAR_TOPICS, CATEGORY_TOPIC
from flask import jsonify

app_bp = Blueprint("app", __name__, url_prefix="/app")
AUTH_COOKIE = "bf_auth"
DEVICE_COOKIE = "bf_device"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def device_fingerprint(device_secret):
    # Random device cookie binding, NOT a hardware/browser biometric fingerprint.
    data = (device_secret + "\0" + request.headers.get("User-Agent", "")).encode("utf-8")
    key = current_app.config["PASSWORD_PEPPER"].encode("utf-8")
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def clear_auth_cookies(response):
    for name in (AUTH_COOKIE, DEVICE_COOKIE):
        response.delete_cookie(name, path="/")
    return response


def get_authenticated_user():
    user_id = session.get("user_id")
    raw_token = request.cookies.get(AUTH_COOKIE, "")
    device_secret = request.cookies.get(DEVICE_COOKIE, "")
    if not user_id or not raw_token or not device_secret:
        if user_id:
            session.clear()
        return None

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as db:
        db.row_factory = sqlite3.Row
        user = db.execute("""
            SELECT u.id, u.name, u.email, u.type, u.level, u.created,
                   u.last_login, u.amount, t.fingerprint_hash
            FROM tokens AS t
            JOIN users AS u ON u.id = t.user_id
            WHERE t.user_id = ? AND t.token = ? AND t.active = 1
              AND t.expires_at > CURRENT_TIMESTAMP AND u.active = 1
            LIMIT 1
        """, (user_id, token_hash)).fetchone()
    if not user or not user["fingerprint_hash"] or not hmac.compare_digest(
        user["fingerprint_hash"], device_fingerprint(device_secret)
    ):
        session.clear()
        return None
    return user


def issue_login(user_id, user_name, user_type, user_level, remember=False):
    raw_token = secrets.token_urlsafe(32)
    device_secret = secrets.token_urlsafe(32)
    lifetime = (
        timedelta(days=current_app.config["REMEMBER_DAYS"])
        if remember else timedelta(hours=current_app.config["AUTH_HOURS"])
    )
    expires = datetime.now(timezone.utc) + lifetime
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("""
            INSERT INTO tokens (user_id, token, fingerprint_hash, expires_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, token_hash, device_fingerprint(device_secret),
              expires.strftime("%Y-%m-%d %H:%M:%S")))
        db.commit()

    session.clear()
    session["user_id"] = user_id
    session["user_name"] = user_name
    session["user_type"] = user_type
    session["user_level"] = user_level
    session.permanent = remember

    response = redirect(url_for("app.app_page"))
    secure = current_app.config["SESSION_COOKIE_SECURE"]
    max_age = int(lifetime.total_seconds()) if remember else None
    for name, value in ((AUTH_COOKIE, raw_token), (DEVICE_COOKIE, device_secret)):
        response.set_cookie(name, value, max_age=max_age, path="/", secure=secure,
                            httponly=True, samesite="Lax")
    return response


@app_bp.before_request
def require_authentication():
    user = get_authenticated_user()
    if user is None:
        return clear_auth_cookies(redirect(url_for("login.login_page")))
    g.user = user


@app_bp.route("/", methods=["GET"])
def app_page():
    tab = request.args.get("tab", "home")
    feed_mode = "following" if request.args.get("feed")=="following" else "for-you"
    if tab not in ("home", "explore", "map", "community", "impact", "profile", "workspace", "organizations", "messages", "leaderboard", "rewards", "people"):
        tab = "home"
    with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as db:
        db.row_factory = sqlite3.Row
        user = db.execute("""SELECT id, name, email, type, created, level, amount,
           country, state, city, postal_code, address, bio, headline,
           public_profile, leaderboard_opt_in, equipped_title_id, equipped_frame_id,
           equipped_accent_id, profile IS NOT NULL AS has_photo
           FROM users WHERE id=?""", (g.user["id"],)).fetchone()
        org = None
        if user["type"] in ("ong", "empresa"):
            table = "ngos" if user["type"] == "ong" else "companies"
            org = db.execute(f"SELECT * FROM {table} WHERE user_id=?", (user["id"],)).fetchone()
            if org is None:
                # Show editable blank organization fields even for an incomplete demo/profile.
                org = {col['name']: None for col in db.execute(f"PRAGMA table_info({table})")}
        campaigns = db.execute("""SELECT c.*, u.name AS ngo_name,
            COALESCE(n.public_name, n.legal_name, u.name) AS display_name,
            COALESCE((SELECT SUM(d.quantity) FROM donations d
                JOIN requests r ON r.id=d.request_id
                WHERE r.campaign_id=c.id AND d.status='confirmed'),0) AS progress
            FROM campaigns c JOIN users u ON u.id=c.ngo_user_id
            LEFT JOIN ngos n ON n.user_id=c.ngo_user_id
            WHERE c.status='open' AND u.active=1
            ORDER BY c.id DESC LIMIT 30""").fetchall()
        needs = db.execute("""SELECT r.*, u.name AS ngo_name,
            COALESCE(n.city,u.city) AS ngo_city, COALESCE(n.state,u.state) AS ngo_state,
            COALESCE(n.public_name,n.legal_name,u.name) AS display_name,
            COALESCE((SELECT SUM(d.quantity) FROM donations d
              WHERE d.request_id=r.id AND d.status='confirmed'),0) AS delivered,
            COALESCE((SELECT SUM(d.quantity) FROM donations d
              WHERE d.request_id=r.id AND d.status='pledged'),0) AS pledged,
            COALESCE((SELECT SUM(c.quantity) FROM claims c
              WHERE c.request_id=r.id AND c.status IN ('reserved','collected')),0) AS claimed
            FROM requests r JOIN users u ON u.id=r.ngo_user_id
            LEFT JOIN ngos n ON n.user_id=r.ngo_user_id
            WHERE r.status='open' AND u.active=1 ORDER BY r.id DESC LIMIT 200""").fetchall()
        offers = db.execute("""SELECT o.*, u.name AS donor_name, u.type AS donor_type,
           COALESCE(co.trade_name,co.legal_name,u.name) AS display_name
           FROM offers o JOIN users u ON u.id=o.donor_user_id
           LEFT JOIN companies co ON co.user_id=o.donor_user_id
           WHERE o.status='available' AND u.active=1 ORDER BY o.id DESC LIMIT 35""").fetchall()
        points = db.execute("""SELECT cp.*, COALESCE(n.public_name,n.legal_name,u.name) AS ngo_name
            FROM collection_points cp JOIN users u ON u.id=cp.ngo_user_id
            LEFT JOIN ngos n ON n.user_id=cp.ngo_user_id
            WHERE cp.active=1 AND u.active=1 ORDER BY cp.id DESC LIMIT 120""").fetchall()
        point_links = db.execute("""SELECT rp.request_id,rp.point_id FROM request_points rp
            JOIN collection_points p ON p.id=rp.point_id WHERE p.active=1""").fetchall()
        posts = db.execute("""SELECT p.*,u.name AS author_name,u.type AS author_type,
             COALESCE(n.public_name,n.legal_name,co.trade_name,co.legal_name,u.name) AS display_name
             FROM posts p JOIN users u ON u.id=p.author_user_id
             LEFT JOIN ngos n ON n.user_id=p.author_user_id
             LEFT JOIN companies co ON co.user_id=p.author_user_id
             WHERE u.active=1 AND (u.type!='pessoa' OR u.public_profile=1) ORDER BY p.id DESC LIMIT 60""").fetchall()
        orgs = db.execute("""SELECT u.id,u.type,u.name,u.city,u.state,
            CASE WHEN u.type='ong' THEN COALESCE(n.public_name,n.legal_name,u.name)
                 ELSE COALESCE(co.trade_name,co.legal_name,u.name) END AS display_name,
            CASE WHEN u.type='ong' THEN n.description ELSE co.description END AS description,
            CASE WHEN u.type='ong' THEN n.verified ELSE co.verified END AS verified
            FROM users u LEFT JOIN ngos n ON n.user_id=u.id
            LEFT JOIN companies co ON co.user_id=u.id
            WHERE u.type IN ('ong','empresa') AND u.active=1
            ORDER BY u.id DESC LIMIT 300""").fetchall()
        incoming = db.execute("""SELECT d.*,u.name AS donor_name,r.title AS request_title,
               o.title AS offer_title
            FROM donations d JOIN users u ON u.id=d.donor_user_id
            LEFT JOIN requests r ON r.id=d.request_id
            LEFT JOIN offers o ON o.id=d.offer_id
            WHERE d.ngo_user_id=? ORDER BY d.id DESC LIMIT 40""",(user["id"],)).fetchall()
        my_donations = db.execute("""SELECT d.*,COALESCE(n.public_name,n.legal_name,u.name) AS ngo_name,
                COALESCE(r.title,o.title) AS item_title
            FROM donations d JOIN users u ON u.id=d.ngo_user_id
            LEFT JOIN ngos n ON n.user_id=d.ngo_user_id
            LEFT JOIN requests r ON r.id=d.request_id
            LEFT JOIN offers o ON o.id=d.offer_id
            WHERE d.donor_user_id=? ORDER BY d.id DESC LIMIT 30""",(user["id"],)).fetchall()
        incoming_claims = db.execute("""SELECT c.*,u.name AS recipient_name,r.title AS item_title
            FROM claims c JOIN users u ON u.id=c.user_id
            JOIN requests r ON r.id=c.request_id
            WHERE r.ngo_user_id=? ORDER BY c.id DESC LIMIT 25""",(user["id"],)).fetchall()
        my_offers = db.execute("SELECT * FROM offers WHERE donor_user_id=? ORDER BY id DESC LIMIT 30", (user["id"],)).fetchall()
        my_claims = db.execute("""SELECT c.*,r.title AS item_title
            FROM claims c JOIN requests r ON r.id=c.request_id
            WHERE c.user_id=? ORDER BY c.id DESC LIMIT 20""", (user["id"],)).fetchall()
        messages = db.execute("""SELECT m.*,snd.name AS sender_name,rcv.name AS recipient_name,
              r.title AS related_title
              FROM messages m JOIN users snd ON snd.id=m.sender_user_id
              JOIN users rcv ON rcv.id=m.recipient_user_id
              LEFT JOIN requests r ON r.id=m.request_id
              WHERE m.sender_user_id=? OR m.recipient_user_id=?
              ORDER BY m.id DESC LIMIT 80""", (user["id"],user["id"])).fetchall()
        xp = db.execute("SELECT COALESCE(SUM(points),0) FROM impact_events WHERE user_id=?",(user["id"],)).fetchone()[0]
        badges = db.execute("""SELECT b.name,b.slug,CASE WHEN ub.user_id IS NULL THEN 0 ELSE 1 END AS earned
            FROM badges b LEFT JOIN user_badges ub ON ub.badge_slug=b.slug AND ub.user_id=?
            ORDER BY b.required_confirmed""",(user["id"],)).fetchall()
        my_points = db.execute("SELECT * FROM collection_points WHERE ngo_user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
        my_campaigns = db.execute("SELECT * FROM campaigns WHERE ngo_user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
        my_requests = db.execute("SELECT * FROM requests WHERE ngo_user_id=? ORDER BY id DESC",(user["id"],)).fetchall()
        # Social discovery, achievements and rankings: only confirmed physical donations count.
        rankings = db.execute("""SELECT u.id,u.name,u.type,
            COALESCE(c.trade_name,c.legal_name,u.name) AS display_name,
            rt.name AS active_title,rt.symbol AS active_symbol,
            COUNT(d.id) AS confirmed_count, COALESCE(SUM(d.quantity),0) AS units,
            u.level,u.public_profile,u.leaderboard_opt_in
            FROM users u
            JOIN donations d ON d.donor_user_id=u.id AND d.status='confirmed'
            LEFT JOIN companies c ON c.user_id=u.id
            LEFT JOIN ngo_rewards rt ON rt.id=u.equipped_title_id
            WHERE u.active=1 AND u.type IN ('empresa','pessoa')
              AND (u.type='empresa' OR u.leaderboard_opt_in=1)
            GROUP BY u.id ORDER BY confirmed_count DESC,units DESC,u.id ASC LIMIT 100""").fetchall()
        # New demo data may have donations but no impact_events; the ranking uses donations directly.
        totals = db.execute("""SELECT
            (SELECT COUNT(*) FROM users WHERE type='ong' AND active=1) AS nonprofits,
            (SELECT COUNT(*) FROM users WHERE type='empresa' AND active=1) AS businesses,
            (SELECT COUNT(*) FROM requests r JOIN users u ON u.id=r.ngo_user_id
              WHERE r.kind='need' AND u.type='ong' AND u.active=1) AS needs,
            (SELECT COUNT(*) FROM donations WHERE status='confirmed') AS confirmed""").fetchone()
        creators = db.execute("""SELECT u.id,u.name,u.type,u.headline,u.city,u.public_profile,
            COALESCE(n.public_name,n.legal_name,c.trade_name,c.legal_name,u.name) AS display_name,
            COALESCE(n.description,c.description,u.bio,'') AS description,
            COALESCE(n.verified,c.verified,0) AS verified,
            COALESCE((SELECT COUNT(*) FROM follows f WHERE f.followed_user_id=u.id),0) AS followers,
            EXISTS(SELECT 1 FROM follows f WHERE f.follower_user_id=? AND f.followed_user_id=u.id) AS following
            FROM users u LEFT JOIN ngos n ON n.user_id=u.id
            LEFT JOIN companies c ON c.user_id=u.id
            WHERE u.active=1 AND (u.type IN ('ong','empresa') OR
              (u.type='pessoa' AND u.public_profile=1))
            ORDER BY CASE u.type WHEN 'ong' THEN 0 WHEN 'empresa' THEN 1 ELSE 2 END,u.id DESC
            LIMIT 300""",(user['id'],)).fetchall()
        feed = db.execute("""SELECT p.id,p.author_user_id,p.body,p.created,p.tags,p.request_id,
            r.category AS request_category,r.status AS request_status,
            u.city AS author_city,u.type,u.name,
            EXISTS(SELECT 1 FROM post_images im WHERE im.post_id=p.id) AS has_image,
            COALESCE(n.public_name,n.legal_name,c.trade_name,c.legal_name,u.name) AS display_name,
            rt.name AS active_title,rt.symbol AS active_symbol,
            (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS likes,
            EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked,
            (SELECT COUNT(*) FROM post_comments cm WHERE cm.post_id=p.id) AS comments_count,
            EXISTS(SELECT 1 FROM follows f WHERE f.follower_user_id=? AND f.followed_user_id=p.author_user_id) AS following
            FROM posts p JOIN users u ON u.id=p.author_user_id
            LEFT JOIN ngos n ON n.user_id=u.id
            LEFT JOIN companies c ON c.user_id=u.id
            LEFT JOIN ngo_rewards rt ON rt.id=u.equipped_title_id
            LEFT JOIN requests r ON r.id=p.request_id
            WHERE u.active=1 AND (u.type!='pessoa' OR u.public_profile=1)
            ORDER BY p.created DESC,p.id DESC LIMIT 320""",(user['id'],user['id'])).fetchall()
        comments = db.execute("""SELECT cm.*,u.name AS author_name,u.type AS author_type,
          CASE WHEN u.type='pessoa' AND u.public_profile=0 THEN 'Community member'
               ELSE COALESCE(n.public_name,c.trade_name,u.name) END AS display_name
          FROM post_comments cm JOIN users u ON u.id=cm.user_id
          LEFT JOIN ngos n ON n.user_id=u.id LEFT JOIN companies c ON c.user_id=u.id
          WHERE u.active=1 AND cm.post_id IN
            (SELECT id FROM posts ORDER BY created DESC,id DESC LIMIT 70)
          ORDER BY cm.created ASC LIMIT 250""").fetchall()
        rewards = db.execute("""SELECT r.*,u.name AS ngo_name,
            COALESCE(n.public_name,n.legal_name,u.name) AS org_name,
            EXISTS(SELECT 1 FROM reward_unlocks x WHERE x.reward_id=r.id AND x.user_id=?) AS unlocked
          FROM ngo_rewards r JOIN users u ON u.id=r.ngo_user_id
          LEFT JOIN ngos n ON n.user_id=u.id
          WHERE r.active=1 AND u.active=1 ORDER BY r.id DESC LIMIT 120""",(user['id'],)).fetchall()
        my_rewards = db.execute("""SELECT r.*,n.public_name AS ngo_display FROM ngo_rewards r
          JOIN reward_unlocks x ON x.reward_id=r.id AND x.user_id=?
          LEFT JOIN ngos n ON n.user_id=r.ngo_user_id
          ORDER BY x.awarded DESC,r.id DESC""",(user['id'],)).fetchall()
        my_created_rewards = db.execute("SELECT * FROM ngo_rewards WHERE ngo_user_id=? ORDER BY id DESC",(user['id'],)).fetchall()
        followers_count = db.execute("SELECT COUNT(*) FROM follows WHERE followed_user_id=?",(user['id'],)).fetchone()[0]
        following_count = db.execute("SELECT COUNT(*) FROM follows WHERE follower_user_id=?",(user['id'],)).fetchone()[0]
        equipped = db.execute("""SELECT r.id,r.name,r.kind,r.color,r.symbol
          FROM ngo_rewards r WHERE r.id IN (?,?,?)""",
          (user['equipped_title_id'],user['equipped_frame_id'],user['equipped_accent_id'])).fetchall()
        # Rank at request time. We never store a hidden, opaque ranking per person.
        feed = ranked_feed(db, user, feed, feed_mode)
        pinned_topics = {r['tag'] for r in db.execute(
            'SELECT tag FROM user_pinned_topics WHERE user_id=?',(user['id'],)).fetchall()}
        pref=db.execute('SELECT personalized FROM user_feed_settings WHERE user_id=?',(user['id'],)).fetchone()
        personalization_enabled = bool(pref[0]) if pref else True
        # Thread list and selected thread, for a familiar chat experience.
        thread_peers = db.execute("""SELECT u.id,u.name,u.type,
            COALESCE(n.public_name,n.legal_name,c.trade_name,c.legal_name,u.name) AS display_name,
            (SELECT MAX(m.created) FROM messages m WHERE
               (m.sender_user_id=? AND m.recipient_user_id=u.id) OR
               (m.recipient_user_id=? AND m.sender_user_id=u.id)) AS latest
            FROM users u LEFT JOIN ngos n ON n.user_id=u.id
            LEFT JOIN companies c ON c.user_id=u.id WHERE u.active=1 AND u.id != ? AND
              (EXISTS(SELECT 1 FROM messages m WHERE (m.sender_user_id=? AND m.recipient_user_id=u.id)
               OR (m.recipient_user_id=? AND m.sender_user_id=u.id)) OR u.type IN ('ong','empresa'))
            ORDER BY latest IS NULL,latest DESC,u.id DESC LIMIT 90""",
            (user['id'],user['id'],user['id'],user['id'],user['id'])).fetchall()
        selected_peer = request.args.get('peer', type=int)
        valid_peers={r['id'] for r in thread_peers}
        if selected_peer not in valid_peers:
            selected_peer = thread_peers[0]['id'] if thread_peers else None
        conversation = db.execute("""SELECT m.*,u.name AS sender_name FROM messages m
            JOIN users u ON u.id=m.sender_user_id
            WHERE (m.sender_user_id=? AND m.recipient_user_id=?)
               OR (m.sender_user_id=? AND m.recipient_user_id=?)
            ORDER BY m.id DESC LIMIT 120""",
            (user['id'],selected_peer,selected_peer,user['id'])).fetchall()[::-1] if selected_peer else []

    links_by_point = {}
    for link in point_links:
        links_by_point.setdefault(link["point_id"], []).append(link["request_id"])
    map_points = [dict(id=p["id"], name=p["name"], address=p["address"],
        city=p["city"], state=p["state"], lat=p["latitude"], lng=p["longitude"],
        instructions=p["instructions"], ngo=p["ngo_name"],
        request_ids=links_by_point.get(p["id"], [])) for p in points]
    return render_template("app.html", tab=tab, user=user, org=org,
        map_points=map_points, has_photo=user["has_photo"], campaigns=campaigns, needs=needs,
        offers=offers, points=points, point_links=point_links, posts=posts,
        organizations=orgs, incoming=incoming, incoming_claims=incoming_claims,
        my_donations=my_donations, my_offers=my_offers, my_claims=my_claims,
        my_points=my_points, my_campaigns=my_campaigns, my_requests=my_requests,
        messages=messages, xp=xp, badges=badges, public_org=None, receipt=None,
        rankings=rankings, totals=totals, creators=creators, feed=feed,
        comments=comments, rewards=rewards, my_rewards=my_rewards,
        my_created_rewards=my_created_rewards, equipped=equipped,
        followers_count=followers_count, following_count=following_count,
        feed_mode=feed_mode, pinned_topics=pinned_topics, all_topics=POPULAR_TOPICS,
        personalization_enabled=personalization_enabled,
        thread_peers=thread_peers, selected_peer=selected_peer, conversation=conversation)


@app_bp.route("/organizations/<int:organization_id>", methods=["GET"])
def organization_page(organization_id):
    with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as db:
        db.row_factory = sqlite3.Row
        org = db.execute("""SELECT u.id,u.type,u.name,u.city,u.state,
            COALESCE(n.public_name,n.legal_name,co.trade_name,co.legal_name,u.name) AS display_name,
            CASE WHEN u.type='ong' THEN n.description ELSE co.description END AS description,
            CASE WHEN u.type='ong' THEN n.website ELSE co.website END AS website,
            CASE WHEN u.type='ong' THEN n.verified ELSE co.verified END AS verified,
            n.mission,n.cause,co.sector FROM users u
            LEFT JOIN ngos n ON n.user_id=u.id
            LEFT JOIN companies co ON co.user_id=u.id
            WHERE u.id=? AND u.type IN ('ong','empresa') AND u.active=1""",(organization_id,)).fetchone()
        if org is None:
            abort(404)
        org_posts = db.execute("""SELECT p.id,p.body,p.created,p.tags,p.request_id,
            EXISTS(SELECT 1 FROM post_images pi WHERE pi.post_id=p.id) AS has_image
            FROM posts p WHERE p.author_user_id=? ORDER BY p.id DESC LIMIT 12""",
            (organization_id,)).fetchall()
        org_campaigns = db.execute("SELECT * FROM campaigns WHERE ngo_user_id=? AND status='open' ORDER BY id DESC",(organization_id,)).fetchall()
        org_offers = db.execute("SELECT * FROM offers WHERE donor_user_id=? AND status='available' ORDER BY id DESC",(organization_id,)).fetchall()
        org_rewards=db.execute("SELECT * FROM ngo_rewards WHERE ngo_user_id=? AND active=1 ORDER BY id DESC",(organization_id,)).fetchall()
        org_stats=db.execute("""SELECT COUNT(*) AS confirmed_count,COALESCE(SUM(quantity),0) AS units
          FROM donations WHERE donor_user_id=? AND status='confirmed'""",(organization_id,)).fetchone()
        followers=db.execute("SELECT COUNT(*) FROM follows WHERE followed_user_id=?",(organization_id,)).fetchone()[0]
        following=db.execute("SELECT 1 FROM follows WHERE followed_user_id=? AND follower_user_id=?",(organization_id,g.user['id'])).fetchone() is not None

    return render_template("app.html", tab="organizations", public_org=org, org_posts=org_posts,
        org_campaigns=org_campaigns, org_offers=org_offers, org_rewards=org_rewards,
        org_stats=org_stats, public_followers=followers, public_following=following,
        user=g.user, org=None, has_photo=False, receipt=None)


@app_bp.route("/demo/receipt/<receipt_id>", methods=["GET"])
def demo_receipt(receipt_id):
    with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as db:
        db.row_factory = sqlite3.Row
        receipt=db.execute("""SELECT p.*,c.title AS campaign_title
            FROM demo_payments p JOIN campaigns c ON c.id=p.campaign_id
            WHERE p.id=? AND p.user_id=? AND p.is_demo=1""",
            (receipt_id,g.user["id"])).fetchone()
    if receipt is None:
        abort(404)
    return render_template("app.html",tab="impact",user=g.user,org=None,
        has_photo=False,public_org=None,receipt=receipt)


@app_bp.route("/avatar", methods=["GET"])
def avatar():
    with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as db:
        row = db.execute("SELECT profile FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    if not row or row[0] is None:
        return "Image not found", 404
    response = make_response(row[0])
    response.headers["Content-Type"] = "image/jpeg"
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response



# Only explicitly permitted profile fields may be changed by account holders.
PERSON_FIELDS = {"name": 120, "email": 254, "country": 100, "state": 120,
                 "city": 120, "postal_code": 20, "address": 255}
COMMON_ORG_FIELDS = {"legal_name": 180, "description": 2000, "tax_id": 100,
                     "website": 255, "phone": 80}
COMPANY_FIELDS = {"trade_name": 180, "sector": 180}
NGO_FIELDS = {"public_name": 180, "mission": 2000, "cause": 180}


@app_bp.route("/profile/field", methods=["POST"])
def update_field():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Invalid request."), 400
    field = payload.get("field")
    scope = payload.get("scope")
    value = payload.get("value")
    if not isinstance(value, str) or not isinstance(field, str):
        return jsonify(error="Invalid field."), 400
    value = value.strip()
    if scope == "user":
        allowed = PERSON_FIELDS
        if field not in allowed:
            return jsonify(error="Field not editable."), 400
        if len(value) > allowed[field]:
            return jsonify(error="Value is too long."), 400
        if field == "name" and len(value) < 2:
            return jsonify(error="Name must contain at least two characters."), 400
        if field == "email":
            value = value.lower()
            if not EMAIL_RE.fullmatch(value):
                return jsonify(error="Invalid email address."), 400
    elif scope == "organization":
        if g.user["type"] not in ("ong", "empresa"):
            return jsonify(error="This account has no organization profile."), 403
        allowed = {**COMMON_ORG_FIELDS, **(COMPANY_FIELDS if g.user["type"] == "empresa" else NGO_FIELDS)}
        if field not in allowed:
            return jsonify(error="Field not editable."), 400
        if len(value) > allowed[field]:
            return jsonify(error="Value is too long."), 400
        if field == "legal_name" and len(value) < 2:
            return jsonify(error="Enter a legal name of at least two characters."), 400
        if field == "website" and value and not value.startswith("https://"):
            return jsonify(error="Use a secure https:// website address."), 400
    else:
        return jsonify(error="Invalid profile section."), 400

    with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as db:
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if scope == "user":
                # Safe dynamic identifier: field is checked against hardcoded allowlist.
                db.execute(f"UPDATE users SET {field}=? WHERE id=?", (value or None, g.user["id"]))
            else:
                table = "companies" if g.user["type"] == "empresa" else "ngos"
                existing = db.execute(f"SELECT legal_name FROM {table} WHERE user_id=?", (g.user["id"],)).fetchone()
                if existing is None:
                    if field != "legal_name":
                        return jsonify(error="Save your organization's legal name first."), 400
                    db.execute(f"INSERT INTO {table} (user_id, legal_name) VALUES (?,?)", (g.user["id"], value))
                else:
                    db.execute(f"UPDATE {table} SET {field}=?, updated=CURRENT_TIMESTAMP WHERE user_id=?", (value or None, g.user["id"]))
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify(error="This email or tax ID is already registered."), 409
    if scope == "user" and field == "name":
        session["user_name"] = value
    return jsonify(ok=True, value=value)


@app_bp.route("/profile/photo", methods=["POST"])
def update_photo():
    upload = request.files.get("profile_photo")
    if not upload or not upload.filename:
        flash("Choose a profile photo.", "error")
        return redirect(url_for("app.app_page"))
    try:
        raw = upload.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Photo too large")
        Image.MAX_IMAGE_PIXELS = 16_000_000
        with Image.open(BytesIO(raw)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("Unsupported image format")
            im.load()
            resized = ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"), (320, 320))
            out = BytesIO()
            resized.save(out, format="JPEG", quality=85, optimize=True)
            image_data = out.getvalue()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        flash("Upload a JPG, PNG, or WebP photo under 2 MB.", "error")
        return redirect(url_for("app.app_page"))
    with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as db:
        db.execute("UPDATE users SET profile=? WHERE id=?", (image_data, g.user["id"]))
        db.commit()
    flash("Your photo has been updated.", "success")
    return redirect(url_for("app.app_page"))

# Community prototype — all writes are authenticated by @app_bp.before_request
# and CSRF-protected globally in main.py. Values are validated server-side.
CATEGORIES = {'food', 'clothing', 'hygiene', 'books', 'furniture', 'electronics', 'other'}
METHODS = {'dropoff', 'pickup', 'contact'}


def field_text(name, maximum=220, required=True):
    value = request.form.get(name, '').strip()
    if len(value) > maximum or (required and not value):
        raise ValueError(f'Please check {name.replace("_", " ")}.')
    return value


def positive_int(name, limit=100000):
    try:
        value = int(request.form.get(name, ''))
        if 1 <= value <= limit:
            return value
    except (TypeError, ValueError):
        pass
    raise ValueError(f'Enter a valid {name.replace("_", " ")}.')


def require_role(*roles):
    if g.user['type'] not in roles:
        abort(403, description='This action is not available to this account type.')


def fail_and_back(error, tab='workspace'):
    flash(str(error), 'error')
    return redirect(url_for('app.app_page', tab=tab))


@app_bp.route('/campaigns/create', methods=['POST'])
def create_campaign():
    require_role('ong')
    try:
        title = field_text('title', 140)
        description = field_text('description', 1600)
        category = field_text('category', 30)
        if category not in CATEGORIES:
            raise ValueError('Choose a category.')
        quantity = positive_int('target_quantity')
        unit = field_text('unit', 30)
        money = int(request.form.get('allow_money_demo') == 'on')
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            db.execute('''INSERT INTO campaigns
               (ngo_user_id,title,description,category,target_quantity,unit,allow_money_demo)
               VALUES (?,?,?,?,?,?,?)''',
               (g.user['id'],title,description,category,quantity,unit,money))
            db.commit()
        flash('Campaign published.', 'success')
    except ValueError as exc:
        return fail_and_back(exc)
    return redirect(url_for('app.app_page', tab='workspace'))


@app_bp.route('/collection-points/create', methods=['POST'])
def create_collection_point():
    require_role('ong')
    try:
        name = field_text('name', 120)
        address = field_text('address', 250)
        city = field_text('city', 100)
        state = field_text('state', 100)
        postal_code = field_text('postal_code', 20, False)
        instructions = field_text('instructions', 600, False)
        lat = float(field_text('latitude', 30))
        lng = float(field_text('longitude', 30))
        import math
        if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError('Select valid map coordinates.')
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            db.execute('''INSERT INTO collection_points
              (ngo_user_id,name,address,city,state,postal_code,latitude,longitude,instructions)
              VALUES (?,?,?,?,?,?,?,?,?)''',
              (g.user['id'],name,address,city,state,postal_code,lat,lng,instructions))
            db.commit()
        flash('Collection point published.', 'success')
    except (TypeError, ValueError) as exc:
        return fail_and_back(exc)
    return redirect(url_for('app.app_page', tab='workspace'))


@app_bp.route('/requests/create', methods=['POST'])
def create_request():
    require_role('ong')
    try:
        title = field_text('title', 140)
        description = field_text('description', 1600)
        kind = field_text('kind', 20)
        category = field_text('category', 30)
        quantity = positive_int('quantity')
        unit = field_text('unit', 30)
        if kind not in ('need', 'giveaway') or category not in CATEGORIES:
            raise ValueError('Invalid listing category or type.')
        allow_dropoff = int(request.form.get('allow_dropoff') == 'on')
        allow_pickup = int(request.form.get('allow_pickup') == 'on')
        allow_contact = int(request.form.get('allow_contact') == 'on')
        allow_claims = int(kind == 'giveaway' and request.form.get('allow_claims') == 'on')
        if not (allow_dropoff or allow_pickup or allow_contact or allow_claims):
            raise ValueError('Select at least one delivery/contact method.')
        campaign_id = request.form.get('campaign_id') or None
        points_raw = request.form.getlist('point_ids')
        point_ids = list(set(positive_int_value(v, 'point') for v in points_raw))
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            db.execute('PRAGMA foreign_keys=ON')
            if campaign_id:
                campaign_id = positive_int_value(campaign_id, 'campaign')
                match=db.execute('SELECT id FROM campaigns WHERE id=? AND ngo_user_id=? AND status="open"',
                                 (campaign_id,g.user['id'])).fetchone()
                if match is None:
                    raise ValueError('Invalid campaign selection.')
            if allow_dropoff and not point_ids:
                raise ValueError('Choose at least one collection point for drop-off, or disable drop-off.')
            for point_id in point_ids:
                if db.execute('SELECT 1 FROM collection_points WHERE id=? AND ngo_user_id=? AND active=1',
                              (point_id,g.user['id'])).fetchone() is None:
                    raise ValueError('Invalid collection point selection.')
            cursor=db.execute('''INSERT INTO requests
              (ngo_user_id,campaign_id,kind,title,description,category,quantity,unit,
               allow_dropoff,allow_pickup,allow_contact,allow_claims)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
              (g.user['id'],campaign_id,kind,title,description,category,quantity,unit,
               allow_dropoff,allow_pickup,allow_contact,allow_claims))
            for point_id in point_ids:
                db.execute('INSERT INTO request_points(request_id,point_id) VALUES (?,?)',
                           (cursor.lastrowid,point_id))
            db.commit()
        flash('Listing published.', 'success')
    except ValueError as exc:
        return fail_and_back(exc)
    return redirect(url_for('app.app_page', tab='workspace'))


def positive_int_value(value, label):
    try:
        result=int(value)
    except (TypeError, ValueError):
        raise ValueError(f'Invalid {label}.')
    if result <= 0 or result > 1_000_000_000:
        raise ValueError(f'Invalid {label}.')
    return result


@app_bp.route('/offers/create', methods=['POST'])
def create_offer():
    require_role('pessoa','empresa')
    try:
        title=field_text('title',140)
        description=field_text('description',1500)
        category=field_text('category',30)
        quantity=positive_int('quantity')
        unit=field_text('unit',30)
        if category not in CATEGORIES:
            raise ValueError('Choose a valid category.')
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            db.execute('''INSERT INTO offers
              (donor_user_id,title,description,category,quantity,unit)
              VALUES (?,?,?,?,?,?)''',
              (g.user['id'],title,description,category,quantity,unit))
            db.commit()
        flash('Your offer is now visible to nonprofits.', 'success')
    except ValueError as exc:
        return fail_and_back(exc,'explore')
    return redirect(url_for('app.app_page', tab='explore'))


@app_bp.route('/posts/create', methods=['POST'])
def create_post():
    require_role('ong','empresa','pessoa')
    try:
        body=field_text('body',1200)
        raw_tags=request.form.get('tags','')[:200]
        image_upload=request.files.get('photo')
        image_jpg=None
        if image_upload and image_upload.filename:
            data=image_upload.read(2_000_001)
            if len(data)>2_000_000: raise ValueError('Use an image smaller than 2 MB.')
            try:
                with Image.open(BytesIO(data)) as im:
                    Image.MAX_IMAGE_PIXELS=12_000_000
                    if im.width*im.height>12_000_000: raise ValueError('Photo has too many pixels.')
                    im=ImageOps.exif_transpose(im).convert('RGB')
                    im.thumbnail((1400,1400))
                    out=BytesIO(); im.save(out,'JPEG',quality=82,optimize=True)
                    image_jpg=out.getvalue()
            except (UnidentifiedImageError,OSError) as exc:
                raise ValueError('Upload a valid JPG, PNG or WebP image.') from exc
        selected_request=request.form.get('request_id','').strip()
        linked_request=None
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            db.execute('PRAGMA foreign_keys=ON')
            if g.user['type']=='pessoa':
                setting=db.execute('SELECT public_profile FROM users WHERE id=?',(g.user['id'],)).fetchone()
                if not setting or not setting[0]:
                    raise ValueError('Enable your public profile before posting.')
            if selected_request:
                if g.user['type']!='ong':raise ValueError('Only nonprofits can link a request to a post.')
                row=db.execute('SELECT id,category FROM requests WHERE id=? AND ngo_user_id=? AND status=?',
                               (selected_request,g.user['id'],'open')).fetchone()
                if row is None: raise ValueError('Select one of your open requests.')
                linked_request=int(row[0]); category=row[1]
            else: category=None
            tags=tags_for(body,raw_tags,category)
            cur=db.execute('INSERT INTO posts(author_user_id,body,tags,request_id) VALUES (?,?,?,?)',
                           (g.user['id'],body,','.join(tags),linked_request))
            if image_jpg:
                db.execute('INSERT INTO post_images(post_id,image_data,mime) VALUES (?,?,?)',
                           (cur.lastrowid,image_jpg,'image/jpeg'))
            db.commit()
        flash('Your story was published.', 'success')
    except ValueError as exc:
        return fail_and_back(exc,'community')
    return redirect(url_for('app.app_page', tab='community'))


@app_bp.route('/requests/<int:request_id>/pledge', methods=['POST'])
def pledge_donation(request_id):
    require_role('pessoa','empresa')
    try:
        qty=positive_int('quantity')
        method=field_text('method',20)
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            item=db.execute('''SELECT r.id,u.active FROM requests r JOIN users u ON u.id=r.ngo_user_id
                WHERE r.id=? AND r.kind='need' AND r.status='open' ''',(request_id,)).fetchone()
            if item is None or not item[-1]:
                raise ValueError('This request is no longer available.')
            # Accessing explicit columns by name is safer if the schema grows.
            db.row_factory=sqlite3.Row
            item=db.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
            allowed={'dropoff':item['allow_dropoff'], 'pickup':item['allow_pickup'], 'contact':item['allow_contact']}
            if method not in METHODS or not allowed.get(method):
                raise ValueError('Choose an accepted delivery method.')
            taken=db.execute('''SELECT COALESCE(SUM(quantity),0) FROM donations
               WHERE request_id=? AND status IN ('pledged','confirmed')''',(request_id,)).fetchone()[0]
            if taken+qty>item['quantity']:
                raise ValueError('The requested quantity exceeds the remaining need.')
            db.execute('''INSERT INTO donations(donor_user_id,ngo_user_id,request_id,quantity,method)
              VALUES (?,?,?,?,?)''',(g.user['id'],item['ngo_user_id'],request_id,qty,method))
            db.commit()
        flash('Donation offered. The nonprofit will confirm receipt.', 'success')
    except ValueError as exc:
        return fail_and_back(exc,'explore')
    return redirect(url_for('app.app_page', tab='map', request=request_id) if method == 'dropoff' else url_for('app.app_page',tab='explore'))


@app_bp.route('/requests/<int:request_id>/claim', methods=['POST'])
def claim_items(request_id):
    require_role('pessoa')
    try:
        qty=positive_int('quantity')
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            db.row_factory=sqlite3.Row
            item=db.execute("SELECT * FROM requests WHERE id=? AND kind='giveaway' AND status='open' AND allow_claims=1",(request_id,)).fetchone()
            if item is None:
                raise ValueError('This listing does not accept pickup requests.')
            already=db.execute("SELECT 1 FROM claims WHERE request_id=? AND user_id=? AND status IN ('reserved','collected')",
                               (request_id,g.user['id'])).fetchone()
            if already:
                raise ValueError('You already submitted a request for this listing.')
            reserved=db.execute("SELECT COALESCE(SUM(quantity),0) FROM claims WHERE request_id=? AND status IN ('reserved','collected')",(request_id,)).fetchone()[0]
            if reserved+qty>item['quantity']:
                raise ValueError('Not enough items remain available.')
            db.execute('INSERT INTO claims(request_id,user_id,quantity) VALUES (?,?,?)',
                       (request_id,g.user['id'],qty))
            db.commit()
        flash('Pickup requested. The nonprofit will coordinate collection.', 'success')
    except ValueError as exc:
        return fail_and_back(exc,'explore')
    return redirect(url_for('app.app_page', tab='explore'))


@app_bp.route('/offers/<int:offer_id>/accept', methods=['POST'])
def accept_offer(offer_id):
    require_role('ong')
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        db.row_factory=sqlite3.Row
        offer=db.execute("SELECT * FROM offers WHERE id=? AND status='available'",(offer_id,)).fetchone()
        if offer is None or offer['donor_user_id']==g.user['id']:
            return fail_and_back('Offer unavailable.','explore')
        db.execute("UPDATE offers SET status='reserved',ngo_user_id=? WHERE id=?",
                   (g.user['id'],offer_id))
        db.execute('''INSERT INTO donations
          (donor_user_id,ngo_user_id,offer_id,quantity,method)
          VALUES (?,?,?,?, 'offer')''',
          (offer['donor_user_id'],g.user['id'],offer_id,offer['quantity']))
        db.commit()
    flash('Offer reserved. Coordinate handover before confirmation.', 'success')
    return redirect(url_for('app.app_page', tab='workspace'))


@app_bp.route('/donations/<int:donation_id>/confirm', methods=['POST'])
def confirm_donation(donation_id):
    require_role('ong')
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        db.row_factory=sqlite3.Row
        donation=db.execute('''SELECT * FROM donations
          WHERE id=? AND ngo_user_id=? AND status='pledged' ''',
          (donation_id,g.user['id'])).fetchone()
        if donation is None:
            return fail_and_back('Donation not found or already processed.')
        db.execute("UPDATE donations SET status='confirmed',confirmed=CURRENT_TIMESTAMP WHERE id=?",(donation_id,))
        if donation['offer_id']:
            db.execute("UPDATE offers SET status='delivered' WHERE id=? AND ngo_user_id=?",
                       (donation['offer_id'],g.user['id']))
        db.execute('INSERT OR IGNORE INTO impact_events(user_id,donation_id,points) VALUES(?,?,?)',
                   (donation['donor_user_id'],donation_id,50))
        stats=db.execute("SELECT COUNT(*), COALESCE(SUM(points),0) FROM impact_events WHERE user_id=?",
                         (donation['donor_user_id'],)).fetchone()
        count,xp=stats[0],stats[1]
        db.execute('UPDATE users SET amount=?, level=? WHERE id=?',
                   (count,1+(xp//150),donation['donor_user_id']))
        db.execute('''INSERT OR IGNORE INTO user_badges(user_id,badge_slug)
          SELECT ?,slug FROM badges WHERE required_confirmed <= ?''',
          (donation['donor_user_id'],count))
        # NGO-created cosmetic rewards unlock after verified delivery, never on pledges or demos.
        db.execute("""INSERT OR IGNORE INTO reward_unlocks(user_id,reward_id)
           SELECT ?,r.id FROM ngo_rewards r
           WHERE r.ngo_user_id=? AND r.active=1 AND r.min_confirmed <=
           (SELECT COUNT(*) FROM donations d WHERE d.donor_user_id=?
              AND d.ngo_user_id=? AND d.status='confirmed')""",
           (donation['donor_user_id'],g.user['id'],donation['donor_user_id'],g.user['id']))
        db.commit()
    flash('Delivery confirmed. XP and eligible community rewards unlocked.', 'success')
    return redirect(url_for('app.app_page', tab='workspace'))


@app_bp.route('/claims/<int:claim_id>/confirm', methods=['POST'])
def confirm_claim(claim_id):
    require_role('ong')
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.execute('BEGIN IMMEDIATE')
        cursor=db.execute('''UPDATE claims SET status='collected' WHERE id=? AND status='reserved'
             AND request_id IN (SELECT id FROM requests WHERE ngo_user_id=?)''',
             (claim_id,g.user['id']))
        db.commit()
        if cursor.rowcount == 0:
            flash('Pickup is not available for confirmation.', 'error')
        else:
            flash('Collection confirmed.', 'success')
    return redirect(url_for('app.app_page', tab='workspace'))


@app_bp.route('/donations/demo', methods=['POST'])
def demo_donation():
    require_role('empresa')
    try:
        campaign_id=positive_int('campaign_id')
        amount=positive_int('amount', 10000)
        if amount not in (10,25,50,100):
            raise ValueError('Choose a supported demo amount.')
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            if db.execute('''SELECT 1 FROM campaigns c JOIN users u ON u.id=c.ngo_user_id
                 WHERE c.id=? AND c.status='open' AND c.allow_money_demo=1 AND u.active=1''',
                 (campaign_id,)).fetchone() is None:
                raise ValueError('This campaign does not allow demo financial support.')
            receipt_id=secrets.token_urlsafe(18)
            db.execute('''INSERT INTO demo_payments(id,user_id,campaign_id,amount_cents,is_demo)
                  VALUES (?,?,?,?,1)''',(receipt_id,g.user['id'],campaign_id,amount*100))
            db.commit()
        return redirect(url_for('app.demo_receipt',receipt_id=receipt_id))
    except ValueError as exc:
        return fail_and_back(exc,'explore')


@app_bp.route('/messages/send', methods=['POST'])
def send_message():
    try:
        recipient_id=positive_int('recipient_id',1_000_000_000)
        body=field_text('body',1000)
        related=request.form.get('request_id','').strip()
        request_id=positive_int_value(related,'request') if related else None
        if recipient_id==g.user['id']:
            raise ValueError('You cannot send a message to yourself.')
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.row_factory=sqlite3.Row
            recipient=db.execute('SELECT id,type FROM users WHERE id=? AND active=1',
                                 (recipient_id,)).fetchone()
            if recipient is None:
                raise ValueError('Recipient is unavailable.')
            if request_id is not None:
                item=db.execute("SELECT ngo_user_id,allow_contact FROM requests WHERE id=? AND status='open'",
                                (request_id,)).fetchone()
                if item is None or item['ngo_user_id'] != recipient_id or not item['allow_contact']:
                    raise ValueError('Contact is not enabled for this request.')
            if recipient['type'] not in ('ong','empresa'):
                prior=db.execute("""SELECT 1 FROM messages WHERE sender_user_id=? AND recipient_user_id=?
                    UNION SELECT 1 FROM donations WHERE donor_user_id=? AND ngo_user_id=?
                    LIMIT 1""",(recipient_id,g.user['id'],recipient_id,g.user['id'])).fetchone()
                if prior is None:
                    raise ValueError('You can message a donor after they contact you or commit to your nonprofit.')
            recent=db.execute("SELECT COUNT(*) FROM messages WHERE sender_user_id=? AND created>=datetime('now','-1 minute')",(g.user['id'],)).fetchone()[0]
            if recent>=5:
                raise ValueError('Too many messages. Please try again shortly.')
            db.execute('INSERT INTO messages(sender_user_id,recipient_user_id,request_id,body) VALUES (?,?,?,?)',
                       (g.user['id'],recipient_id,request_id,body))
            db.commit()
        flash('Your message was sent.', 'success')
        return redirect(url_for('app.app_page',tab='messages'))
    except ValueError as exc:
        return fail_and_back(exc,'messages')


@app_bp.route('/donations/<int:donation_id>/cancel', methods=['POST'])
def cancel_donation(donation_id):
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.execute('BEGIN IMMEDIATE')
        db.row_factory=sqlite3.Row
        donation=db.execute("SELECT * FROM donations WHERE id=? AND status='pledged'",(donation_id,)).fetchone()
        if donation is None or g.user['id'] not in (donation['donor_user_id'],donation['ngo_user_id']):
            flash('The commitment cannot be cancelled.', 'error')
        else:
            db.execute("UPDATE donations SET status='cancelled' WHERE id=?",(donation_id,))
            if donation['offer_id']:
                db.execute("UPDATE offers SET status='available',ngo_user_id=NULL WHERE id=? AND status='reserved'",(donation['offer_id'],))
            db.commit()
            flash('Donation commitment cancelled.', 'success')
    return redirect(url_for('app.app_page',tab='workspace' if g.user['type']=='ong' else 'impact'))


@app_bp.route('/claims/<int:claim_id>/cancel', methods=['POST'])
def cancel_claim(claim_id):
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.execute('BEGIN IMMEDIATE')
        db.row_factory=sqlite3.Row
        claim=db.execute("""SELECT c.*,r.ngo_user_id FROM claims c
              JOIN requests r ON r.id=c.request_id
              WHERE c.id=? AND c.status='reserved'""",(claim_id,)).fetchone()
        if claim is None or g.user['id'] not in (claim['user_id'],claim['ngo_user_id']):
            flash('Pickup request cannot be cancelled.', 'error')
        else:
            db.execute("UPDATE claims SET status='cancelled' WHERE id=?",(claim_id,))
            db.commit()
            flash('Pickup request cancelled.', 'success')
    return redirect(url_for('app.app_page',tab='workspace' if g.user['type']=='ong' else 'impact'))


@app_bp.route('/requests/<int:request_id>/close', methods=['POST'])
def close_request(request_id):
    require_role('ong')
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        result = db.execute("""UPDATE requests SET status='closed'
            WHERE id=? AND ngo_user_id=? AND status='open'""",
            (request_id, g.user['id']))
        db.commit()
    flash('Request closed.' if result.rowcount else 'Request not available.',
          'success' if result.rowcount else 'error')
    return redirect(url_for('app.app_page', tab='workspace'))


@app_bp.route('/requests/<int:request_id>/update', methods=['POST'])
def update_request(request_id):
    """NGO may correct a live listing without invalidating existing commitments."""
    require_role('ong')
    try:
        title = field_text('title', 140)
        description = field_text('description', 1600)
        quantity = positive_int('quantity')
        unit = field_text('unit', 30)
        category = field_text('category', 30)
        if category not in CATEGORIES:
            raise ValueError('Choose a valid category.')
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            db.execute('BEGIN IMMEDIATE')
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT id,kind FROM requests WHERE id=? AND ngo_user_id=? AND status='open'",
                             (request_id,g.user['id'])).fetchone()
            if row is None:
                raise ValueError('Only your open requests can be edited.')
            if row['kind']=='need':
                committed = db.execute("""SELECT COALESCE(SUM(quantity),0) FROM donations
                    WHERE request_id=? AND status IN ('pledged','confirmed')""",
                    (request_id,)).fetchone()[0]
            else:
                committed = db.execute("""SELECT COALESCE(SUM(quantity),0) FROM claims
                    WHERE request_id=? AND status IN ('reserved','collected')""",
                    (request_id,)).fetchone()[0]
            if quantity < committed:
                raise ValueError(f'Quantity cannot be less than {committed} already committed items.')
            db.execute("""UPDATE requests SET title=?,description=?,category=?,quantity=?,unit=?
                WHERE id=? AND ngo_user_id=?""",
                (title,description,category,quantity,unit,request_id,g.user['id']))
            db.commit()
        flash('Request updated.', 'success')
    except ValueError as error:
        return fail_and_back(error)
    return redirect(url_for('app.app_page',tab='workspace'))


@app_bp.route('/requests/<int:request_id>/points', methods=['POST'])
def update_request_points(request_id):
    """Only let the NGO assign its own active collection points to a request."""
    require_role('ong')
    try:
        ids = set(positive_int_value(value,'collection point') for value in request.form.getlist('point_ids'))
        with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            db.row_factory = sqlite3.Row
            row = db.execute("""SELECT id,allow_dropoff FROM requests
                WHERE id=? AND ngo_user_id=? AND status='open'""",
                (request_id,g.user['id'])).fetchone()
            if row is None:
                raise ValueError('This request cannot be edited.')
            if row['allow_dropoff'] and not ids:
                raise ValueError('Choose a point for drop-off, or close this listing and create one with different handover options.')
            for point_id in ids:
                point = db.execute("""SELECT id FROM collection_points
                    WHERE id=? AND ngo_user_id=? AND active=1""",
                    (point_id,g.user['id'])).fetchone()
                if point is None:
                    raise ValueError('One of the collection points is not yours or is inactive.')
            db.execute('DELETE FROM request_points WHERE request_id=?',(request_id,))
            for point_id in ids:
                db.execute('INSERT INTO request_points(request_id,point_id) VALUES(?,?)',
                           (request_id,point_id))
            db.commit()
        flash('Collection points updated.', 'success')
    except ValueError as error:
        return fail_and_back(error)
    return redirect(url_for('app.app_page',tab='workspace'))

# ---- Social profiles, community and nonprofit-created cosmetics ----
@app_bp.route('/people/<int:person_id>')
def person_page(person_id):
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.row_factory=sqlite3.Row
        person=db.execute('''SELECT id,name,headline,bio,city,state,created,level,amount,
                 public_profile,leaderboard_opt_in,profile IS NOT NULL AS has_photo,
                 equipped_title_id,equipped_frame_id,equipped_accent_id
                 FROM users WHERE id=? AND type='pessoa' AND active=1''',(person_id,)).fetchone()
        if not person or (not person['public_profile'] and person_id != g.user['id']):
            abort(404)
        stats=db.execute('''SELECT COUNT(*) AS confirmed_count,COALESCE(SUM(quantity),0) AS units
              FROM donations WHERE donor_user_id=? AND status='confirmed' ''',(person_id,)).fetchone()
        earned=db.execute('''SELECT r.*,n.public_name AS org_name FROM reward_unlocks x
              JOIN ngo_rewards r ON r.id=x.reward_id LEFT JOIN ngos n ON n.user_id=r.ngo_user_id
              WHERE x.user_id=? ORDER BY x.awarded DESC LIMIT 40''',(person_id,)).fetchall()
        posts=db.execute('SELECT id,body,created FROM posts WHERE author_user_id=? ORDER BY id DESC LIMIT 20',(person_id,)).fetchall()
        followers=db.execute('SELECT COUNT(*) FROM follows WHERE followed_user_id=?',(person_id,)).fetchone()[0]
        following=db.execute('SELECT 1 FROM follows WHERE follower_user_id=? AND followed_user_id=?',(g.user['id'],person_id)).fetchone() is not None
        equipped=db.execute('''SELECT r.id,r.name,r.kind,r.symbol,r.color FROM ngo_rewards r WHERE r.id IN (?,?,?)''',
              (person['equipped_title_id'],person['equipped_frame_id'],person['equipped_accent_id'])).fetchall()
    return render_template('app.html', tab='people', public_person=person, person_stats=stats,
         person_rewards=earned, person_posts=posts, public_followers=followers,
         public_following=following, public_equipped=equipped, user=g.user,
         public_org=None, receipt=None)


@app_bp.route('/users/<int:user_id>/avatar')
def user_avatar(user_id):
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        result=db.execute('SELECT type,public_profile,profile FROM users WHERE id=? AND active=1',(user_id,)).fetchone()
    if result is None or result[2] is None or (result[0]=='pessoa' and not result[1] and user_id!=g.user['id']):
        abort(404)
    response=make_response(result[2])
    response.headers['Content-Type']='image/jpeg'
    response.headers['Cache-Control']='private, no-store'
    return response


@app_bp.route('/social/profile',methods=['POST'])
def update_social_profile():
    headline=request.form.get('headline','').strip()
    bio=request.form.get('bio','').strip()
    if len(headline)>90 or len(bio)>600:
        return fail_and_back('Profile details are too long.','profile')
    public=int(request.form.get('public_profile')=='on')
    ranked=int(request.form.get('leaderboard_opt_in')=='on' and public==1)
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.execute('UPDATE users SET headline=?,bio=?,public_profile=?,leaderboard_opt_in=? WHERE id=?',
          (headline,bio,public,ranked,g.user['id']))
        db.commit()
    flash('Your social profile was updated.','success')
    return redirect(url_for('app.app_page',tab='profile'))


@app_bp.route('/social/follow/<int:target_id>',methods=['POST'])
def follow_account(target_id):
    if target_id==g.user['id']:
        return fail_and_back('You cannot follow yourself.','organizations')
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.row_factory=sqlite3.Row
        target=db.execute('SELECT id,type,public_profile FROM users WHERE id=? AND active=1',(target_id,)).fetchone()
        if not target or (target['type']=='pessoa' and not target['public_profile']):
            abort(404)
        exists=db.execute('SELECT 1 FROM follows WHERE follower_user_id=? AND followed_user_id=?',
                          (g.user['id'],target_id)).fetchone()
        if exists:
            db.execute('DELETE FROM follows WHERE follower_user_id=? AND followed_user_id=?',(g.user['id'],target_id))
        else:
            db.execute('INSERT INTO follows(follower_user_id,followed_user_id) VALUES(?,?)',(g.user['id'],target_id))
        db.commit()
    origin=request.form.get('back','')
    if origin=='person' and target['type']=='pessoa': return redirect(url_for('app.person_page',person_id=target_id))
    if origin=='organization' and target['type'] in ('ong','empresa'): return redirect(url_for('app.organization_page',organization_id=target_id))
    return redirect(url_for('app.app_page',tab='organizations'))


@app_bp.route('/social/posts/<int:post_id>/like',methods=['POST'])
def like_post(post_id):
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        visible=db.execute('''SELECT 1 FROM posts p JOIN users u ON u.id=p.author_user_id
                 WHERE p.id=? AND u.active=1 AND (u.type!='pessoa' OR u.public_profile=1)''',(post_id,)).fetchone()
        if not visible: abort(404)
        if db.execute('SELECT 1 FROM post_likes WHERE post_id=? AND user_id=?',(post_id,g.user['id'])).fetchone():
            db.execute('DELETE FROM post_likes WHERE post_id=? AND user_id=?',(post_id,g.user['id']))
        else:
            db.execute('INSERT INTO post_likes(post_id,user_id) VALUES(?,?)',(post_id,g.user['id']))
            post=db.execute('SELECT body,tags FROM posts WHERE id=?',(post_id,)).fetchone()
            add_affinity(db,g.user['id'],tags_for(post[0],post[1]),2.5)
        db.commit()
    return redirect(url_for('app.app_page',tab='community')+'#post-'+str(post_id))


@app_bp.route('/social/posts/<int:post_id>/comment',methods=['POST'])
def comment_post(post_id):
    body=request.form.get('body','').strip()
    if not (1<=len(body)<=500): return fail_and_back('Comments must be 1–500 characters.','community')
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        visible=db.execute('''SELECT 1 FROM posts p JOIN users u ON u.id=p.author_user_id
                 WHERE p.id=? AND u.active=1 AND (u.type!='pessoa' OR u.public_profile=1)''',(post_id,)).fetchone()
        if not visible:abort(404)
        frequency=db.execute('''SELECT COUNT(*) FROM post_comments WHERE user_id=?
                        AND created>=datetime('now','-10 minutes')''',(g.user['id'],)).fetchone()[0]
        if frequency>=15:return fail_and_back('Please wait before commenting again.','community')
        db.execute('INSERT INTO post_comments(post_id,user_id,body) VALUES(?,?,?)',(post_id,g.user['id'],body))
        post=db.execute('SELECT body,tags FROM posts WHERE id=?',(post_id,)).fetchone()
        add_affinity(db,g.user['id'],tags_for(post[0],post[1]),2.0)
        db.commit()
    return redirect(url_for('app.app_page',tab='community')+'#post-'+str(post_id))


@app_bp.route('/rewards/create',methods=['POST'])
def create_ngo_reward():
    require_role('ong')
    name=request.form.get('name','').strip()
    description=request.form.get('description','').strip()
    kind=request.form.get('kind','')
    color=request.form.get('color','violet')
    symbol=request.form.get('symbol','✦').strip()
    try:min_confirmed=int(request.form.get('min_confirmed','1'))
    except ValueError:min_confirmed=0
    if (not 3<=len(name)<=46 or len(description)>200 or kind not in ('title','frame','accent')
        or color not in ('violet','mint','gold','coral','sky') or not 1<=len(symbol)<=4
        or not 1<=min_confirmed<=50):
        return fail_and_back('Check your title, color and unlock requirement.','rewards')
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.execute('PRAGMA foreign_keys=ON')
        if db.execute('SELECT COUNT(*) FROM ngo_rewards WHERE ngo_user_id=?',(g.user['id'],)).fetchone()[0]>=18:
            return fail_and_back('Maximum 18 rewards per nonprofit.','rewards')
        cursor=db.execute('''INSERT INTO ngo_rewards
            (ngo_user_id,name,description,kind,color,symbol,min_confirmed)
            VALUES (?,?,?,?,?,?,?)''',(g.user['id'],name,description,kind,color,symbol,min_confirmed))
        # Also unlock for donors whose deliveries were confirmed before the reward was created.
        db.execute('''INSERT OR IGNORE INTO reward_unlocks(user_id,reward_id)
             SELECT d.donor_user_id,? FROM donations d
             WHERE d.ngo_user_id=? AND d.status='confirmed'
             GROUP BY d.donor_user_id HAVING COUNT(*)>=?''',
             (cursor.lastrowid,g.user['id'],min_confirmed))
        db.commit()
    flash('Community reward published. Eligible supporters can now equip it.','success')
    return redirect(url_for('app.app_page',tab='rewards'))


@app_bp.route('/rewards/equip',methods=['POST'])
def equip_reward():
    try:reward_id=int(request.form.get('reward_id','0'))
    except ValueError:return fail_and_back('Invalid cosmetic.','rewards')
    kind=request.form.get('kind','')
    columns={'title':'equipped_title_id','frame':'equipped_frame_id','accent':'equipped_accent_id'}
    if kind not in columns:return fail_and_back('Invalid cosmetic type.','rewards')
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.execute('PRAGMA foreign_keys=ON')
        if reward_id:
            valid=db.execute('''SELECT 1 FROM reward_unlocks x
                JOIN ngo_rewards r ON r.id=x.reward_id
                WHERE x.user_id=? AND x.reward_id=? AND r.kind=? AND r.active=1''',
                (g.user['id'],reward_id,kind)).fetchone()
            if not valid:return fail_and_back('You have not unlocked this reward.','rewards')
        db.execute(f'UPDATE users SET {columns[kind]}=? WHERE id=?',
                   (reward_id or None,g.user['id']))
        db.commit()
    flash('Profile cosmetic updated!','success')
    return redirect(url_for('app.app_page',tab='rewards'))


@app_bp.route('/social/posts/<int:post_id>/image',methods=['GET'])
def post_image(post_id):
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        row=db.execute("""SELECT pi.image_data,pi.mime FROM post_images pi
          JOIN posts p ON p.id=pi.post_id JOIN users u ON u.id=p.author_user_id
          WHERE pi.post_id=? AND u.active=1 AND (u.type!='pessoa' OR u.public_profile=1)""",
          (post_id,)).fetchone()
    if not row: abort(404)
    response=make_response(row[0]); response.headers['Content-Type']=row[1]
    response.headers['Cache-Control']='private,max-age=600'
    return response


@app_bp.route('/social/posts/<int:post_id>/event',methods=['POST'])
def post_event(post_id):
    payload=request.get_json(silent=True) or {}
    action=payload.get('action')
    if action not in ('view','save','unsave','hide'): return jsonify(error='Invalid action'),400
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.row_factory=sqlite3.Row; db.execute('PRAGMA foreign_keys=ON')
        post=db.execute("""SELECT p.id,p.body,p.tags FROM posts p JOIN users u ON u.id=p.author_user_id
          WHERE p.id=? AND u.active=1 AND (u.type!='pessoa' OR u.public_profile=1)""",(post_id,)).fetchone()
        if not post: abort(404)
        tags=tags_for(post['body'],post['tags'])
        uid=g.user['id']
        if action=='view':
            pref=db.execute('SELECT personalized FROM user_feed_settings WHERE user_id=?',(uid,)).fetchone()
            if pref and not pref[0]: return jsonify(ok=True,action='view',tracked=False)
            # Count at most once per viewer/post/day. Limit heavy automated spam.
            daily=db.execute("SELECT COUNT(*) FROM post_views WHERE user_id=? AND day=date('now')",(uid,)).fetchone()[0]
            if daily<120:
                cur=db.execute("INSERT OR IGNORE INTO post_views(user_id,post_id) VALUES (?,?)",(uid,post_id))
                if cur.rowcount: add_affinity(db,uid,tags,0.35)
        elif action=='save':
            cur=db.execute('INSERT OR IGNORE INTO post_saves(user_id,post_id) VALUES (?,?)',(uid,post_id))
            if cur.rowcount: add_affinity(db,uid,tags,3.5)
        elif action=='unsave':
            db.execute('DELETE FROM post_saves WHERE user_id=? AND post_id=?',(uid,post_id))
        elif action=='hide':
            cur=db.execute('INSERT OR IGNORE INTO user_hidden_posts(user_id,post_id) VALUES (?,?)',(uid,post_id))
            if cur.rowcount: add_affinity(db,uid,tags,-1.5)
        db.commit()
    return jsonify(ok=True,action=action)


@app_bp.route('/social/interests',methods=['POST'])
def update_interests():
    choice=request.form.get('choice','set')
    with closing(sqlite3.connect(current_app.config['DATABASE_PATH'])) as db:
        db.execute('PRAGMA foreign_keys=ON')
        if choice=='reset':
            db.execute('DELETE FROM user_topic_scores WHERE user_id=?',(g.user['id'],))
            db.execute('DELETE FROM user_pinned_topics WHERE user_id=?',(g.user['id'],))
            db.execute('DELETE FROM user_hidden_posts WHERE user_id=?',(g.user['id'],))
            db.execute('DELETE FROM post_views WHERE user_id=?',(g.user['id'],))
            flash('Your recommendation interests were reset.','success')
        else:
            personalize=1 if request.form.get('personalized')=='on' else 0
            db.execute('''INSERT INTO user_feed_settings(user_id,personalized)
               VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET personalized=excluded.personalized''',(g.user['id'],personalize))
            selected=set(request.form.getlist('topics')) & set(POPULAR_TOPICS)
            db.execute('DELETE FROM user_pinned_topics WHERE user_id=?',(g.user['id'],))
            db.executemany('INSERT INTO user_pinned_topics(user_id,tag) VALUES (?,?)',
                           [(g.user['id'],t) for t in selected])
            flash('Your interests were saved.','success')
        db.commit()
    return redirect(url_for('app.app_page',tab='community'))
