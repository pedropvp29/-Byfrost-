"""Byfrost Social V4: large, Brasília/DF-only FICTIONAL demonstration dataset.

python seed_brasilia_run.py            # backup and insert immediately
python seed_brasilia_run.py --preview      # show location and counts only
python seed_brasilia_run.py --db data/users.db

Run main.py once before applying so V4 tables/migrations exist.
No real collection points, organizations, financial transfers or verified donations.
"""
import argparse
import hashlib
import hmac
import io
import os
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

# Find the real Flask project root even when the script is in another folder.
SCRIPT_DIR = Path(__file__).resolve().parent

def find_project_root():
    locations = [Path.cwd(), SCRIPT_DIR, *SCRIPT_DIR.parents]
    for place in locations:
        if (place / 'main.py').is_file() and (place / 'data').is_dir():
            return place.resolve()
    for place in locations:
        if (place / 'main.py').is_file():
            return place.resolve()
    raise SystemExit(
        'Byfrost root not found. Copy this script next to main.py, '
        'or run it from the project root.'
    )

ROOT = find_project_root()
load_dotenv(ROOT / '.env')
DOMAIN = 'byfrost-brasilia-demo.invalid'
MARK = '[DEMO — FICTIONAL / BRASÍLIA-DF]'

# City/subregion coordinates are approximate visual anchors, NEVER collection addresses.
AREAS = [
    ('Plano Piloto', -15.794, -47.882),
    ('Asa Norte', -15.756, -47.884),
    ('Asa Sul', -15.818, -47.902),
    ('Taguatinga', -15.834, -48.054),
    ('Ceilândia', -15.825, -48.108),
    ('Samambaia', -15.878, -48.085),
    ('Guará', -15.829, -47.979),
    ('Águas Claras', -15.843, -48.028),
    ('Sobradinho', -15.649, -47.790),
    ('Gama', -16.021, -48.064),
]
NGOS = [
    ('Rede Acolher DF','Food security and family assistance'),
    ('Mãos de Brasília','Winter clothing and social protection'),
    ('Instituto Aprender Juntos','Education and school supplies'),
    ('Casa Recomeçar','Furniture and household support'),
    ('Crescer com Afeto','Childhood and development'),
    ('Caminhos Solidários','Food distribution and volunteering'),
    ('Coletivo Novo Horizonte','Professional training and digital access'),
    ('Abraço Verde','Sustainable reuse and community gardens'),
    ('Vozes do Cerrado','Environmental and community education'),
    ('Ponte do Amanhã','Family care and basic needs'),
]
BUSINESSES = [
    ('Cerrado Alimentos','Food'),('Capital Tec','Technology'),
    ('Brasília Têxtil','Clothing'),('Rota Solidária Logística','Logistics'),
    ('Mercado Horizonte DF','Retail'),('Luz do Planalto','Energy'),
    ('Gráfica Capital','Printing'),('Móveis do Cerrado','Furniture'),
]
PEOPLE = ['Ana Lima','Bruno Costa','Carla Souza','Diego Martins','Elisa Rocha',
          'Felipe Dias','Gabriela Nunes','Hugo Ferreira','Isabela Mendes','João Ribeiro',
          'Karina Oliveira','Lucas Pereira','Marina Alves','Nicolas Castro','Olivia Santos',
          'Paulo Duarte','Rafaela Barbosa','Samuel Teixeira','Tainá Ribeiro','Victor Araújo']
# category, resource, unit, goal, topic tags
CAUSES = [
    ('food','Rice, beans and nutritious food baskets','kits',100,'food,community,families'),
    ('clothing','Warm clothes for local families','pieces',160,'clothing,winter,families'),
    ('hygiene','Hygiene and personal care kits','kits',85,'hygiene,health,care'),
    ('books','Books and learning materials','books',120,'education,books,children'),
    ('electronics','Refurbished notebooks for students','devices',24,'technology,education,digital'),
    ('furniture','Furniture and household essentials','items',35,'furniture,housing,reuse'),
    ('other','Backpacks and school supplies','kits',110,'education,children,school'),
    ('food','Nonperishable food for community kitchens','kg',240,'food,hunger,community'),
]
POST_LINES = [
    'Our volunteers are preparing the next phase of this community project. Every contribution matters.',
    'A behind-the-scenes look at our mission in Brasília. Learn how you can help local families.',
    'We are inviting neighbors to support this cause with useful items and shared knowledge.',
    'Small gestures can become meaningful change. Discover the project and its collection options.',
    'Community update: here is what we are working on and why this cause deserves attention.',
]

def ensure_schema(db):
    required = {
      'users':['id','email','password','type','city','state','country','bio','public_profile'],
      'ngos':['user_id','public_name','mission'], 'companies':['user_id','trade_name','sector'],
      'campaigns':['ngo_user_id','title','target_quantity'],
      'requests':['ngo_user_id','kind','title','quantity'],
      'collection_points':['ngo_user_id','latitude','longitude'],
      'request_points':['request_id','point_id'],
      'offers':['donor_user_id','title'], 'donations':['donor_user_id','ngo_user_id','status'],
      'posts':['author_user_id','body','tags','request_id'],
      'post_images':['post_id','image_data','mime'],
      'post_likes':['post_id','user_id'],'post_comments':['post_id','user_id'],
      'follows':['follower_user_id','followed_user_id'],
      'messages':['sender_user_id','recipient_user_id'],
      'ngo_rewards':['ngo_user_id','name'],
      'impact_events':['user_id','donation_id','points'],
      'user_topic_scores':['user_id','tag','weight'],
    }
    for table, cols in required.items():
        have={r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
        if not set(cols).issubset(have):
            raise SystemExit(f'Missing V4 schema: {table} {set(cols)-have}. Run latest main.py first.')

def inserted(db, table, where, params, payload):
    row=db.execute('SELECT id FROM '+table+' WHERE '+where+' LIMIT 1',params).fetchone()
    if row: return row['id'],False
    keys=list(payload)
    cur=db.execute('INSERT INTO '+table+' ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',tuple(payload.values()))
    return cur.lastrowid,True

def once(db, table, predicate, args, fields):
    if db.execute('SELECT 1 FROM '+table+' WHERE '+predicate+' LIMIT 1',args).fetchone():return False
    keys=list(fields)
    db.execute('INSERT INTO '+table+' ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',tuple(fields.values()))
    return True

def poster_bytes(head, sub, kind):
    """Create a demo poster with Windows-compatible font and safe fallback.

    Older Pillow/default bitmap fonts cannot encode accented Portuguese text or
    Unicode symbols. Prefer a TrueType font and transliterate only if needed.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print('NOTICE: Pillow is not installed; posts will be created without images.')
        return None

    palette = {
        'food': ('#374A58', '#79D9B4'),
        'clothing': ('#4A395B', '#E4A8C6'),
        'books': ('#243D5F', '#8DB6FF'),
        'electronics': ('#263D42', '#7AD9DE'),
        'hygiene': ('#3D4B60', '#B8A7FF'),
        'furniture': ('#554638', '#F7CE95'),
        'other': ('#343B62', '#C3B1FF'),
    }
    bg, accent = palette.get(kind, palette['other'])
    im = Image.new('RGB', (900, 600), bg)
    d = ImageDraw.Draw(im)
    for r in range(14):
        x = r * 87 - 120
        y = r * 22 - 115
        d.ellipse((x, y, x + 550, y + 550), outline=accent, width=2)
    d.rounded_rectangle((55, 65, 845, 535), radius=33,
                        fill='#172338', outline=accent, width=3)

    # Windows (your computer), Linux and macOS common fonts.
    font_candidates = [
        Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'arial.ttf',
        Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf',
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'),
        Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
    ]
    truetype_path = next((str(p) for p in font_candidates if p.is_file()), None)
    try:
        font = ImageFont.truetype(truetype_path, 29) if truetype_path else ImageFont.load_default()
        small = ImageFont.truetype(truetype_path, 21) if truetype_path else ImageFont.load_default()
    except (OSError, ValueError):
        font = small = ImageFont.load_default()

    def safe_text(xy, value, use_font, color):
        value = str(value)
        try:
            d.text(xy, value, font=use_font, fill=color)
        except (UnicodeEncodeError, UnicodeError):
            # Default Pillow bitmap font only supports Latin-1. ASCII is safe.
            ascii_value = unicodedata.normalize('NFKD', value)
            ascii_value = ascii_value.encode('ascii', 'replace').decode('ascii')
            d.text(xy, ascii_value, font=use_font, fill=color)

    safe_text((90, 110), 'BYFROST / BRASILIA DF', font, accent)
    safe_text((90, 205), head[:31], font, '#FFFFFF')
    safe_text((90, 264), sub[:37], small, '#D8E8EA')
    d.rounded_rectangle((90, 397, 490, 459), radius=16, fill=accent)
    safe_text((108, 412), 'DEMO - FICTIONAL CONTENT', small, '#101A28')

    out = io.BytesIO()
    im.save(out, format='JPEG', quality=80, optimize=True)
    return out.getvalue()

def run(db,hashed):
    totals={k:0 for k in ['users','ngos','companies','campaigns','requests','collection_points',
         'request_points','offers','donations','posts','post_images','post_likes','post_comments',
         'follows','messages','ngo_rewards','impact_events','user_topic_scores']}
    def inc(k,truth=True):totals[k]+=bool(truth)
    # This seed NEVER uses existing real user IDs for social interactions.
    def account(label,name,kind,i):
        email=f'{label}{i+1:02d}@{DOMAIN}'
        row=db.execute('SELECT id,type FROM users WHERE email=?',(email,)).fetchone()
        if row:
            if row['type']!=kind:raise RuntimeError('Demo email collision: '+email)
            return row['id']
        region,lat,lon=AREAS[i%len(AREAS)]
        cur=db.execute('''INSERT INTO users
          (type,name,email,password,country,state,city,address,postal_code,bio,headline,public_profile,leaderboard_opt_in)
          VALUES (?,?,?,?,'Brazil','DF','Brasília',?,?,?, ?,1,1)''',
          (kind,name+' [DEMO]',email,hashed,'FICTIONAL — '+region,'00000-000',
           MARK+' Community profile in '+region+'.','Supporting meaningful causes in Brasília'))
        inc('users');return cur.lastrowid
    ngo_ids=[];company_ids=[];person_ids=[];all_requests=[];all_campaigns=[]
    for i,(name,mission) in enumerate(NGOS):
        uid=account('ngo.df.',name,'ong',i);ngo_ids.append(uid)
        inc('ngos',once(db,'ngos','user_id=?',(uid,),dict(
            user_id=uid,legal_name=name+' (fictional)',public_name=name+' — DEMO',
            tax_id='DEMO-DF-NGO-'+str(i+1).zfill(3),description=MARK+' Community nonprofit prototype in Brasília, Federal District.',
            mission=mission,cause=mission,website='https://example.org',phone='DEMO — not a phone',
            address='FICTIONAL ONLY — not a collection address',city='Brasília',state='DF',country='Brazil',
            postal_code='00000-000',verified=0)))
        region,lat,lon=AREAS[i]
        point_ids=[]
        for j in range(3):
            title=f'[DEMO] Collection zone {j+1} / {name} / {region}'
            pid,yes=inserted(db,'collection_points','ngo_user_id=? AND name=?',(uid,title),dict(
                ngo_user_id=uid,name=title,address='FICTIONAL MAP PIN — NOT A REAL COLLECTION LOCATION',
                city='Brasília',state='DF',postal_code='00000-000',
                latitude=lat+(j-1)*.008,longitude=lon+(j-1)*.007,
                instructions='DEMO ONLY. Do not travel to this coordinate. Contact is fictional.',active=1))
            inc('collection_points',yes);point_ids.append(pid)
        for j in range(4):
            cat,res,unit,goal,tags=CAUSES[(i+j)%len(CAUSES)]
            cname=f'[DEMO DF] {name} — {res} | {j+1}'
            cid,yes=inserted(db,'campaigns','ngo_user_id=? AND title=?',(uid,cname),dict(
                ngo_user_id=uid,title=cname,
                description=MARK+' '+mission+'. Demonstration campaign for '+region+'.',category=cat,
                target_quantity=goal,unit=unit,allow_money_demo=int(j%2==0),status='open'))
            inc('campaigns',yes);all_campaigns.append((uid,cid))
            for k in range(3):
                xcat,xres,xunit,xgoal,xtags=CAUSES[(i+j+k)%len(CAUSES)]
                title=f'[DEMO DF] {name}: {xres} — {j+1}.{k+1}'
                rid,yes=inserted(db,'requests','ngo_user_id=? AND title=?',(uid,title),dict(
                    ngo_user_id=uid,campaign_id=cid,kind='need',title=title,
                    description=MARK+' The organization needs '+xres.lower()+'. '+
                                'Choose delivery, pickup or contact. All data is simulated.',
                    category=xcat,quantity=xgoal+(i%4)*8,unit=xunit,allow_dropoff=1,
                    allow_pickup=int(k==1),allow_contact=1,allow_claims=0,status='open'))
                inc('requests',yes);all_requests.append((uid,rid,xcat,xtags))
                for pid in (point_ids[(j+k)%3],point_ids[(j+k+1)%3]):
                    inc('request_points',once(db,'request_points','request_id=? AND point_id=?',(rid,pid),
                        dict(request_id=rid,point_id=pid)))
        # Public distribution is created by NGO only, like normal NGO requests.
        title=f'[DEMO DF] {name} — Community distribution of donated essentials'
        give_id,yes=inserted(db,'requests','ngo_user_id=? AND title=?',(uid,title),dict(
            ngo_user_id=uid,campaign_id=None,kind='giveaway',title=title,
            description=MARK+' Test a beneficiary claim/reservation; no real items are supplied.',
            category='clothing',quantity=42,unit='kits',allow_dropoff=0,allow_pickup=1,
            allow_contact=1,allow_claims=1,status='open'))
        inc('requests',yes)
        inc('request_points',once(db,'request_points','request_id=? AND point_id=?',(give_id,point_ids[0]),
            dict(request_id=give_id,point_id=point_ids[0])))
        for j in range(12):
            owner,rid,cat,tags=all_requests[(i*12+j)%len(all_requests)]
            body=(f'{MARK} {name} • {POST_LINES[j%len(POST_LINES)]} '
                  f'Cause: {CAUSES[(i+j)%len(CAUSES)][1]}. Region: Brasília / DF. '
                  f'#{cat} #brasilia #solidarity #ngo #donate [DFNGO{i+1:02d}P{j+1:02d}]')
            own_requests=[x for x in all_requests if x[0]==uid]
            linked=own_requests[j%len(own_requests)]
            pid,yes=inserted(db,'posts','author_user_id=? AND body=?',(uid,body),dict(
                author_user_id=uid,body=body,tags=','.join(dict.fromkeys((tags+',brasilia,df,donation,community').split(','))),request_id=linked[1],
                created=(datetime.now(timezone.utc)-timedelta(hours=i*6+j*3)).strftime('%Y-%m-%d %H:%M:%S')))
            inc('posts',yes)
            if not db.execute('SELECT 1 FROM post_images WHERE post_id=?',(pid,)).fetchone():
                art=poster_bytes(name,CAUSES[(i+j)%len(CAUSES)][1],cat)
                if art:db.execute('INSERT INTO post_images(post_id,image_data,mime) VALUES (?,?,?)',(pid,art,'image/jpeg'));inc('post_images')
        for kind,label,symbol,color,threshold in [('title','Brasília Helper','✦','mint',1),
                          ('frame','Cerrado Guardian','★','violet',2),('accent','Community Spark','♡','gold',3)]:
            title=label+' · '+name
            inc('ngo_rewards',once(db,'ngo_rewards','ngo_user_id=? AND name=?',(uid,title),dict(
                ngo_user_id=uid,name=title,description=MARK+' Reward earned through confirmed donations.',
                kind=kind,symbol=symbol,color=color,min_confirmed=threshold,active=1)))
    for i,(name,sector) in enumerate(BUSINESSES):
        uid=account('biz.df.',name,'empresa',i);company_ids.append(uid)
        inc('companies',once(db,'companies','user_id=?',(uid,),dict(
            user_id=uid,legal_name=name+' Ltda (fictional)',trade_name=name+' — DEMO',
            tax_id='DEMO-DF-BIZ-'+str(i+1).zfill(3),description=MARK+' Local business prototype supporting Brasília communities.',
            sector=sector,website='https://example.org',phone='DEMO — not a phone',
            address='Fictional headquarters',city='Brasília',state='DF',country='Brazil',postal_code='00000-000',verified=0)))
        for j in range(7):
            cat,resource,unit,goal,tags=CAUSES[(i+j)%len(CAUSES)]
            title=f'[DEMO DF] {name} offers {resource} — lot {j+1}'
            oid,yes=inserted(db,'offers','donor_user_id=? AND title=?',(uid,title),dict(
                donor_user_id=uid,ngo_user_id=None,title=title,
                description=MARK+' Fictional company donation offer for NGOs in Brasília.',
                category=cat,quantity=max(12,goal//2),unit=unit,status='available'))
            inc('offers',yes)
        for j in range(10):
            cat,resource,unit,goal,tags=CAUSES[(i+j)%len(CAUSES)]
            body=(f'{MARK} {name}: Our Brasília team is supporting community causes. '
                  f'Today we are highlighting {resource.lower()} and nonprofit partnerships. '
                  f'#business #brasilia #{cat} #socialimpact [DFBIZ{i+1:02d}P{j+1:02d}]')
            pid,yes=inserted(db,'posts','author_user_id=? AND body=?',(uid,body),dict(
                author_user_id=uid,body=body,tags=tags+',business,brasilia,donation',request_id=None,
                created=(datetime.now(timezone.utc)-timedelta(hours=i*7+j*4)).strftime('%Y-%m-%d %H:%M:%S')))
            inc('posts',yes)
            if not db.execute('SELECT 1 FROM post_images WHERE post_id=?',(pid,)).fetchone():
                art=poster_bytes(name,resource,cat)
                if art:db.execute('INSERT INTO post_images(post_id,image_data,mime) VALUES (?,?,?)',(pid,art,'image/jpeg'));inc('post_images')
    for i,name in enumerate(PEOPLE):
        uid=account('person.df.',name,'pessoa',i);person_ids.append(uid)
        for j in range(2):
            cat,resource,unit,goal,tags=CAUSES[(i+j)%len(CAUSES)]
            title=f'[DEMO DF] {name} offers {resource} — {j+1}'
            oid,yes=inserted(db,'offers','donor_user_id=? AND title=?',(uid,title),dict(
                donor_user_id=uid,ngo_user_id=None,title=title,
                description=MARK+' Fictional individual donation offer.',category=cat,
                quantity=2+(i+j)%7,unit=unit,status='available'))
            inc('offers',yes)
    donors=company_ids+person_ids
    # 100 fictional pledges, some marked confirmed ONLY within designated demo identities.
    for i in range(100):
        donor=donors[i%len(donors)];ngo,rid,cat,tags=all_requests[(i*11)%len(all_requests)]
        found=db.execute('SELECT id,status FROM donations WHERE donor_user_id=? AND request_id=? AND method=?',
                         (donor,rid,'dropoff')).fetchone()
        if found: did=found['id']
        else:
            status='confirmed' if i%3==0 else 'pledged'
            did=db.execute('''INSERT INTO donations (donor_user_id,ngo_user_id,request_id,quantity,method,status,confirmed)
               VALUES (?,?,?,?,?,?,?)''',(
                 donor,ngo,rid,1+i%5,'dropoff',status,
                 datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if status=='confirmed' else None)).lastrowid
            inc('donations')
        if i%3==0:
            inc('impact_events',once(db,'impact_events','donation_id=?',(did,),dict(
                user_id=donor,donation_id=did,points=20)))
    everyone=ngo_ids+company_ids+person_ids
    for i,uid in enumerate(everyone):
        for target in (ngo_ids[i%len(ngo_ids)],ngo_ids[(i+3)%len(ngo_ids)]):
            if target!=uid:
                inc('follows',once(db,'follows','follower_user_id=? AND followed_user_id=?',(uid,target),
                                   dict(follower_user_id=uid,followed_user_id=target)))
    demo_posts=db.execute('''SELECT p.id,p.author_user_id,p.tags FROM posts p JOIN users u ON u.id=p.author_user_id
       WHERE u.email LIKE ? ORDER BY p.id DESC LIMIT 140''',('%@'+DOMAIN,)).fetchall()
    for i,p in enumerate(demo_posts):
        for j in range(3):
            who=donors[(i*3+j)%len(donors)]
            inc('post_likes',once(db,'post_likes','post_id=? AND user_id=?',(p['id'],who),
                                  dict(post_id=p['id'],user_id=who)))
        if i%2==0:
            who=donors[i%len(donors)]
            body=MARK+f' Inspiring local community initiative! Test comment #{i+1}.'
            inc('post_comments',once(db,'post_comments','post_id=? AND user_id=? AND body=?',
                     (p['id'],who,body),dict(post_id=p['id'],user_id=who,body=body)))
    for i in range(35):
        donor=donors[i%len(donors)];ngo,rid,cat,tags=all_requests[(i*13)%len(all_requests)]
        body=MARK+f' Hello! This is a sample chat about pickup or delivery #{i+1}.'
        inc('messages',once(db,'messages','sender_user_id=? AND recipient_user_id=? AND body=?',
                (donor,ngo,body),dict(sender_user_id=donor,recipient_user_id=ngo,request_id=rid,body=body)))
    # Populate example affinities ONLY for these fictional identities, not any actual user's history.
    for i,uid in enumerate(person_ids):
        for tag,weight in [('food',5+(i%4)),('education',3+(i%3)),('brasilia',2)]:
            inc('user_topic_scores',once(db,'user_topic_scores','user_id=? AND tag=?',(uid,tag),
                dict(user_id=uid,tag=tag,weight=weight)))
    for uid in donors:
        count,xp=db.execute('''SELECT COUNT(*),COALESCE(SUM(e.points),0)
            FROM impact_events e JOIN donations d ON d.id=e.donation_id WHERE e.user_id=?''',(uid,)).fetchone()
        db.execute('UPDATE users SET amount=?,level=? WHERE id=?',(count,1+xp//100,uid))
    return totals

def report(db, heading):
    print('\n' + heading)
    queries = {
      'NGOs (demo)': "SELECT COUNT(*) FROM users WHERE type='ong' AND email LIKE ?",
      'Businesses (demo)': "SELECT COUNT(*) FROM users WHERE type='empresa' AND email LIKE ?",
      'People (demo)': "SELECT COUNT(*) FROM users WHERE type='pessoa' AND email LIKE ?",
      'Campaigns (demo)': "SELECT COUNT(*) FROM campaigns c JOIN users u ON u.id=c.ngo_user_id WHERE u.email LIKE ?",
      'NGO requests (demo)': "SELECT COUNT(*) FROM requests r JOIN users u ON u.id=r.ngo_user_id WHERE u.email LIKE ?",
      'Collection points (demo)': "SELECT COUNT(*) FROM collection_points cp JOIN users u ON u.id=cp.ngo_user_id WHERE u.email LIKE ?",
      'Company/NGO posts (demo)': "SELECT COUNT(*) FROM posts p JOIN users u ON u.id=p.author_user_id WHERE u.email LIKE ?",
      'Offers (demo)': "SELECT COUNT(*) FROM offers o JOIN users u ON u.id=o.donor_user_id WHERE u.email LIKE ?",
    }
    for label,sql in queries.items():
        print(f'  {label}: {db.execute(sql, ("%@" + DOMAIN,)).fetchone()[0]}')
    print('  Total posts in DB:',db.execute('SELECT COUNT(*) FROM posts').fetchone()[0])
    print('  Total active organizations:',db.execute("SELECT COUNT(*) FROM users WHERE type IN ('ong','empresa') AND active=1").fetchone()[0])


def main():
    p=argparse.ArgumentParser(description='Insert fictional Brasília/DF dataset in the actual Byfrost project database')
    p.add_argument('--preview',action='store_true',help='only inspect DB; do not add data')
    p.add_argument('--apply',action='store_true',help='optional compatibility flag; insertion is now default')
    p.add_argument('--db',default=None,help='database path relative to Byfrost root, or absolute path')
    args=p.parse_args()
    path=Path(args.db or os.getenv('DATABASE_PATH','data/users.db'))
    if not path.is_absolute():path=ROOT/path
    path=path.resolve()
    print('BYFROST PROJECT:',ROOT)
    print('DATABASE IN USE:',path)
    print('Mode:', 'PREVIEW — read only' if args.preview else 'INSERT — with backup')
    if not path.is_file():
        raise SystemExit('Database not found at this location. Check DATABASE_PATH in .env and main.py.')
    db=sqlite3.connect(path)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=5000')
    try:
        ensure_schema(db)
        report(db,'BEFORE')
        if args.preview:
            print('\nTo insert the data, run: python seed_brasilia_run.py')
            return
        # One-click mode: no flags, prompts or .env changes required.
        # Reuse the application's exact pepper when it is available, so demo users
        # can authenticate with the same hashing mechanism as real registrations.
        pepper=os.getenv('PASSWORD_PEPPER','')
        password=os.getenv('DEMO_PASSWORD') or 'ByfrostDemo2026!'
        if not pepper:
            # Still populate public demo content without interfering with actual
            # login configuration. Demo credentials will not work until the
            # application's PASSWORD_PEPPER is present on the next run.
            pepper='BYFROST_SEED_ONLY_NO_LOGIN_PEPPER_' + hashlib.sha256(str(ROOT).encode()).hexdigest()
            print('NOTICE: PASSWORD_PEPPER absent: demo accounts will display, but their login will require re-seeding passwords after configuring the app.')
        print('DEMO ACCOUNT PASSWORD:', password)
        pass_pepper=hmac.new(pepper.encode(),password.encode(),hashlib.sha256).hexdigest()
        hashed=generate_password_hash(pass_pepper)
        backup=path.with_name(path.name+'.before-brasilia-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        with sqlite3.connect(backup) as dest: db.backup(dest)
        print('BACKUP:',backup)
        db.execute('BEGIN IMMEDIATE')
        try:
            totals=run(db,hashed)
            db.commit()
        except Exception:
            db.rollback()
            raise
        print('\nADDED THIS RUN:')
        for k,v in totals.items(): print(f'  {k}: +{v}')
        report(db,'AFTER')
        print('\nDone. Restart Flask, then visit /app/?tab=community and /app/?tab=organizations')
        print('Demo accounts: ngo.df.01, biz.df.01, person.df.01 @'+DOMAIN)
        print('Open the app Organizations / Community / Explore tabs to view the content.')
        print('FICTIONAL CONTENT ONLY — map pins are NOT collection locations.')
    finally:
        db.close()

if __name__=='__main__': main()
