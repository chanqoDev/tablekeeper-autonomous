#!/usr/bin/env python3
"""Tablekeeper Stage 3 policy, history, series API and browser application."""
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

def state():
    value=json.loads(DB.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    return upgrade_state(value)
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
def policy_zero(r):
    return {'policy_version':0,'slot_minutes':r['slot_minutes'],'reservation_duration_minutes':r['reservation_duration_minutes'],'cancellation_cutoff_minutes':r['cancellation_cutoff_minutes'],'opening_hours':json.loads(json.dumps(r.get('opening_hours',[]))),'capacities':{t['id']:t['capacity'] for t in r.get('tables',[])}}
def policy_terms(s,r,day):
    date_value=day.isoformat() if isinstance(day,date) else str(day)
    candidates=[p for p in s.get('policies',[]) if p.get('restaurant_id')==r['id'] and p.get('effective_from','9999-99-99')<=date_value]
    if not candidates: return policy_zero(r)
    chosen=max(candidates,key=lambda p:(p['effective_from'],p['policy_version']))
    return {k:json.loads(json.dumps(chosen[k])) for k in ('policy_version','slot_minutes','reservation_duration_minutes','cancellation_cutoff_minutes','opening_hours','capacities')}
def upgrade_state(s):
    dirty=False
    for key,default in (('policies',[]),('history',{}),('series',[]),('restaurant_revisions',{})):
        if key not in s: s[key]=default; dirty=True
    revisions=s['restaurant_revisions']
    for r in s.get('restaurants',[]):
        if 'manager_user_ids' not in r: r['manager_user_ids']=[]; dirty=True
        if r['id'] not in revisions: revisions[r['id']]=0; dirty=True
    for reservation in s.get('reservations',[]):
        r=next((q for q in s.get('restaurants',[]) if q['id']==reservation.get('restaurant_id')),None)
        if not r: continue
        if 'revision' not in reservation: reservation['revision']=1; dirty=True
        if 'accepted_terms' not in reservation:
            reservation['accepted_terms']=policy_zero(r); dirty=True
        reference=reservation.get('reference')
        if reference and not s['history'].get(reference):
            ids=table_ids(reservation)
            changes=[{'field':'table_ids' if len(ids)>1 else 'table_id','from':None,'to':ids if len(ids)>1 else (ids[0] if ids else None)}, {'field':'starts_at_local','from':None,'to':reservation.get('starts_at_local')}, {'field':'party_size','from':None,'to':reservation.get('party_size')}]
            history_event(s,reservation,'created',changes,at_override=reservation.get('created_at'))
            dirty=True
    return s
def history_event(s,reservation,event,changes,at_override=None):
    r=next((q for q in s.get('restaurants',[]) if q['id']==reservation.get('restaurant_id')),None)
    if at_override:
        try: instant=datetime.fromisoformat(at_override.replace('Z','+00:00'))
        except Exception: instant=datetime.now(timezone.utc)
    else: instant=datetime.now(timezone.utc)
    entries=s.setdefault('history',{}).setdefault(reservation['reference'],[])
    if entries:
        previous=datetime.fromisoformat(entries[-1]['at'].replace('Z','+00:00')).astimezone(timezone.utc)
        if instant.astimezone(timezone.utc)<=previous: instant=(previous+timedelta(microseconds=1)).astimezone(timezone.utc)
    at=instant.astimezone(ZoneInfo(r['timezone'])).isoformat() if r else instant.astimezone(timezone.utc).isoformat()
    entries.append({'seq':len(entries)+1,'at':at,'event':event,'changes':changes,'revision':reservation.get('revision',1),'accepted_terms':json.loads(json.dumps(reservation.get('accepted_terms',{})))})
    return entries[-1]
def terms_for_response(terms):
    return {k:json.loads(json.dumps(terms[k])) for k in ('policy_version','slot_minutes','reservation_duration_minutes','cancellation_cutoff_minutes','opening_hours','capacities')}
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
    terms=res.get('accepted_terms') or policy_zero(r)
    end=start+timedelta(minutes=terms['reservation_duration_minutes'])
    return start,end
def terms_times(local,r,terms):
    start=parse_stamp(local,r['timezone']).astimezone(timezone.utc)
    return start,start+timedelta(minutes=terms['reservation_duration_minutes'])
def table_ids(res):
    ids=res.get('table_ids')
    if isinstance(ids,list) and ids: return ids
    return [res['table_id']] if isinstance(res.get('table_id'),str) else []
def reservation_view(res,r):
    start,end=res_times(res,r); ids=table_ids(res)
    out={'reservation_id':res['id'],'reference':res['reference'],'restaurant_id':res['restaurant_id'],'table_ids':ids,'party_size':res['party_size'],'status':res['status'],'starts_at_local':res['starts_at_local'],'starts_at':local_iso(start,r['timezone']),'ends_at':local_iso(end,r['timezone']),'created_at':res['created_at'],'revision':res.get('revision',1),'accepted_terms':terms_for_response(res.get('accepted_terms') or policy_zero(r))}
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
def validate_booking(s,uid,obj,old=None,excluded=(),check_occupancy=True,terms=None):
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
    party=obj.get('party_size',old['party_size'] if old else None)
    if not isinstance(party,int) or isinstance(party,bool) or party<1: fail(422,'validation_failed')
    local=obj.get('starts_at_local',old['starts_at_local'] if old else None)
    start=parse_stamp(local,r['timezone'])
    day=start.date(); terms=terms or policy_terms(s,r,day)
    capacity=sum(terms['capacities'][tid] for tid in tids)
    if party>capacity: fail(422,'party_exceeds_capacity')
    oh=next((x for x in terms['opening_hours'] if x.get('weekday')==WDAYS[day.weekday()]),None)
    if not oh: fail(422,'outside_opening_hours')
    opens=datetime.combine(day,time.fromisoformat(oh['opens']))
    closes=datetime.combine(day,time.fromisoformat(oh['closes']))
    open_dt=parse_stamp(day.strftime('%Y-%m-%dT')+oh['opens'],r['timezone']).astimezone(timezone.utc)
    close_dt=parse_stamp(day.strftime('%Y-%m-%dT')+oh['closes'],r['timezone']).astimezone(timezone.utc)
    duration=terms['reservation_duration_minutes']
    if start.astimezone(timezone.utc)<open_dt or start.astimezone(timezone.utc)+timedelta(minutes=duration)>close_dt: fail(422,'outside_opening_hours')
    if (start.replace(tzinfo=None)-opens).total_seconds()%(terms['slot_minutes']*60): fail(422,'not_on_slot_grid')
    a=start.astimezone(timezone.utc); b=a+timedelta(minutes=duration)
    if check_occupancy:
        for x in s['reservations']:
            if x['status']!='confirmed' or x['id'] in excluded or x['restaurant_id']!=rid or not set(table_ids(x)).intersection(tids): continue
            xr=restaurant(s,x['restaurant_id']); xx=res_times(x,xr)
            if overlaps((a,b),xx): fail(409,'table_unavailable')
    return r,tids,party,local,terms
def new_res(s,uid,r,tids,party,local,terms,existing=None):
    if existing: return existing
    x={'id':'res_'+secrets.token_urlsafe(12),'reference':''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(8)),'user_id':uid,'restaurant_id':r['id'],'table_ids':list(tids),'party_size':party,'starts_at_local':local,'status':'confirmed','created_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'revision':1,'accepted_terms':terms_for_response(terms)}
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
        managers=r.get('manager_user_ids',[])
        if not isinstance(managers,list) or any(not isinstance(uid,str) or uid not in uids for uid in managers) or len(set(managers))!=len(managers): fail(422,'validation_failed')
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

def validate_policy(r,obj):
    required=('effective_from','slot_minutes','reservation_duration_minutes','cancellation_cutoff_minutes','opening_hours','capacities')
    if not isinstance(obj,dict) or any(k not in obj for k in required): fail(422,'validation_failed')
    effective=obj['effective_from']
    if not isinstance(effective,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',effective): fail(422,'validation_failed')
    try:
        if date.fromisoformat(effective).isoformat()!=effective: fail(422,'validation_failed')
    except Exception: fail(422,'validation_failed')
    for key,low,high in (('slot_minutes',1,1440),('reservation_duration_minutes',1,1440),('cancellation_cutoff_minutes',0,10080)):
        value=obj[key]
        if not isinstance(value,int) or isinstance(value,bool) or not low<=value<=high: fail(422,'validation_failed')
    hours=obj['opening_hours']
    if not isinstance(hours,list): fail(422,'validation_failed')
    weekdays=set()
    for oh in hours:
        if not isinstance(oh,dict) or oh.get('weekday') not in WDAYS or oh['weekday'] in weekdays or not isinstance(oh.get('opens'),str) or not isinstance(oh.get('closes'),str) or len(oh['opens'])!=5 or len(oh['closes'])!=5: fail(422,'validation_failed')
        weekdays.add(oh['weekday'])
        try: op=time.fromisoformat(oh['opens']); cl=time.fromisoformat(oh['closes'])
        except Exception: fail(422,'validation_failed')
        if op>=cl: fail(422,'validation_failed')
    capacities=obj['capacities']; expected={t['id'] for t in r.get('tables',[])}
    if not isinstance(capacities,dict) or set(capacities)!=expected: fail(422,'validation_failed')
    if any(not isinstance(value,int) or isinstance(value,bool) or not 1<=value<=100 for value in capacities.values()): fail(422,'validation_failed')
    return {k:json.loads(json.dumps(obj[k])) for k in required}

def validate_terms_snapshot(r,terms,known_policies):
    if not isinstance(terms,dict): fail(422,'validation_failed')
    version=terms.get('policy_version')
    if not isinstance(version,int) or isinstance(version,bool) or version<0: fail(422,'validation_failed')
    fields=('slot_minutes','reservation_duration_minutes','cancellation_cutoff_minutes','opening_hours','capacities')
    for field,low in (('slot_minutes',1),('reservation_duration_minutes',1),('cancellation_cutoff_minutes',0)):
        value=terms.get(field)
        if not isinstance(value,int) or isinstance(value,bool) or value<low: fail(422,'validation_failed')
        # Policy 0 is the original Stage 1 fixture configuration. Its range
        # must remain importable even where Stage 3 policies add upper bounds.
        if version>0 and value>(10080 if field=='cancellation_cutoff_minutes' else 1440): fail(422,'validation_failed')
    hours=terms.get('opening_hours')
    if not isinstance(hours,list): fail(422,'validation_failed')
    seen=set()
    for item in hours:
        if not isinstance(item,dict) or item.get('weekday') not in WDAYS or item['weekday'] in seen or not isinstance(item.get('opens'),str) or not isinstance(item.get('closes'),str) or len(item['opens'])!=5 or len(item['closes'])!=5: fail(422,'validation_failed')
        seen.add(item['weekday'])
        try: opens=time.fromisoformat(item['opens']); closes=time.fromisoformat(item['closes'])
        except Exception: fail(422,'validation_failed')
        if opens>=closes: fail(422,'validation_failed')
    capacities=terms.get('capacities')
    expected={table['id'] for table in r.get('tables',[])}
    if not isinstance(capacities,dict) or set(capacities)!=expected: fail(422,'validation_failed')
    for value in capacities.values():
        if not isinstance(value,int) or isinstance(value,bool) or value<1 or version>0 and value>100: fail(422,'validation_failed')
    snapshot={field:json.loads(json.dumps(terms[field])) for field in fields}
    snapshot['policy_version']=version
    if version==0:
        if snapshot!=policy_zero(r): fail(422,'validation_failed')
    else:
        published=next((policy for policy in known_policies if policy['restaurant_id']==r['id'] and policy['policy_version']==version),None)
        if not published or any(snapshot[field]!=published[field] for field in ('policy_version',)+fields): fail(422,'validation_failed')
    return snapshot

def validate_import_state(s):
    try:
        _validate_import_state(s)
    except ApiError as e:
        # Imports have one public validation error regardless of which shared
        # fixture/booking helper detected the malformed value.
        if e.status == 422 and e.code == 'validation_failed': raise
        fail(422,'validation_failed')
    except Exception:
        # Never expose an internal type error for an invalid imported state.
        fail(422,'validation_failed')

def _validate_import_state(s):
    if not isinstance(s,dict) or not all(isinstance(s.get(k),list) for k in ('users','restaurants','reservations')) or not isinstance(s.get('tokens'),dict) or not isinstance(s.get('receipts'),list): fail(422,'validation_failed')
    ids=set(); emails=set()
    for u in s['users']:
        if not isinstance(u,dict) or not valid_id(u.get('id')) or not isinstance(u.get('email'),str) or not isinstance(u.get('password_hash'),str) or not isinstance(u.get('display_name'),str): fail(422,'validation_failed')
        if u['id'] in ids or u['email'] in emails: fail(422,'validation_failed')
        ids.add(u['id']); emails.add(u['email'])
    restaurants=s['restaurants']; rids=set()
    fixture_users=[{'id':u['id'],'email':u['email'],'password':'imported-password','display_name':u['display_name']} for u in s['users']]
    for r in restaurants:
        if not isinstance(r,dict): fail(422,'validation_failed')
        validate_fixture({'users':fixture_users,'restaurants':[r],'reservations':[]})
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
    policies=s.get('policies',[])
    if not isinstance(policies,list): fail(422,'validation_failed')
    versions={rid:0 for rid in rids}
    for p in policies:
        if not isinstance(p,dict) or not valid_id(p.get('restaurant_id')) or p['restaurant_id'] not in rids: fail(422,'validation_failed')
        rid=p['restaurant_id']; version=p.get('policy_version')
        if not isinstance(version,int) or isinstance(version,bool) or version!=versions[rid]+1: fail(422,'validation_failed')
        r=next(x for x in restaurants if x['id']==rid)
        validate_policy(r,p)
        versions[rid]=version
    for x in s['reservations']:
        r=next(q for q in restaurants if q['id']==x['restaurant_id'])
        revision=x.get('revision',1)
        if not isinstance(revision,int) or isinstance(revision,bool) or revision<1: fail(422,'validation_failed')
        terms=x.get('accepted_terms')
        if terms is not None:
            x['accepted_terms']=validate_terms_snapshot(r,terms,policies)
    histories=s.get('history',{})
    if not isinstance(histories,dict): fail(422,'validation_failed')
    reservations_by_ref={x['reference']:x for x in s['reservations']}
    if 'history' in s:
        for reservation in s['reservations']:
            entries=histories.get(reservation['reference'])
            if not isinstance(entries,list) or len(entries)!=reservation.get('revision',1): fail(422,'validation_failed')
    for ref,entries in histories.items():
        if ref not in reservations_by_ref or not isinstance(entries,list): fail(422,'validation_failed')
        if entries and entries[0].get('event')!='created': fail(422,'validation_failed')
        previous_at=None
        for index,e in enumerate(entries,1):
            if not isinstance(e,dict) or not isinstance(e.get('seq'),int) or isinstance(e.get('seq'),bool) or e['seq']!=index or e.get('event') not in ('created','changed','cancelled') or not isinstance(e.get('at'),str) or not isinstance(e.get('changes'),list): fail(422,'validation_failed')
            try:
                event_at=datetime.fromisoformat(e['at'].replace('Z','+00:00'))
                if event_at.utcoffset() is None: fail(422,'validation_failed')
                event_utc=event_at.astimezone(timezone.utc)
                if previous_at is not None and event_utc<=previous_at: fail(422,'validation_failed')
                previous_at=event_utc
            except Exception: fail(422,'validation_failed')
            if any(not isinstance(change,dict) or change.get('field') not in ('table_id','table_ids','starts_at_local','party_size') or 'from' not in change or 'to' not in change for change in e['changes']): fail(422,'validation_failed')
            if e['event']=='created' and (index!=1 or len(e['changes'])!=3 or [change['field'] for change in e['changes']][1:]!=['starts_at_local','party_size'] or e['changes'][0]['field'] not in ('table_id','table_ids') or any(change['from'] is not None for change in e['changes'])): fail(422,'validation_failed')
            if e['event']=='cancelled' and (e['changes'] or index!=len(entries)): fail(422,'validation_failed')
            if e['event']=='changed':
                order={'table_id':0,'table_ids':0,'starts_at_local':1,'party_size':2}
                if not e['changes'] or any(change['from']==change['to'] for change in e['changes']) or [order[c['field']] for c in e['changes']]!=sorted(order[c['field']] for c in e['changes']): fail(422,'validation_failed')
            rev=e.get('revision'); terms=e.get('accepted_terms')
            if not isinstance(rev,int) or isinstance(rev,bool) or rev<1 or not isinstance(terms,dict): fail(422,'validation_failed')
            r=next(q for q in restaurants if q['id']==reservations_by_ref[ref]['restaurant_id'])
            e['accepted_terms']=validate_terms_snapshot(r,terms,policies)
            if rev!=index: fail(422,'validation_failed')
        if entries:
            current=reservations_by_ref[ref]
            if entries[-1]['revision']!=current.get('revision',1) or entries[-1]['accepted_terms']!=current.get('accepted_terms',policy_zero(next(q for q in restaurants if q['id']==current['restaurant_id']))): fail(422,'validation_failed')
    series_rows=s.get('series',[])
    if not isinstance(series_rows,list): fail(422,'validation_failed')
    series_ids=set(); linked_refs=set()
    for series in series_rows:
        if not isinstance(series,dict) or not valid_id(series.get('series_id')) or series['series_id'] in series_ids or not valid_id(series.get('user_id')) or series['user_id'] not in ids or not valid_id(series.get('restaurant_id')) or series['restaurant_id'] not in rids: fail(422,'validation_failed')
        count=series.get('count'); interval=series.get('interval_weeks'); revision=series.get('revision'); occurrences=series.get('occurrences')
        if not isinstance(count,int) or isinstance(count,bool) or not 2<=count<=12 or not isinstance(interval,int) or isinstance(interval,bool) or not 1<=interval<=4 or not isinstance(revision,int) or isinstance(revision,bool) or revision<1 or not isinstance(occurrences,list) or len(occurrences)!=count: fail(422,'validation_failed')
        for index,occurrence in enumerate(occurrences):
            ref=occurrence.get('reference') if isinstance(occurrence,dict) else None
            if not isinstance(ref,str): fail(422,'validation_failed')
            reservation=reservations_by_ref.get(ref)
            if not reservation or ref in linked_refs or occurrence.get('index')!=index or not isinstance(occurrence.get('exception'),bool) or reservation['user_id']!=series['user_id'] or reservation['restaurant_id']!=series['restaurant_id']: fail(422,'validation_failed')
            if reservation.get('series_id')!=series['series_id'] or reservation.get('series_index')!=index: fail(422,'validation_failed')
            linked_refs.add(ref)
        if occurrences[0]['reference']!=series.get('anchor_reference'): fail(422,'validation_failed')
        series_ids.add(series['series_id'])
    for reservation in s['reservations']:
        series_id=reservation.get('series_id')
        series_index=reservation.get('series_index')
        if series_id is None and series_index is None: continue
        if not valid_id(series_id) or not isinstance(series_index,int) or isinstance(series_index,bool): fail(422,'validation_failed')
        series=next((row for row in series_rows if row['series_id']==series_id),None)
        if not series or not 0<=series_index<len(series['occurrences']) or series['occurrences'][series_index]['reference']!=reservation['reference']: fail(422,'validation_failed')
    restaurant_revisions=s.get('restaurant_revisions',{})
    if not isinstance(restaurant_revisions,dict) or any(rid not in rids or not isinstance(rev,int) or isinstance(rev,bool) or rev<0 for rid,rev in restaurant_revisions.items()): fail(422,'validation_failed')
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
            # Browser documents and bundled assets are immutable and do not need
            # access to the SQLite-backed reservation state or its global lock.
            path=urlparse(self.path).path
            if self.command=='GET' and path in ('/','/signup','/login','/lookup','/app.js','/style.css'):
                if path in ('/','/signup','/login','/lookup'):
                    self.send(200,self.read_asset('index.html'),'text/html; charset=utf-8')
                else:
                    name='app.js' if path=='/app.js' else 'style.css'
                    kind='text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8'
                    self.send(200,self.read_asset(name),kind)
                return
            with LOCK:
                result=self.route()
            self.send(*result)
        except ApiError as e: self.send(e.status,{'error':{'code':e.code,'message':e.message}})
        except Exception: self.send(500,{'error':{'code':'internal_error','message':'internal error'}})
    def route(self):
        method=self.command; path=urlparse(self.path).path; qs=parse_qs(urlparse(self.path).query,keep_blank_values=True)
        policy_path=re.fullmatch(r'/restaurants/([^/]+)/policies',path)
        history_path=re.fullmatch(r'/reservations/([^/]+)/(history|decision)',path)
        series_path=re.fullmatch(r'/series/([^/]+)',path)
        public=path in ('/','/signup','/login','/lookup','/app.js','/style.css','/health','/_test/reset','/_test/import','/_test/export','/auth/signup','/auth/login','/restaurants','/availability') or re.fullmatch(r'/restaurants/[^/]+',path) or (policy_path and method=='GET') or (history_path and method=='GET') or (series_path and method=='GET')
        s=state(); uid=None; obj=None
        wants_body=method=='PATCH' or method=='POST' and (path in ('/_test/reset','/_test/import','/auth/signup','/auth/login','/reservations','/reservation-moves','/series') or policy_path)
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
            restaurants=[]
            for source in obj['restaurants']:
                r={**source,'combinable':source.get('combinable',[]),'manager_user_ids':source.get('manager_user_ids',[])}
                restaurants.append(r)
            ns={'users':[],'restaurants':restaurants,'reservations':[],'tokens':{},'receipts':[],'policies':[],'history':{},'series':[],'restaurant_revisions':{r['id']:0 for r in restaurants}}
            for u in obj['users']: ns['users'].append({'id':u['id'],'email':u['email'].lower(),'password_hash':hashpw(u['password']),'display_name':u['display_name']})
            for rr in obj['reservations']:
                x={**rr,'user_id':rr.get('user_id'),'status':rr.get('status','confirmed')}
                if not all(k in x for k in ('id','reference','user_id','restaurant_id','party_size','starts_at_local')) or not ('table_id' in x or 'table_ids' in x): fail(422,'validation_failed')
                r=restaurant(ns,x['restaurant_id']); tids=canonical_tables(r,table_ids(x)); x['table_ids']=tids
                if len(tids)==1: x.setdefault('table_id',tids[0])
                else: x.pop('table_id',None)
                x.setdefault('created_at',datetime.now(timezone.utc).isoformat(timespec='seconds')); x['revision']=1; x['accepted_terms']=policy_zero(r); ns['reservations'].append(x)
                fields=[{'field':'table_ids' if len(tids)>1 else 'table_id','from':None,'to':tids if len(tids)>1 else tids[0]}, {'field':'starts_at_local','from':None,'to':x['starts_at_local']}, {'field':'party_size','from':None,'to':x['party_size']}]
                history_event(ns,x,'created',fields,at_override=x['created_at'])
            save(ns); return 204,None
        if path=='/_test/export' and method=='GET': return 200,{'track':'tablekeeper','format_version':1,'state':s}
        if path=='/_test/import' and method=='POST':
            if obj.get('track')!='tablekeeper' or obj.get('format_version')!=1: fail(422,'validation_failed')
            ns=obj.get('state'); validate_import_state(ns); ns=upgrade_state(ns)
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
        if policy_path and method=='GET':
            r=restaurant(s,policy_path.group(1))
            policies=[{k:p[k] for k in ('effective_from','slot_minutes','reservation_duration_minutes','cancellation_cutoff_minutes','opening_hours','capacities','policy_version')} for p in s['policies'] if p['restaurant_id']==r['id']]
            return 200,{'policies':policies}
        if policy_path and method=='POST':
            return self.idempotent(s,uid,obj,'POST',path,lambda:self.publish_policy(s,uid,policy_path.group(1),obj))
        m=re.fullmatch(r'/restaurants/([^/]+)',path)
        if m and method=='GET':
            r=restaurant(s,m.group(1)); out={k:r[k] for k in ('id','name','timezone','slot_minutes','reservation_duration_minutes','cancellation_cutoff_minutes','opening_hours','tables')}; out['combinable']=allowed_combinations(r); return 200,out
        if history_path and method=='GET':
            token=self.headers.get('Authorization',''); caller=s.get('tokens',{}).get(token[7:]) if token.startswith('Bearer ') else None
            reservation=next((x for x in s['reservations'] if x['reference']==history_path.group(1) and x['user_id']==caller),None)
            if not reservation: fail(404,'not_found')
            if history_path.group(2)=='history': return 200,{'reference':reservation['reference'],'entries':json.loads(json.dumps(s['history'].get(reservation['reference'],[])))}
            return 200,{'reference':reservation['reference'],'revision':reservation['revision'],'accepted_terms':terms_for_response(reservation['accepted_terms'])}
        if series_path and method=='GET':
            token=self.headers.get('Authorization',''); caller=s.get('tokens',{}).get(token[7:]) if token.startswith('Bearer ') else None
            series=next((x for x in s['series'] if x['series_id']==series_path.group(1) and x['user_id']==caller),None)
            if not series: fail(404,'not_found')
            return 200,self.series_view(s,series)
        if path=='/availability' and method=='GET':
            if any(k not in qs for k in ('restaurant_id','date','party_size')): fail(422,'validation_failed')
            rid=qs['restaurant_id'][0]; ds=qs['date'][0]; ps=qs['party_size'][0]
            if not re.fullmatch(r'\d+',ps): fail(422,'validation_failed')
            try: party_size=int(ps)
            except (ValueError,OverflowError): fail(422,'validation_failed')
            if party_size<1: fail(422,'validation_failed')
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',ds): fail(422,'validation_failed')
            try: day=date.fromisoformat(ds)
            except Exception: fail(422,'validation_failed')
            explain_values=qs.get('explain')
            if explain_values is not None and explain_values!=['true']: fail(422,'validation_failed')
            explain=explain_values==['true']
            r=restaurant(s,rid); terms=policy_terms(s,r,day); oh=next((x for x in terms['opening_hours'] if x.get('weekday')==WDAYS[day.weekday()]),None); slots=[]
            if oh:
                opens=datetime.combine(day,time.fromisoformat(oh['opens'])); closes=datetime.combine(day,time.fromisoformat(oh['closes']))
                close_local=day.strftime('%Y-%m-%dT')+oh['closes']
                close_utc=parse_stamp(close_local,r['timezone']).astimezone(timezone.utc)
                naive=opens
                while naive<closes:
                    local=naive.strftime('%Y-%m-%dT%H:%M')
                    try: start=parse_stamp(local,r['timezone']); a=start.astimezone(timezone.utc)
                    except ApiError as e:
                        if e.code=='invalid_local_time': naive+=timedelta(minutes=terms['slot_minutes']); continue
                        raise
                    b=a+timedelta(minutes=terms['reservation_duration_minutes'])
                    if b>close_utc:
                        naive+=timedelta(minutes=terms['slot_minutes']); continue
                    avail=[]; options=[]; explanations=[]
                    for table in r['tables']:
                        tid=table['id']; cap_holds=terms['capacities'][tid]>=party_size; overlap_holds=option_free(s,rid,[tid],a,b); available=cap_holds and overlap_holds
                        if available: avail.append(tid)
                        if cap_holds and overlap_holds: options.append({'table_ids':[tid],'capacity':terms['capacities'][tid]})
                        if explain: explanations.append({'table_id':tid,'policy_version':terms['policy_version'],'available':available,'rules':[{'rule':'capacity','holds':cap_holds},{'rule':'no_overlap','holds':overlap_holds}]})
                    for pair in allowed_combinations(r):
                        capacity=sum(terms['capacities'][tid] for tid in pair); free=option_free(s,rid,pair,a,b)
                        if capacity>=party_size and free: options.append({'table_ids':pair,'capacity':capacity})
                    slot={'starts_at_local':local,'starts_at':iso(start),'available_table_ids':avail,'available_options':options}
                    if explain: slot['explain']=explanations
                    slots.append(slot)
                    naive+=timedelta(minutes=terms['slot_minutes'])
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
                cutoff=(x.get('accepted_terms') or policy_zero(r))['cancellation_cutoff_minutes']
                if datetime.now(timezone.utc)>=start-timedelta(minutes=cutoff): fail(409,'cutoff_passed')
                x['status']='cancelled'; x['revision']=x.get('revision',1)+1; history_event(s,x,'cancelled',[]); self.update_series_for_change(s,x,exception=False); save(s)
            return 200,reservation_view(x,restaurant(s,x['restaurant_id']))
        m=re.fullmatch(r'/reservations/([^/]+)',path)
        if m and method=='PATCH':
            x=next((x for x in s['reservations'] if x['reference']==m.group(1) and x['user_id']==uid),None)
            if not x: fail(404,'not_found')
            self.expected_revision(obj,x)
            if x['status']=='cancelled': fail(409,'reservation_cancelled')
            r=restaurant(s,x['restaurant_id']); start,_=res_times(x,r); cutoff=(x.get('accepted_terms') or policy_zero(r))['cancellation_cutoff_minutes']
            if datetime.now(timezone.utc)>=start-timedelta(minutes=cutoff): fail(409,'cutoff_passed')
            changes={k:v for k,v in obj.items() if k in ('table_id','table_ids','starts_at_local','party_size')}
            if 'table_id' in changes and 'table_ids' in changes: fail(422,'validation_failed')
            self.validate_extra(obj,changes)
            ids,local,party=self.canonical_core(r,changes,x)
            if ids==table_ids(x) and local==x['starts_at_local'] and party==x['party_size']:
                return 200,reservation_view(x,r)
            rr,tids,new_party,new_local,terms=validate_booking(s,uid,changes,x,excluded=(x['id'],))
            self.record_change(s,x,rr,tids,new_local,new_party,terms); self.update_series_for_change(s,x,exception=True)
            save(s)
            return 200,reservation_view(x,rr)
        if path=='/reservation-moves' and method=='POST':
            return self.idempotent(s,uid,obj,'POST',path,lambda: self.move(s,uid,obj))
        if path=='/series' and method=='POST':
            return self.idempotent(s,uid,obj,'POST',path,lambda:self.adopt_series(s,uid,obj))
        fail(404,'not_found')
    def validate_extra(self,obj,fields):
        for k,t in [('restaurant_id',str),('table_id',str),('starts_at_local',str),('party_size',int)]:
            if k in fields and (not isinstance(fields[k],t) or t is int and isinstance(fields[k],bool)):
                if k=='party_size': fail(422,'validation_failed')
                fail(400,'malformed_request')
        if 'table_ids' in fields and (not isinstance(fields['table_ids'],list) or any(not isinstance(t,str) for t in fields['table_ids'])): fail(400,'malformed_request')
        if 'expected_revision' in fields and (not isinstance(fields['expected_revision'],int) or isinstance(fields['expected_revision'],bool) or fields['expected_revision']<1): fail(422,'validation_failed')
    def publish_policy(self,s,uid,rid,obj):
        r=restaurant(s,rid)
        if uid not in r.get('manager_user_ids',[]): fail(403,'forbidden')
        clean=validate_policy(r,obj)
        version=max((p['policy_version'] for p in s['policies'] if p['restaurant_id']==rid),default=0)+1
        policy={**clean,'restaurant_id':rid,'policy_version':version}
        s['policies'].append(policy); s['restaurant_revisions'][rid]=s['restaurant_revisions'].get(rid,0)+1
        save(s)
        return 201,{**clean,'policy_version':version}
    def expected_revision(self,obj,reservation):
        if 'expected_revision' not in obj: return
        expected=obj['expected_revision']
        if not isinstance(expected,int) or isinstance(expected,bool) or expected<1: fail(422,'validation_failed')
        if expected!=reservation.get('revision',1): fail(409,'stale_revision')
    def canonical_core(self,r,obj,old):
        ids=chosen_tables(obj,old)
        if not ids: fail(422,'validation_failed')
        if len(set(ids))!=len(ids): fail(422,'validation_failed')
        if any(not any(t['id']==tid for t in r['tables']) for tid in ids): fail(404,'not_found')
        if not option_allowed(r,ids): fail(422,'combination_not_allowed')
        ids=canonical_tables(r,ids)
        local=obj.get('starts_at_local',old['starts_at_local'])
        party=obj.get('party_size',old['party_size'])
        return ids,local,party
    def record_change(self,s,reservation,r,ids,local,party,terms):
        old_ids=table_ids(reservation); old_local=reservation['starts_at_local']; old_party=reservation['party_size']
        changes=[]
        if ids!=old_ids:
            field='table_ids' if len(ids)>1 or len(old_ids)>1 else 'table_id'
            before=old_ids if field=='table_ids' else old_ids[0]
            after=ids if field=='table_ids' else ids[0]
            changes.append({'field':field,'from':before,'to':after})
        if local!=old_local: changes.append({'field':'starts_at_local','from':old_local,'to':local})
        if party!=old_party: changes.append({'field':'party_size','from':old_party,'to':party})
        if not changes: return False
        reservation.update(table_ids=ids,starts_at_local=local,party_size=party,accepted_terms=terms_for_response(terms),revision=reservation.get('revision',1)+1)
        if len(ids)==1: reservation['table_id']=ids[0]
        else: reservation.pop('table_id',None)
        history_event(s,reservation,'changed',changes)
        return True
    def update_series_for_change(self,s,reservation,exception=True):
        series_id=reservation.get('series_id')
        if not series_id: return
        series=next((x for x in s['series'] if x['series_id']==series_id),None)
        if not series: return
        series['revision']+=1
        occurrence=series['occurrences'][reservation['series_index']]
        if exception: occurrence['exception']=True
    def series_view(self,s,series):
        out={'series_id':series['series_id'],'revision':series['revision'],'interval_weeks':series['interval_weeks'],'occurrences':[]}
        for occurrence in series['occurrences']:
            reservation=next(x for x in s['reservations'] if x['reference']==occurrence['reference'])
            out['occurrences'].append({'index':occurrence['index'],'reference':occurrence['reference'],'exception':occurrence['exception'],'reservation':reservation_view(reservation,restaurant(s,reservation['restaurant_id']))})
        return out
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
        r,tids,p,l,terms=validate_booking(s,uid,obj); x=new_res(s,uid,r,tids,p,l,terms)
        ids=table_ids(x); history_event(s,x,'created',[{'field':'table_ids' if len(ids)>1 else 'table_id','from':None,'to':ids if len(ids)>1 else ids[0]},{'field':'starts_at_local','from':None,'to':l},{'field':'party_size','from':None,'to':p}]); save(s)
        return 201,reservation_view(x,r)
    def adopt_series(self,s,uid,obj):
        if not isinstance(obj.get('anchor_reference'),str):
            if 'anchor_reference' not in obj: fail(422,'validation_failed')
            fail(400,'malformed_request')
        count=obj.get('count'); interval=obj.get('interval_weeks')
        if not isinstance(count,int) or isinstance(count,bool) or not 2<=count<=12 or not isinstance(interval,int) or isinstance(interval,bool) or not 1<=interval<=4: fail(422,'validation_failed')
        anchor=next((x for x in s['reservations'] if x['reference']==obj['anchor_reference'] and x['user_id']==uid),None)
        if not anchor: fail(404,'not_found')
        if anchor['status']=='cancelled': fail(409,'reservation_cancelled')
        if anchor.get('series_id') or any(x['anchor_reference']==anchor['reference'] for x in s['series']): fail(409,'already_in_series')
        r=restaurant(s,anchor['restaurant_id']); start,_=res_times(anchor,r); cutoff=anchor['accepted_terms']['cancellation_cutoff_minutes']
        if datetime.now(timezone.utc)>=start-timedelta(minutes=cutoff): fail(409,'cutoff_passed')
        cloned=json.loads(json.dumps(s)); anchor_copy=next(x for x in cloned['reservations'] if x['reference']==anchor['reference'])
        series_id='series_'+secrets.token_urlsafe(12)
        series={'series_id':series_id,'user_id':uid,'restaurant_id':r['id'],'anchor_reference':anchor['reference'],'count':count,'interval_weeks':interval,'revision':1,'occurrences':[]}
        anchor_copy['series_id']=series_id; anchor_copy['series_index']=0
        series['occurrences'].append({'index':0,'reference':anchor_copy['reference'],'exception':False})
        local_dt=datetime.strptime(anchor_copy['starts_at_local'],'%Y-%m-%dT%H:%M')
        for index in range(1,count):
            day=local_dt.date()+timedelta(days=index*interval*7)
            local=day.strftime('%Y-%m-%dT')+local_dt.strftime('%H:%M')
            body={'restaurant_id':r['id'],'table_ids':table_ids(anchor_copy),'party_size':anchor_copy['party_size'],'starts_at_local':local}
            rr,tids,party,starts,terms=validate_booking(cloned,uid,body)
            occurrence=new_res(cloned,uid,rr,tids,party,starts,terms)
            occurrence['series_id']=series_id; occurrence['series_index']=index
            history_event(cloned,occurrence,'created',[{'field':'table_ids' if len(tids)>1 else 'table_id','from':None,'to':tids if len(tids)>1 else tids[0]},{'field':'starts_at_local','from':None,'to':starts},{'field':'party_size','from':None,'to':party}])
            series['occurrences'].append({'index':index,'reference':occurrence['reference'],'exception':False})
        cloned['series'].append(series); cloned['restaurant_revisions'][r['id']]=cloned['restaurant_revisions'].get(r['id'],0)+1
        save(cloned); return 201,self.series_view(cloned,series)
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
        cloned=json.loads(json.dumps(s)); rows=[next(q for q in cloned['reservations'] if q['id']==x['id']) for x in rows]; ids=[x['id'] for x in rows]
        candidates=[]
        for item,x in zip(moves,rows):
            self.expected_revision(item,x)
            if x['status']=='cancelled': fail(409,'reservation_cancelled')
            r0=restaurant(cloned,x['restaurant_id']); start,_=res_times(x,r0)
            cutoff=(x.get('accepted_terms') or policy_zero(r0))['cancellation_cutoff_minutes']
            if datetime.now(timezone.utc)>=start-timedelta(minutes=cutoff): fail(409,'cutoff_passed')
            changes={k:v for k,v in item.items() if k in ('table_id','table_ids','starts_at_local','party_size')}
            if 'table_id' in item and 'table_ids' in item: fail(422,'validation_failed')
            self.validate_extra(item,changes)
            t0,local0,party0=self.canonical_core(r0,changes,x)
            changed=(t0!=table_ids(x) or local0!=x['starts_at_local'] or party0!=x['party_size'])
            if changed:
                r,t,p,l,terms=validate_booking(cloned,uid,changes,x,excluded=tuple(ids),check_occupancy=False)
            else:
                r,t,p,l,terms=r0,t0,party0,local0,x['accepted_terms']
            candidates.append((x,r,t,p,l,terms,changed))
        for x,r,t,p,l,terms,changed in candidates:
            a,b=terms_times(l,r,terms)
            for external in cloned['reservations']:
                if external['status']!='confirmed' or external['id'] in ids or external['restaurant_id']!=r['id'] or not set(table_ids(external)).intersection(t): continue
                if overlaps((a,b),res_times(external,r)): fail(409,'table_unavailable')
        for index,(x,r,t,p,l,terms,changed) in enumerate(candidates):
            a,b=terms_times(l,r,terms)
            for j,(y,rr,tt,pp,ll,other_terms,other_changed) in enumerate(candidates[:index]):
                if set(t).intersection(tt) and overlaps((a,b),terms_times(ll,rr,other_terms)): fail(409,'table_unavailable')
        changed_series=set(); any_changed=False
        for x,r,t,p,l,terms,changed in candidates:
            if not changed: continue
            self.record_change(cloned,x,r,t,l,p,terms); any_changed=True
            if x.get('series_id'):
                series=next((q for q in cloned['series'] if q['series_id']==x['series_id']),None)
                if series:
                    changed_series.add(series['series_id']); series['occurrences'][x['series_index']]['exception']=True
        for sid in changed_series:
            series=next(q for q in cloned['series'] if q['series_id']==sid); series['revision']+=1
        if any_changed:
            rid=candidates[0][1]['id']; cloned['restaurant_revisions'][rid]=cloned['restaurant_revisions'].get(rid,0)+1
        save(cloned); return 201,{'reservations':[reservation_view(x,r) for x,r,t,p,l,terms,changed in candidates]}

def main():
    server=ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),Handler)
    server.daemon_threads=True; server.serve_forever()
if __name__=='__main__': main()
