#!/usr/bin/env python3
"""Tablekeeper Stage 2 reservation API and browser application."""
import hashlib, hmac, json, os, re, secrets, sqlite3, threading
from datetime import datetime, date, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DB_PATH = os.environ.get("TABLEKEEPER_DB", "/tmp/tablekeeper.sqlite3")
LOCK = threading.RLock()
WDAYS = ['mon','tue','wed','thu','fri','sat','sun']
DB = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
DB.row_factory = sqlite3.Row
DB.execute('PRAGMA journal_mode=WAL')
DB.execute('PRAGMA foreign_keys=ON')
DB.executescript('''
CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
INSERT OR IGNORE INTO state VALUES (1, '{"users":[],"restaurants":[],"reservations":[],"tokens":{},"receipts":[]}');
''')

def state(): return json.loads(DB.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
def save(s): DB.execute('UPDATE state SET payload=? WHERE id=1',(json.dumps(s,separators=(',',':')),))
def fail(status, code, message=None): raise ApiError(status,code,message or code.replace('_',' '))
class ApiError(Exception):
    def __init__(self,status,code,message): self.status=status; self.code=code; self.message=message

def err(status,code,message): return status, {'error':{'code':code,'message':message}}
def parse_stamp(local, zone):
    if not isinstance(local,str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d',local): fail(422,'validation_failed')
    try: naive=datetime.strptime(local,'%Y-%m-%dT%H:%M')
    except ValueError: fail(422,'validation_failed')
    z=ZoneInfo(zone); possibilities=[]
    for fold in (0,1):
        aware=naive.replace(tzinfo=z,fold=fold)
        back=aware.astimezone(timezone.utc).astimezone(z)
        if back.replace(tzinfo=None)==naive and all(x.utcoffset()!=aware.utcoffset() for x in possibilities): possibilities.append(aware)
    if not possibilities: fail(422,'invalid_local_time')
    return min(possibilities,key=lambda x:x.astimezone(timezone.utc))
def iso(dt): return dt.isoformat(timespec='seconds')
def local_iso(dt,z): return dt.astimezone(ZoneInfo(z)).isoformat(timespec='seconds')
def parse_json(raw):
    try:
        x=json.loads(raw)
        if not isinstance(x,dict): raise ValueError()
        return x
    except Exception: fail(400,'malformed_request')
def valid_id(v): return isinstance(v,str) and 0<len(v)<=64
def valid_reference(v): return isinstance(v,str) and re.fullmatch(r'[A-Z0-9]{6,12}',v) is not None
def body_type(obj,key,typ,required=True):
    if key not in obj:
        if required: fail(422,'validation_failed')
        return None
    v=obj[key]
    # bool is not an integer for API purposes.
    if typ is int and (not isinstance(v,int) or isinstance(v,bool)): fail(400,'malformed_request')
    if typ is str and not isinstance(v,str): fail(400,'malformed_request')
    return v
def hashpw(p,salt=None):
    salt=salt or secrets.token_bytes(16).hex()
    n,r,parallelism=8192,8,1
    digest=hashlib.scrypt(p.encode(),salt=bytes.fromhex(salt),n=n,r=r,p=parallelism,dklen=32)
    return f'scrypt${n}${r}${parallelism}${salt}${digest.hex()}'
def checkpw(p,stored):
    try:
        if stored.startswith('scrypt$'):
            _,n,r,parallelism,salt,hashed=stored.split('$',5)
            digest=hashlib.scrypt(p.encode(),salt=bytes.fromhex(salt),n=int(n),r=int(r),p=int(parallelism),dklen=len(bytes.fromhex(hashed)))
            return hmac.compare_digest(digest.hex(),hashed)
        # Accept Stage 1 exports created before the scrypt encoding change.
        salt,hashed=stored.split(':',1)
        return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(salt),240000).hex(),hashed)
    except Exception: return False
def auth(h,s):
    v=h.headers.get('Authorization','')
    if not v.startswith('Bearer ') or not v[7:]: fail(401,'unauthenticated')
    uid=s.get('tokens',{}).get(v[7:])
    if not uid: fail(401,'unauthenticated')
    return uid
def restaurant(s,rid):
    r=next((x for x in s['restaurants'] if x.get('id')==rid),None)
    if not r: fail(404,'not_found')
    return r
def opening(r,day):
    wd=WDAYS[day.weekday()]
    return next((x for x in r.get('opening_hours',[]) if x.get('weekday')==wd),None)
def overlaps(a,b): return a[0] < b[1] and b[0] < a[1]
def res_times(res,r):
    start=parse_stamp(res['starts_at_local'],r['timezone']).astimezone(timezone.utc)
    end=start+timedelta(minutes=r['reservation_duration_minutes'])
    return start,end
def table_ids(res):
    ids=res.get('table_ids')
    if isinstance(ids,list) and ids: return ids
    return [res['table_id']] if isinstance(res.get('table_id'),str) else []
def reservation_view(res,r):
    start,end=res_times(res,r); ids=table_ids(res)
    out={'reservation_id':res['id'],'reference':res['reference'],'restaurant_id':res['restaurant_id'],'table_ids':ids,'party_size':res['party_size'],'status':res['status'],'starts_at_local':res['starts_at_local'],'starts_at':local_iso(start,r['timezone']),'ends_at':local_iso(end,r['timezone']),'created_at':res['created_at']}
    if len(ids)==1: out['table_id']=ids[0]
    return out
def allowed_combinations(r):
    combos=r.get('combinable',[])
    return [list(pair) for pair in combos]
def canonical_tables(r,ids):
    if len(ids)==2:
        return next(pair[:] for pair in allowed_combinations(r) if set(pair)==set(ids))
    return list(ids)
def chosen_tables(obj,old=None):
    if 'table_id' in obj and 'table_ids' in obj:
        values=obj['table_ids']
        if not isinstance(values,list) or values!=[obj['table_id']]: fail(422,'validation_failed')
        return values
    if 'table_ids' in obj:
        values=obj['table_ids']
        if not isinstance(values,list) or not all(isinstance(x,str) for x in values): fail(400,'malformed_request')
        return values
    if 'table_id' in obj:
        if not isinstance(obj['table_id'],str): fail(400,'malformed_request')
        return [obj['table_id']]
    return table_ids(old) if old else []
def option_allowed(r,ids):
    if len(ids)==1: return True
    if len(ids)!=2: return False
    return any(ids==pair or ids==list(reversed(pair)) for pair in allowed_combinations(r))
def option_free(s,rid,tids,a,b):
    for x in s['reservations']:
        if x['status']=='confirmed' and x['restaurant_id']==rid and set(table_ids(x)).intersection(tids):
            if overlaps((a,b),res_times(x,restaurant(s,rid))): return False
    return True
def validate_booking(s,uid,obj,old=None,excluded=(),check_occupancy=True):
    rid=obj.get('restaurant_id',old['restaurant_id'] if old else None)
    if not isinstance(rid,str): fail(422,'validation_failed')
    r=restaurant(s,rid)
    tids=chosen_tables(obj,old)
    if not tids: fail(422,'validation_failed')
    if len(set(tids))!=len(tids): fail(422,'validation_failed')
    tables={t['id']:t for t in r.get('tables',[])}
    if any(tid not in tables for tid in tids): fail(404,'not_found')
    if not option_allowed(r,tids): fail(422,'combination_not_allowed')
    tids=canonical_tables(r,tids)
    capacity=sum(tables[tid]['capacity'] for tid in tids)
    party=obj.get('party_size',old['party_size'] if old else None)
    if not isinstance(party,int) or isinstance(party,bool) or party<1: fail(422,'validation_failed')
    if party>capacity: fail(422,'party_exceeds_capacity')
    local=obj.get('starts_at_local',old['starts_at_local'] if old else None)
    start=parse_stamp(local,r['timezone'])
    day=start.date(); oh=opening(r,day)
    if not oh: fail(422,'outside_opening_hours')
    opens=datetime.combine(day,time.fromisoformat(oh['opens']))
    closes=datetime.combine(day,time.fromisoformat(oh['closes']))
    open_dt=parse_stamp(day.strftime('%Y-%m-%dT')+oh['opens'],r['timezone']).astimezone(timezone.utc)
    close_dt=parse_stamp(day.strftime('%Y-%m-%dT')+oh['closes'],r['timezone']).astimezone(timezone.utc)
    if start.astimezone(timezone.utc)<open_dt or start.astimezone(timezone.utc)+timedelta(minutes=r['reservation_duration_minutes'])>close_dt: fail(422,'outside_opening_hours')
    if (start.replace(tzinfo=None)-opens).total_seconds()%(r['slot_minutes']*60): fail(422,'not_on_slot_grid')
    a=start.astimezone(timezone.utc); b=a+timedelta(minutes=r['reservation_duration_minutes'])
    if check_occupancy:
        for x in s['reservations']:
            if x['status']!='confirmed' or x['id'] in excluded or x['restaurant_id']!=rid or not set(table_ids(x)).intersection(tids): continue
            xr=restaurant(s,x['restaurant_id']); xx=res_times(x,xr)
            if overlaps((a,b),xx): fail(409,'table_unavailable')
    return r,tids,party,local
def new_res(s,uid,r,tids,party,local,existing=None):
    if existing: return existing
    x={'id':'res_'+secrets.token_urlsafe(12),'reference':''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(8)),'user_id':uid,'restaurant_id':r['id'],'table_ids':list(tids),'party_size':party,'starts_at_local':local,'status':'confirmed','created_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if len(tids)==1: x['table_id']=tids[0]
    while any(q['reference']==x['reference'] for q in s['reservations']): x['reference']=''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(8))
    s['reservations'].append(x); return x
def validate_fixture(f):
    if not isinstance(f,dict) or not all(isinstance(f.get(k),list) for k in ('users','restaurants','reservations')): fail(422,'validation_failed')
    uids=[]; rids=[]; emails=set()
    for u in f['users']:
        if not isinstance(u,dict) or not valid_id(u.get('id')) or not isinstance(u.get('email'),str) or not isinstance(u.get('password'),str) or not isinstance(u.get('display_name'),str): fail(422,'validation_failed')
        if u['id'] in uids or u['email'].lower() in emails: fail(422,'validation_failed')
        uids.append(u['id']); emails.add(u['email'].lower())
    for r in f['restaurants']:
        if not isinstance(r,dict) or not valid_id(r.get('id')) or not isinstance(r.get('name'),str): fail(422,'validation_failed')
        if r['id'] in rids: fail(422,'validation_failed')
        rids.append(r['id'])
        try: ZoneInfo(r['timezone'])
        except Exception: fail(422,'validation_failed')
        for k in ('slot_minutes','reservation_duration_minutes','cancellation_cutoff_minutes'):
            if not isinstance(r.get(k),int) or isinstance(r[k],bool) or r[k]<0 or k in ('slot_minutes','reservation_duration_minutes') and r[k]==0: fail(422,'validation_failed')
        if not isinstance(r.get('tables'),list) or not isinstance(r.get('opening_hours'),list): fail(422,'validation_failed')
        table_ids=set(); weekdays=set()
        for t in r['tables']:
            if not isinstance(t,dict) or not valid_id(t.get('id')) or not isinstance(t.get('label'),str) or not isinstance(t.get('capacity'),int) or isinstance(t.get('capacity'),bool) or t['capacity']<1 or t['id'] in table_ids: fail(422,'validation_failed')
            table_ids.add(t['id'])
        for oh in r['opening_hours']:
            if not isinstance(oh,dict) or oh.get('weekday') not in WDAYS or oh['weekday'] in weekdays or not isinstance(oh.get('opens'),str) or not isinstance(oh.get('closes'),str): fail(422,'validation_failed')
            weekdays.add(oh['weekday'])
            try: op=time.fromisoformat(oh['opens']); cl=time.fromisoformat(oh['closes'])
            except Exception: fail(422,'validation_failed')
            if op>=cl or len(oh['opens'])!=5 or len(oh['closes'])!=5: fail(422,'validation_failed')
        combinable=r.get('combinable',[])
        if not isinstance(combinable,list): fail(422,'validation_failed')
        seen_pairs=set()
        for pair in combinable:
            if not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(tid,str) for tid in pair) or pair[0]==pair[1] or any(tid not in table_ids for tid in pair): fail(422,'validation_failed')
            identity=frozenset(pair)
            if identity in seen_pairs: fail(422,'validation_failed')
            seen_pairs.add(identity)
    reservation_ids=set(); reservation_refs=set()
    for x in f['reservations']:
        if not isinstance(x,dict): fail(422,'validation_failed')
        if not all(k in x for k in ('id','reference','user_id','restaurant_id','party_size','starts_at_local')) or not ('table_id' in x or 'table_ids' in x): fail(422,'validation_failed')
        if not valid_id(x['id']) or x['id'] in reservation_ids or not valid_reference(x['reference']) or x['reference'] in reservation_refs or x['user_id'] not in uids: fail(422,'validation_failed')
        if not isinstance(x['party_size'],int) or isinstance(x['party_size'],bool) or x['party_size']<1: fail(422,'validation_failed')
        r=next((q for q in f['restaurants'] if q['id']==x['restaurant_id']),None)
        tids=chosen_tables(x)
        if not r or not tids or len(set(tids))!=len(tids) or any(not any(t['id']==tid for t in r['tables']) for tid in tids) or not option_allowed(r,tids): fail(422,'validation_failed')
        tids=canonical_tables(r,tids); x['table_ids']=tids
        if len(tids)==1: x.setdefault('table_id',tids[0])
        if x.get('status','confirmed') not in ('confirmed','cancelled'): fail(422,'validation_failed')
        if 'created_at' in x and not isinstance(x['created_at'],str): fail(422,'validation_failed')
        parse_stamp(x['starts_at_local'],r['timezone'])
        reservation_ids.add(x['id']); reservation_refs.add(x['reference'])
    return True

def validate_import_state(s):
    if not isinstance(s,dict) or not all(isinstance(s.get(k),list) for k in ('users','restaurants','reservations')) or not isinstance(s.get('tokens'),dict) or not isinstance(s.get('receipts'),list): fail(422,'validation_failed')
    ids=set(); emails=set()
    for u in s['users']:
        if not isinstance(u,dict) or not valid_id(u.get('id')) or not isinstance(u.get('email'),str) or not isinstance(u.get('password_hash'),str) or not isinstance(u.get('display_name'),str): fail(422,'validation_failed')
        if u['id'] in ids or u['email'] in emails: fail(422,'validation_failed')
        ids.add(u['id']); emails.add(u['email'])
    restaurants=s['restaurants']; rids=set()
    for r in restaurants:
        if not isinstance(r,dict): fail(422,'validation_failed')
        validate_fixture({'users':[],'restaurants':[r],'reservations':[]})
        if r['id'] in rids: fail(422,'validation_failed')
        rids.add(r['id'])
    refs=set(); resids=set()
    for x in s['reservations']:
        if not isinstance(x,dict) or not all(k in x for k in ('id','reference','user_id','restaurant_id','party_size','starts_at_local','status','created_at')) or not ('table_id' in x or 'table_ids' in x): fail(422,'validation_failed')
        if not valid_id(x['id']) or not valid_reference(x['reference']) or not valid_id(x['user_id']) or not valid_id(x['restaurant_id']) or x['id'] in resids or x['reference'] in refs or x['user_id'] not in ids or x['restaurant_id'] not in rids: fail(422,'validation_failed')
        r=next(q for q in restaurants if q['id']==x['restaurant_id'])
        tids=chosen_tables(x)
        if not tids or len(set(tids))!=len(tids) or any(not any(t['id']==tid for t in r['tables']) for tid in tids) or not option_allowed(r,tids) or x['status'] not in ('confirmed','cancelled') or not isinstance(x['party_size'],int) or isinstance(x['party_size'],bool) or x['party_size']<1 or not isinstance(x['created_at'],str): fail(422,'validation_failed')
        tids=canonical_tables(r,tids); x['table_ids']=tids
        if len(tids)==1: x.setdefault('table_id',tids[0])
        parse_stamp(x['starts_at_local'],r['timezone']); resids.add(x['id']); refs.add(x['reference'])
    if any(not isinstance(token,str) or not valid_id(owner) or owner not in ids for token,owner in s['tokens'].items()): fail(422,'validation_failed')
    receipt_keys=set()
    for q in s['receipts']:
        if not isinstance(q,dict) or not all(k in q for k in ('user_id','key','method','path','body','response')): fail(422,'validation_failed')
        if not valid_id(q['user_id']) or not isinstance(q['key'],str) or not 1<=len(q['key'])<=255 or not isinstance(q['method'],str) or not isinstance(q['path'],str) or not isinstance(q['body'],str) or not isinstance(q['response'],dict): fail(422,'validation_failed')
        identity=(q['user_id'],q['key'],q['method'],q['path'])
        if q['user_id'] not in ids or identity in receipt_keys: fail(422,'validation_failed')
        try:
            if not isinstance(json.loads(q['body']),dict): fail(422,'validation_failed')
        except ApiError: raise
        except Exception: fail(422,'validation_failed')
        receipt_keys.add(identity)
    return True

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args): pass
    def send_error(self,code,message=None,explain=None):
        text=message or 'request error'
        self.send(code,{'error':{'code':'malformed_request' if code==400 else 'not_found','message':text}})
    def send(self,status,obj=None,content_type=None):
        if isinstance(obj,str): data=obj.encode('utf-8'); content_type=content_type or 'text/html; charset=utf-8'
        else: data=b'' if status==204 else json.dumps(obj,separators=(',',':'),ensure_ascii=False).encode(); content_type=content_type or 'application/json; charset=utf-8'
        self.send_response(status); self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(data))); self.end_headers()
        if data: self.wfile.write(data)
    def readbody(self):
        try: return parse_json(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        except ApiError: raise
        except Exception: fail(400,'malformed_request')
    def read_asset(self,name):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),name),encoding='utf-8') as asset: return asset.read()
    def do_GET(self): self.dispatch()
    def do_POST(self): self.dispatch()
    def do_PATCH(self): self.dispatch()
    def do_PUT(self): self.dispatch()
    def do_DELETE(self): self.dispatch()
    def do_OPTIONS(self): self.dispatch()
    def do_HEAD(self): self.dispatch()
    def dispatch(self):
        if not self.path.startswith('/'): return
        try:
            with LOCK:
                result=self.route()
            self.send(*result)
        except ApiError as e: self.send(e.status,{'error':{'code':e.code,'message':e.message}})
        except Exception: self.send(500,{'error':{'code':'internal_error','message':'internal error'}})
    def route(self):
        method=self.command; path=urlparse(self.path).path; qs=parse_qs(urlparse(self.path).query,keep_blank_values=True)
        public=path in ('/','/signup','/login','/lookup','/app.js','/style.css','/health','/_test/reset','/_test/import','/_test/export','/auth/signup','/auth/login','/restaurants','/availability') or re.fullmatch(r'/restaurants/[^/]+',path)
        s=state(); uid=None; obj=None
        wants_body=method=='PATCH' or method=='POST' and (path in ('/_test/reset','/_test/import','/auth/signup','/auth/login','/reservations','/reservation-moves'))
        if wants_body: obj=self.readbody()
        if not public: uid=auth(self,s)
        if method=='GET' and path in ('/','/signup','/login','/lookup'):
            return 200,self.read_asset('index.html'),'text/html; charset=utf-8'
        if method=='GET' and path in ('/app.js','/style.css'):
            name='app.js' if path=='/app.js' else 'style.css'
            kind='text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8'
            return 200,self.read_asset(name),kind
        if path=='/health' and method=='GET': return 200,{'status':'ok'}
        if path=='/_test/reset' and method=='POST':
            validate_fixture(obj)
            ns={'users':[],'restaurants':obj['restaurants'],'reservations':[],'tokens':{},'receipts':[]}
            for u in obj['users']: ns['users'].append({'id':u['id'],'email':u['email'].lower(),'password_hash':hashpw(u['password']),'display_name':u['display_name']})
            for rr in obj['reservations']:
                x={**rr,'user_id':rr.get('user_id'),'status':rr.get('status','confirmed')}
                if not all(k in x for k in ('id','reference','user_id','restaurant_id','party_size','starts_at_local')) or not ('table_id' in x or 'table_ids' in x): fail(422,'validation_failed')
                x.setdefault('created_at',datetime.now(timezone.utc).isoformat(timespec='seconds')); ns['reservations'].append(x)
            save(ns); return 204,None
        if path=='/_test/export' and method=='GET': return 200,{'track':'tablekeeper','format_version':1,'state':s}
        if path=='/_test/import' and method=='POST':
            if obj.get('track')!='tablekeeper' or obj.get('format_version')!=1: fail(422,'validation_failed')
            ns=obj.get('state'); validate_import_state(ns)
            save(ns); return 204,None
        if path=='/auth/signup' and method=='POST':
            email=body_type(obj,'email',str).lower(); pw=body_type(obj,'password',str); name=body_type(obj,'display_name',str)
            if not re.fullmatch(r'[^@\s]+@[^@\s]+',email) or len(pw)<8: fail(422,'validation_failed')
            if any(u['email']==email for u in s['users']): fail(409,'email_taken')
            u={'id':'u_'+secrets.token_urlsafe(10),'email':email,'password_hash':hashpw(pw),'display_name':name}; token=secrets.token_urlsafe(32); s['users'].append(u); s['tokens'][token]=u['id']; save(s)
            return 201,{'user_id':u['id'],'display_name':name,'token':token}
        if path=='/auth/login' and method=='POST':
            email=body_type(obj,'email',str).lower(); pw=body_type(obj,'password',str); u=next((u for u in s['users'] if u['email']==email),None)
            if not u or not checkpw(pw,u['password_hash']): fail(401,'unauthenticated')
            token=secrets.token_urlsafe(32); s['tokens'][token]=u['id']; save(s); return 200,{'user_id':u['id'],'display_name':u['display_name'],'token':token}
        if path=='/restaurants' and method=='GET': return 200,{'restaurants':[{'id':r['id'],'name':r.get('name',''),'timezone':r['timezone']} for r in s['restaurants']]}
        m=re.fullmatch(r'/restaurants/([^/]+)',path)
        if m and method=='GET':
            r=restaurant(s,m.group(1)); out={k:r[k] for k in ('id','name','timezone','slot_minutes','reservation_duration_minutes','cancellation_cutoff_minutes','opening_hours','tables')}; out['combinable']=allowed_combinations(r); return 200,out
        if path=='/availability' and method=='GET':
            if any(k not in qs for k in ('restaurant_id','date','party_size')): fail(422,'validation_failed')
            rid=qs['restaurant_id'][0]; ds=qs['date'][0]; ps=qs['party_size'][0]
            if not re.fullmatch(r'\d+',ps) or int(ps)<1: fail(422,'validation_failed')
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',ds): fail(422,'validation_failed')
            try: day=date.fromisoformat(ds)
            except Exception: fail(422,'validation_failed')
            r=restaurant(s,rid); oh=opening(r,day); slots=[]
            if oh:
                opens=datetime.combine(day,time.fromisoformat(oh['opens'])); closes=datetime.combine(day,time.fromisoformat(oh['closes']))
                close_local=day.strftime('%Y-%m-%dT')+oh['closes']
                close_utc=parse_stamp(close_local,r['timezone']).astimezone(timezone.utc)
                naive=opens
                while naive<closes:
                    local=naive.strftime('%Y-%m-%dT%H:%M')
                    try: start=parse_stamp(local,r['timezone']); a=start.astimezone(timezone.utc); b=a+timedelta(minutes=r['reservation_duration_minutes'])
                    except ApiError as e:
                        if e.code=='invalid_local_time': naive+=timedelta(minutes=r['slot_minutes']); continue
                        raise
                    if b>close_utc:
                        naive+=timedelta(minutes=r['slot_minutes']); continue
                    avail=[]; options=[]
                    declared=[[t['id']] for t in r['tables']]+allowed_combinations(r)
                    for ids in declared:
                        capacity=sum(next(t['capacity'] for t in r['tables'] if t['id']==tid) for tid in ids)
                        if capacity<int(ps) or not option_free(s,rid,ids,a,b): continue
                        options.append({'table_ids':ids,'capacity':capacity})
                        if len(ids)==1: avail.append(ids[0])
                    slots.append({'starts_at_local':local,'starts_at':iso(start),'available_table_ids':avail,'available_options':options})
                    naive+=timedelta(minutes=r['slot_minutes'])
            return 200,{'restaurant_id':rid,'date':ds,'timezone':r['timezone'],'slots':slots}
        if path=='/reservations' and method=='POST':
            return self.idempotent(s,uid,obj,'POST',path,lambda: self.create(s,uid,obj))
        if path=='/reservations' and method=='GET':
            xs=[x for x in s['reservations'] if x['user_id']==uid]; xs.sort(key=lambda x:res_times(x,restaurant(s,x['restaurant_id']))[0],reverse=True)
            return 200,{'reservations':[reservation_view(x,restaurant(s,x['restaurant_id'])) for x in xs]}
        m=re.fullmatch(r'/reservations/([^/]+)',path)
        if m and method=='GET':
            x=next((x for x in s['reservations'] if x['reference']==m.group(1) and x['user_id']==uid),None)
            if not x: fail(404,'not_found')
            return 200,reservation_view(x,restaurant(s,x['restaurant_id']))
        m=re.fullmatch(r'/reservations/([^/]+)/(cancel)',path)
        if m and method=='POST':
            x=next((x for x in s['reservations'] if x['reference']==m.group(1) and x['user_id']==uid),None)
            if not x: fail(404,'not_found')
            if x['status']!='cancelled':
                r=restaurant(s,x['restaurant_id']); start,_=res_times(x,r)
                if datetime.now(timezone.utc)>=start-timedelta(minutes=r['cancellation_cutoff_minutes']): fail(409,'cutoff_passed')
                x['status']='cancelled'; save(s)
            return 200,reservation_view(x,restaurant(s,x['restaurant_id']))
        m=re.fullmatch(r'/reservations/([^/]+)',path)
        if m and method=='PATCH':
            x=next((x for x in s['reservations'] if x['reference']==m.group(1) and x['user_id']==uid),None)
            if not x: fail(404,'not_found')
            if x['status']=='cancelled': fail(409,'reservation_cancelled')
            r=restaurant(s,x['restaurant_id']); start,_=res_times(x,r)
            if datetime.now(timezone.utc)>=start-timedelta(minutes=r['cancellation_cutoff_minutes']): fail(409,'cutoff_passed')
            changes={k:v for k,v in obj.items() if k in ('table_id','table_ids','starts_at_local','party_size')}
            if 'table_id' in changes and 'table_ids' in changes: fail(422,'validation_failed')
            new=dict(x)
            if 'table_ids' in changes: new.pop('table_id',None)
            if 'table_id' in changes: new.pop('table_ids',None)
            new.update(changes); self.validate_extra(new,changes); rr,tids,party,local=validate_booking(s,uid,new,x,excluded=(x['id'],)); x.update(table_ids=tids,party_size=party,starts_at_local=local)
            if len(tids)==1: x['table_id']=tids[0]
            else: x.pop('table_id',None)
            save(s)
            return 200,reservation_view(x,rr)
        if path=='/reservation-moves' and method=='POST':
            return self.idempotent(s,uid,obj,'POST',path,lambda: self.move(s,uid,obj))
        fail(404,'not_found')
    def validate_extra(self,obj,fields):
        for k,t in [('restaurant_id',str),('table_id',str),('starts_at_local',str),('party_size',int)]:
            if k in fields and (not isinstance(fields[k],t) or t is int and isinstance(fields[k],bool)):
                if k=='party_size': fail(422,'validation_failed')
                fail(400,'malformed_request')
        if 'table_ids' in fields and (not isinstance(fields['table_ids'],list) or any(not isinstance(t,str) for t in fields['table_ids'])): fail(400,'malformed_request')
    def idempotent(self,s,uid,obj,method,path,operation):
        key=self.headers.get('Idempotency-Key')
        if key is None or key=='': fail(400,'missing_idempotency_key')
        if len(key)>255: fail(422,'validation_failed')
        canonical=json.dumps(obj,sort_keys=True,separators=(',',':'))
        existing=next((x for x in s['receipts'] if x['user_id']==uid and x['key']==key and x['method']==method and x['path']==path),None)
        if existing:
            if existing['body']!=canonical: fail(409,'idempotency_key_reuse')
            return 200,existing['response']
        try: status,response=operation()
        except ApiError: raise
        if status>=400: return status,response
        s=state(); s['receipts'].append({'user_id':uid,'key':key,'method':method,'path':path,'body':canonical,'response':response}); save(s)
        return status,response
    def create(self,s,uid,obj):
        self.validate_extra(obj,obj)
        if 'table_id' in obj and 'table_ids' in obj: fail(422,'validation_failed')
        for k in ('restaurant_id','starts_at_local','party_size'):
            if k not in obj: fail(422,'validation_failed')
        if not ('table_id' in obj or 'table_ids' in obj): fail(422,'validation_failed')
        r,tids,p,l=validate_booking(s,uid,obj); x=new_res(s,uid,r,tids,p,l); save(s); return 201,reservation_view(x,r)
    def move(self,s,uid,obj):
        moves=obj.get('moves')
        if not isinstance(moves,list) or not 1<=len(moves)<=8 or any(not isinstance(x,dict) for x in moves): fail(422,'validation_failed')
        refs=[x.get('reference') for x in moves]
        if any(not isinstance(x,str) for x in refs) or len(set(refs))!=len(refs): fail(422,'validation_failed')
        rows=[]
        for ref in refs:
            x=next((q for q in s['reservations'] if q['reference']==ref and q['user_id']==uid),None)
            if not x: fail(404,'not_found')
            rows.append(x)
        if len({x['restaurant_id'] for x in rows})!=1: fail(422,'validation_failed')
        self.validate_extra({}, {})
        cloned=json.loads(json.dumps(s)); rows=[next(q for q in cloned['reservations'] if q['id']==x['id']) for x in rows]; ids=[x['id'] for x in rows]
        # Validate in request order against all non-listed bookings, then pairwise resulting occupancy.
        candidates=[]
        for item,x in zip(moves,rows):
            if x['status']=='cancelled': fail(409,'reservation_cancelled')
            r0=restaurant(cloned,x['restaurant_id']); start,_=res_times(x,r0)
            if datetime.now(timezone.utc)>=start-timedelta(minutes=r0['cancellation_cutoff_minutes']): fail(409,'cutoff_passed')
            changes={k:v for k,v in item.items() if k in ('table_id','table_ids','starts_at_local','party_size')}
            data=dict(x)
            if 'table_ids' in changes: data.pop('table_id',None)
            if 'table_id' in changes: data.pop('table_ids',None)
            data.update(changes)
            if 'table_id' in item and 'table_ids' in item: fail(422,'validation_failed')
            self.validate_extra(data,changes)
            r,t,p,l=validate_booking(cloned,uid,data,x,excluded=tuple(ids),check_occupancy=False); candidates.append((x,r,t,p,l))
        for x,r,t,p,l in candidates:
            a,b=res_times({**x,'starts_at_local':l},r)
            for external in cloned['reservations']:
                if external['status']!='confirmed' or external['id'] in ids or external['restaurant_id']!=r['id'] or not set(table_ids(external)).intersection(t): continue
                if overlaps((a,b),res_times(external,r)): fail(409,'table_unavailable')
        occ=[]
        for index,(x,r,t,p,l) in enumerate(candidates):
            a,b=res_times({**x,'starts_at_local':l},r)
            for j,(y,rr,tt,pp,ll) in enumerate(candidates[:index]):
                if set(t).intersection(tt) and overlaps((a,b),res_times({**y,'starts_at_local':ll},rr)): fail(409,'table_unavailable')
            occ.append((t,a,b))
        for x,r,t,p,l in candidates:
            x.update(table_ids=t,party_size=p,starts_at_local=l)
            if len(t)==1: x['table_id']=t[0]
            else: x.pop('table_id',None)
        save(cloned); return 201,{'reservations':[reservation_view(x,r) for x,r,t,p,l in candidates]}

def main():
    server=ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),Handler)
    server.daemon_threads=True; server.serve_forever()
if __name__=='__main__': main()
