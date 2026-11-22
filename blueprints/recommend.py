"""Explainable, privacy-conscious feed ranking for Byfrost (SQLite, no external AI API).

Only visible community posts are ranked. A view is deliberately a WEAK signal;
likes, saved posts and confirmed donations matter more. Ranking balances relevance,
new causes, freshness and diversity. Demo-only scoring: tune with real opt-in feedback.
"""
from __future__ import annotations
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone

TOPIC_ALIASES = {
    'food': ('food','meals','groceries','hunger','nutrition','rice','beans','aliment','comida','fome','cesta'),
    'clothing': ('clothes','clothing','jackets','winter','shoes','uniform','roupa','agasalho','vestuario'),
    'education': ('school','student','students','book','books','education','classroom','learning','escola','educacao','livro'),
    'health': ('health','hospital','wellness','medical','care','saude','higiene','hygiene'),
    'environment': ('environment','recycling','sustainable','climate','green','ecology','ambiente','reciclagem'),
    'children': ('children','child','kids','youth','baby','crianca','infancia'),
    'animals': ('animals','pets','shelter','dogs','cats','animal','resgate'),
    'technology': ('laptop','computer','tech','technology','digital','eletronico','computador'),
    'housing': ('housing','shelter','home','furniture','moradia','casa','moveis'),
    'community': ('community','neighborhood','volunteer','volunteers','solidarity','comunidade','voluntario'),
}
POPULAR_TOPICS = list(TOPIC_ALIASES)
CATEGORY_TOPIC = {'food':'food','clothing':'clothing','hygiene':'health', 'books':'education',
                  'furniture':'housing','electronics':'technology','other':'community'}


def clean_tag(text: str) -> str:
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).lower().strip('# ')
    text = re.sub(r'[^a-z0-9_-]', '', text)
    return text[:28]


def tags_for(body='', explicit='', category=None):
    """Explicit hashtags/tags plus topic keywords. Whitelist-friendly normalized tags."""
    raw = (explicit or '').replace(';', ',')
    chosen = [clean_tag(v) for v in raw.split(',')]
    chosen += [clean_tag(t) for t in re.findall(r'#([\w-]{2,30})', body or '')]
    if category in CATEGORY_TOPIC:
        chosen.append(CATEGORY_TOPIC[category])
    lower = unicodedata.normalize('NFKD', (body or '').lower())
    lower = ''.join(ch for ch in lower if not unicodedata.combining(ch))
    words = set(re.findall(r'[a-z]{3,}', lower))
    for canonical, keywords in TOPIC_ALIASES.items():
        if any(term in words or (len(term) > 6 and term in lower) for term in keywords):
            chosen.append(canonical)
    result=[]
    for tag in chosen:
        if tag and tag not in result and len(tag) > 1:
            result.append(tag)
    return result[:10]


def add_affinity(db, user_id: int, tags, delta: float):
    for tag in dict.fromkeys(tags):
        db.execute('''INSERT INTO user_topic_scores(user_id,tag,weight,updated)
          VALUES(?,?,?,CURRENT_TIMESTAMP)
          ON CONFLICT(user_id,tag) DO UPDATE SET
            weight=MAX(-12,MIN(30,weight+excluded.weight)),updated=CURRENT_TIMESTAMP''',
                   (user_id,tag,delta))


def _age_days(value):
    if not value: return 60
    try:
        date = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if date.tzinfo is None: date=date.replace(tzinfo=timezone.utc)
        return max(0,(datetime.now(timezone.utc)-date).total_seconds()/86400)
    except (ValueError, TypeError):
        return 60


def ranked_feed(db, viewer, rows, mode='for-you', limit=60):
    """Views are weak signals, never a reason to remove posts.

    Fresh unseen -> older unseen -> previously seen. Explicit user hiding is
    the only reason a visible, otherwise eligible post is removed from ranking.
    """
    uid=viewer['id']
    limit=max(10,min(240,int(limit)))
    pref=db.execute('SELECT personalized FROM user_feed_settings WHERE user_id=?',(uid,)).fetchone()
    personalized=bool(pref[0]) if pref else True
    topic_rows=db.execute('SELECT tag,weight,updated FROM user_topic_scores WHERE user_id=?',(uid,)).fetchall()
    interests={r['tag']:float(r['weight'])*(0.5**(_age_days(r['updated'])/45)) for r in topic_rows} if personalized else {}
    pinned={r['tag'] for r in db.execute('SELECT tag FROM user_pinned_topics WHERE user_id=?',(uid,)).fetchall()} if personalized else set()
    follows={r['followed_user_id'] for r in db.execute('SELECT followed_user_id FROM follows WHERE follower_user_id=?',(uid,)).fetchall()}
    hidden={r['post_id'] for r in db.execute('SELECT post_id FROM user_hidden_posts WHERE user_id=?',(uid,)).fetchall()}
    saved={r['post_id'] for r in db.execute('SELECT post_id FROM post_saves WHERE user_id=?',(uid,)).fetchall()}
    seen={r['post_id'] for r in db.execute('SELECT DISTINCT post_id FROM post_views WHERE user_id=?',(uid,)).fetchall()}
    given=Counter()
    if personalized:
        for r in db.execute("""SELECT r.category,COUNT(*) AS n FROM donations d JOIN requests r
          ON r.id=d.request_id WHERE d.donor_user_id=? AND d.status='confirmed'
          GROUP BY r.category""",(uid,)).fetchall():
            given[CATEGORY_TOPIC.get(r['category'],'community')]+=r['n']
    ranking=[]
    for raw in rows:
        p=dict(raw)
        if p['id'] in hidden: continue
        if mode=='saved' and p['id'] not in saved: continue
        if mode=='following' and p['author_user_id'] not in follows and p['author_user_id']!=uid:
            continue
        tags=tags_for(p.get('body',''),p.get('tags') or '',p.get('request_category'))
        p['topic_tags']=tags
        relevant=sorted(((t,interests.get(t,0)+(4 if t in pinned else 0)+min(4,given[t]*1.4)) for t in tags),key=lambda x:x[1],reverse=True)
        matching=[(t,v) for t,v in relevant if v>0.2]
        affinity=sum(min(9,v)*1.6 for _,v in matching[:3])
        age=_age_days(p.get('created'))
        new_unseen=age<=2 and p['id'] not in seen
        engagement=min(3.5,math.log1p(p.get('likes',0))*0.8+math.log1p(p.get('comments_count',0))*0.9)
        followed=p['author_user_id'] in follows
        nearby=2 if viewer['city'] and p.get('author_city') and viewer['city'].casefold()==p['author_city'].casefold() else 0
        nonprofit=2 if p['type']=='ong' else 0
        action=3 if p.get('request_id') and p.get('request_status')=='open' else 0
        explore=1.6 if p['type']=='ong' and not matching else 0
        recency=8*math.exp(-age/16)
        p['score']=affinity+recency+engagement+(7 if followed else 0)+nearby+nonprofit+action+explore
        p['is_new']=new_unseen
        p['was_seen']=p['id'] in seen
        p['saved']=p['id'] in saved
        p['root_post_id']=p.get('repost_of_id') or p['id']
        p['why_recommended']=('New in your community' if new_unseen else
            'Because you explored #'+matching[0][0] if matching else
            'From an account you follow' if followed else
            'A cause near you' if nearby else 'Discover a cause')
        p['bucket']=0 if new_unseen else (1 if p['id'] not in seen else 2)
        ranking.append(p)
    if mode in ('following','latest'):
        ranking.sort(key=lambda p:(p['created'],p['id']),reverse=True)
    else:
        ranking.sort(key=lambda p:(-p['bucket'],p['score'],p['id']),reverse=True)
        arranged=[]
        remaining=ranking[:]
        while remaining and len(arranged)<limit:
            pick=next((i for i,p in enumerate(remaining)
                if sum(x['author_user_id']==p['author_user_id'] for x in arranged[-6:])<2
                and all(x['root_post_id']!=p['root_post_id'] for x in arranged[-5:])),0)
            arranged.append(remaining.pop(pick))
        ranking=arranged
    return ranking[:limit]
