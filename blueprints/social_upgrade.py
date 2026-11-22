"""Non-destructive social features migration for Byfrost V6.

Works regardless of whether the Flask entry point is main.py or flask_app.py.
Only adds nullable columns and tables; never deletes existing records.
"""
from pathlib import Path
import sqlite3
from threading import Lock

_ready = set()
_lock = Lock()


def ensure_social_schema(database_path):
    path = str(Path(database_path).resolve())
    if path in _ready:
        return
    with _lock:
        if path in _ready:
            return
        with sqlite3.connect(path, timeout=35) as db:
            db.execute('PRAGMA busy_timeout=35000')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            def add_columns(table, additions):
                old = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
                if not old:
                    raise RuntimeError(f'Byfrost database is missing the {table} table')
                for name, sqltype in additions.items():
                    if name not in old:
                        db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {sqltype}')
            add_columns('posts', {
                'repost_of_id': 'INTEGER REFERENCES posts(id) ON DELETE SET NULL',
                'post_type': "TEXT NOT NULL DEFAULT 'post'",
                'expires_at': 'TEXT',
                'edited_at': 'TEXT',
                'deleted_at': 'TEXT',
            })
            add_columns('post_comments', {
                'edited_at': 'TEXT',
                'deleted_at': 'TEXT',
            })
            add_columns('messages', {
                'read_at': 'TEXT',
                'forwarded_from_id': 'INTEGER REFERENCES messages(id) ON DELETE SET NULL',
                'shared_post_id': 'INTEGER REFERENCES posts(id) ON DELETE SET NULL',
                'image_data': 'BLOB',
                'image_mime': 'TEXT',
                'edited_at': 'TEXT',
                'deleted_at': 'TEXT',
            })
            db.execute('''CREATE TABLE IF NOT EXISTS message_blocks (
                blocker_user_id INTEGER NOT NULL,
                blocked_user_id INTEGER NOT NULL,
                created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (blocker_user_id,blocked_user_id),
                FOREIGN KEY (blocker_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (blocked_user_id) REFERENCES users(id) ON DELETE CASCADE,
                CHECK (blocker_user_id <> blocked_user_id)
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS post_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                image_data BLOB NOT NULL,
                mime TEXT NOT NULL DEFAULT 'image/jpeg',
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                UNIQUE (post_id, position)
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS message_hidden (
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, message_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
            )''')
            db.execute('CREATE INDEX IF NOT EXISTS idx_post_media ON post_media(post_id,position)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_posts_expiry ON posts(post_type,expires_at)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_posts_repost_of ON posts(repost_of_id)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_messages_unread ON messages(recipient_user_id,read_at)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_messages_shared_post ON messages(shared_post_id)')
            db.commit()
        _ready.add(path)
