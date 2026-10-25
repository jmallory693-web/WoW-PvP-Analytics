"""Permanent versioned rated evidence and append-only manual history.

Only rated.sqlite is written. Derived observations/indexes can be rebuilt from
the exact source bytes stored here, even if original addon history is pruned.
"""
from collections import defaultdict
from datetime import datetime, timezone,date
import hashlib,json,math,sqlite3,uuid
from pathlib import Path
from .archive import safe_destination
from .sync import home_lock
from .player_index import uid,read_archive
from .career_sources import extract,context,integer,player_id,BRACKETS

SCHEMA=1
READER='1.4.1'
DEFINITIONS={
 'rating':'Personal competitive rating; never MMR or leaderboard rank. REFlex after = observed before + observed change.',
 'current':'Latest timestamped known personal rating within one character/certainty, version, season, bracket and specialization. Not a live API value.',
 'peak':'Maximum unconflicted known before/after/manual rating in the same fully classified cohort. Season peak uses all archived dates; highest_recorded is the selected date-window peak. Neither guarantees official season best.',
 'games':'Distinct resolved logical match links per character/cohort; manual standalone rating observations are not games. Revisions do not add games.',
 'outcomes':'Known faction outcomes only. Shuffle session W/L is withheld because rounds and sessions differ; no outcome is inferred from rating change.',
 'missing':'Unrecorded version/season/bracket/spec stays null. Incomplete cohorts remain individually visible but are not combined into career peaks or charts.',
 'rank':'No live leaderboard provider is configured. Rank is Not Available unless a manual observation supplies a documented source. User attestation is distinguished from independent verification.',
 'revisions':'Latest revision per manual root applies; reversal removes its projection, not original evidence. Correction/reversal history remains exportable.',
 'conflicts':'Different source revisions remain available. Conflicting simultaneous event facts withhold aggregate rating/delta/outcome rather than choosing a convenient value.'}


def now():return datetime.now(timezone.utc).isoformat()
def encode(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,allow_nan=False)


def connect(home,write=False):
    p=safe_destination(Path(home)/'rated.sqlite')
    if not write and not p.exists():return None
    db=sqlite3.connect(p if write else p.as_uri()+'?mode=ro',uri=not write);db.row_factory=sqlite3.Row
    version=db.execute('pragma user_version').fetchone()[0]
    if version not in ((0,SCHEMA) if write else (SCHEMA,)):
        db.close();raise ValueError('Unsupported rated archive schema; original history retained')
    if write:
        db.execute('pragma foreign_keys=ON');db.execute('pragma busy_timeout=30000')
        db.executescript('''
        create table if not exists sources(sha256 text primary key,bytes blob not null);
        create table if not exists captures(id text primary key,sha256 text not null references sources(sha256),metadata text not null,reader text);
        create table if not exists observations(id text primary key,player_key text not null,event_key text not null,payload text not null);
        create index if not exists rated_players on observations(player_key,event_key);
        create table if not exists evidence(id text primary key,observation_id text references observations(id),capture_id text references captures(id),provenance text not null);
        create table if not exists diagnostics(id text primary key,capture_id text references captures(id),payload text not null);
        create table if not exists manual_revisions(id integer primary key,root_id text not null,previous_id integer references manual_revisions(id),action text not null check(action in ('record','reverse')),payload text not null,reason text not null,created text not null);
        create index if not exists manual_roots on manual_revisions(root_id,id);
        pragma user_version=1;''')
    else:db.execute('BEGIN')
    return db


def _index_capture(db,capture,raw):
    from .lua_reader import loads
    meta=json.loads(capture['metadata']);doc=loads(raw.decode('utf-8-sig'))
    rows,problems=extract(doc,meta.get('owner'),meta.get('realm'),meta['timezone'],meta['captured_at'])
    for r in rows:
        raw_record=r.pop('raw');r.pop('captured_at',None)
        # A repeated snapshot/capture is additional provenance, not a new rating.
        oid=uid({k:v for k,v in r.items() if k!='source_record'});db.execute('insert or ignore into observations values (?,?,?,?)',(oid,r['player_key'],r['event_key'],encode(r)))
        provenance={'source_sha256':capture['sha256'],'capture':meta,'source_record':r['source_record'],'raw_record':raw_record}
        db.execute('insert or ignore into evidence values (?,?,?,?)',(uid([oid,capture['id']]),oid,capture['id'],encode(provenance)))
    for issue in problems:db.execute('insert or ignore into diagnostics values (?,?,?)',(uid([capture['id'],issue]),capture['id'],encode(issue)))
    db.execute('update captures set reader=? where id=?',(READER,capture['id']))


def recover(home,force=False):
    """Capture every retained import snapshot; unchanged scans are idempotent."""
    home=Path(home)
    if not (home/'archive.sqlite').exists():return {'added':0,'observations':0,'diagnostics':0}
    with home_lock(home):
        from .settings import SettingsStore
        zone=SettingsStore(home/'settings.json').load()['source_timezone'];archive=read_archive(home);db=connect(home,True)
        before=db.execute('select count(*) from observations').fetchone()[0]
        try:
            with db:
                for item in archive.execute('select id,source,snapshot,sha256,started from imports where snapshot is not null order by id'):
                    owner,realm=context(item['source'])
                    if not owner:
                        pairs={(r[0],r[1]) for r in archive.execute('''select distinct o.character,o.realm from observations o left join observation_versions v on o.id=v.observation_id where o.first_import=? or o.last_import=? or v.import_id=?''',(item['id'],)*3)}
                        if len(pairs)==1:owner,realm=next(iter(pairs))
                    meta={'import_id':item['id'],'source_path':item['source'],'snapshot':item['snapshot'],'captured_at':item['started'],'owner':owner,'realm':realm,'timezone':zone}
                    cid=uid([item['id'],item['sha256'],owner,realm,zone]);existing=db.execute('select id from captures where id=?',(cid,)).fetchone()
                    if existing:continue
                    try:
                        raw=Path(item['snapshot']).read_bytes()
                        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Source snapshot hash mismatch')
                        db.execute('insert or ignore into sources values (?,?)',(item['sha256'],raw))
                        db.execute('insert into captures values (?,?,?,null)',(cid,item['sha256'],encode(meta)))
                    except (OSError,ValueError) as exc:
                        issue={'code':'snapshot_unavailable','snapshot':item['snapshot'],'detail':str(exc)}
                        db.execute('insert or ignore into diagnostics values (?,null,?)',(uid(issue),encode(issue)))
                if force:
                    db.execute('delete from evidence');db.execute('delete from observations');db.execute('update captures set reader=null')
                for capture in db.execute('select * from captures where reader is null or reader!=?',(READER,)).fetchall():
                    raw=db.execute('select bytes from sources where sha256=?',(capture['sha256'],)).fetchone()[0]
                    try:_index_capture(db,capture,raw)
                    except (ValueError,TypeError,KeyError,OverflowError,OSError) as exc:
                        issue={'code':'rating_decode_failed','detail':str(exc)}
                        db.execute('insert or ignore into diagnostics values (?,?,?)',(uid([capture['id'],issue]),capture['id'],encode(issue)))
            count=db.execute('select count(*) from observations').fetchone()[0]
            return {'added':max(0,count-before),'observations':count,'diagnostics':db.execute('select count(*) from diagnostics').fetchone()[0]}
        finally:archive.close();db.close()


def manual_history(home):
    db=connect(home)
    if db is None:return []
    try:return [dict(r)|{'data':json.loads(r['payload'])} for r in db.execute('select * from manual_revisions order by id desc')]
    finally:db.close()


def validate_manual(values):
    x=dict(values)
    for f in ('character','realm','spec','game_version','source','source_reference','notes','ranking_region','identity_context'):
        x[f]=str(x.get(f) or '').strip()
    if not x['character']:raise ValueError('Character is required')
    x['realm_certainty']=x.get('realm_certainty') or 'observed'
    if x['realm_certainty'] not in ('observed','inferred','unknown'):raise ValueError('Invalid realm certainty')
    if x['realm_certainty']!='unknown' and not x['realm']:raise ValueError('A known or inferred realm requires a realm value')
    if x['realm_certainty']!='observed' and not x['identity_context']:raise ValueError('Uncertain identities require their recording-realm context')
    if x.get('bracket') not in BRACKETS:raise ValueError('Choose a supported bracket')
    for f in ('spec','game_version','season'):
        value=str(x.get(f) or '').strip();x[f]=None if value.casefold() in ('','unknown','not available') else value
    for f in ('rating','leaderboard_position'):
        v=x.get(f)
        if v in ('',None):x[f]=None;continue
        try:n=float(v)
        except (ValueError,TypeError):raise ValueError(f+' must be an integer') from None
        if isinstance(v,bool) or not math.isfinite(n) or not n.is_integer() or n<(1 if f=='leaderboard_position' else 0):raise ValueError(f+' must be a valid nonnegative integer (rank starts at 1)')
        x[f]=int(n)
    if x['rating'] is None and x['leaderboard_position'] is None:raise ValueError('Enter a rating or a sourced leaderboard position')
    stamp=datetime.fromisoformat(str(x.get('observed_at') or '').replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('Observation date/time requires a UTC offset, e.g. 2026-10-24T12:00:00-07:00')
    x['observed_at']=stamp.astimezone(timezone.utc).isoformat()
    if not x['source']:raise ValueError('Describe the source')
    if x['leaderboard_position'] is not None and (not x['source_reference'] or x['ranking_region'] not in ('US','EU','KR','TW','CN') or not all(x[f] for f in ('spec','game_version','season'))):raise ValueError('A rank requires a documented source, region, game version, season and specialization')
    if x.get('ranking_verified_by_user',False) not in (True,False):raise ValueError('Rank attestation must be a boolean')
    x['ranking_verified_by_user']=bool(x.get('ranking_verified_by_user'))
    if x['ranking_verified_by_user'] and (x['leaderboard_position'] is None or x['realm_certainty']!='observed'):raise ValueError('Source attestation requires a rank and an observed realm identity')
    x.update(player_key=player_id(x['character'],x['realm'],x['realm_certainty'],x['identity_context']),own=bool(x.get('own',True)),rating_before=None,rating_after=None,rating_change=None,mmr_before=None,mmr_after=None,result=None,match_key=None,event_key=None)
    return x


def save_manual(home,values,previous=None,reason='Manual rating observation',approved=False):
    if approved is not True:raise PermissionError('Explicit approval is required to save a manual observation')
    x=validate_manual(values)
    with home_lock(home):
        # Backup existing persistent manual/source history before a revision.
        p=Path(home)/'rated.sqlite'
        if p.exists():
            folder=safe_destination(Path(home)/'backups'/('rated_'+uuid.uuid4().hex));folder.mkdir(parents=True)
            a=connect(home);b=sqlite3.connect(folder/'rated.sqlite')
            try:a.backup(b)
            finally:a.close();b.close()
        db=connect(home,True)
        try:
            root=uuid.uuid4().hex
            if previous is not None:
                prior=db.execute('select * from manual_revisions where id=?',(previous,)).fetchone()
                if prior is None:raise ValueError('Unknown manual revision')
                latest=db.execute('select max(id) from manual_revisions where root_id=?',(prior['root_id'],)).fetchone()[0]
                if latest!=previous:raise ValueError('Manual entry changed; review the latest revision first')
                if len(reason.strip())<8:raise ValueError('Explain the correction')
                root=prior['root_id']
            with db:
                id=db.execute('insert into manual_revisions(root_id,previous_id,action,payload,reason,created) values (?,?,?,?,?,?)',(root,previous,'record',encode(x),reason,now())).lastrowid
            return {'id':id,'root_id':root}
        finally:db.close()


def reverse_manual(home,previous,approved=False):
    if approved is not True:raise PermissionError('Explicit approval is required for reversal')
    # A reversal is a new event, never deletion of a rating observation.
    with home_lock(home):
        db=connect(home,True)
        try:
            prior=db.execute('select * from manual_revisions where id=?',(previous,)).fetchone()
            if prior is None:raise ValueError('Unknown manual revision')
            if db.execute('select max(id) from manual_revisions where root_id=?',(prior['root_id'],)).fetchone()[0]!=previous:raise ValueError('Select the latest revision before reversing')
            if prior['action']=='reverse':return {'reversed':False}
            with db:db.execute('insert into manual_revisions(root_id,previous_id,action,payload,reason,created) values (?,?,?,?,?,?)',(prior['root_id'],previous,'reverse',prior['payload'],'User reversed manual projection',now()))
            return {'reversed':True}
        finally:db.close()


def observations(home):
    db=connect(home)
    if db is None:return []
    try:
        result=[json.loads(r['payload'])|{'id':r['id'],'manual':False} for r in db.execute('select * from observations')]
        for r in db.execute('select m.* from manual_revisions m join (select root_id,max(id) id from manual_revisions group by root_id) last on last.id=m.id where m.action="record"'):
            result.append(json.loads(r['payload'])|{'id':'manual:'+str(r['id']),'manual':True,'revision_id':r['id'],'root_id':r['root_id'],'event_key':None,'rating_semantics':'User-entered observation; not independently fetched'})
        return result
    finally:db.close()


def classified(r):
    return bool(r.get('game_version') and r.get('season') is not None and r.get('bracket') and r.get('spec'))


def _event_resolution(rows,home):
    """Respect existing explicit duplicate links without modifying them."""
    db=read_archive(home)
    try:
        from .dual_archive import project
        from types import SimpleNamespace
        matches,roster=project(SimpleNamespace(db=db))
        aliases={}
        for m in matches:
            key=(m['Character'],m['Realm'],m['Match ID'])
            for oid in m.get('_observation_ids',[]):
                ob=db.execute('select character,realm,original_id from observations where id=?',(oid,)).fetchone()
                if ob:aliases[tuple(ob)]=key
        for r in rows:
            original=tuple(r.get('match_key') or ())
            if original:r['canonical_match_key']=list(aliases.get(original,original));r['logical_event']=uid([aliases.get(original,original),r['player_key']])
        return rows
    finally:db.close()


def _resolve_events(items):
    events=defaultdict(list)
    for r in items:events[r.get('logical_event') or r.get('event_key') or r['id']].append(r)
    effective=[]
    for group in events.values():
        r=group[0].copy();r['conflicting_fields']=[]
        for f in ('rating','rating_before','rating_after','rating_change','result'):
            values={x[f] for x in group if x.get(f) is not None}
            r[f]=next(iter(values)) if len(values)==1 else None
            if len(values)>1:r['conflicting_fields'].append(f)
        effective.append(r)
    return effective


def _peak(items):
    return max((v for r in items for v in (r.get('rating'),r.get('rating_before'),r.get('rating_after')) if v is not None),default=None)


def model(home,player=None,season=None,bracket=None,spec=None,start=None,end=None,include_others=False):
    rows=observations(home)
    catalogue={}
    for r in rows:
        if include_others or r.get('own'):catalogue[r['player_key']]={k:r.get(k) for k in ('player_key','character','realm','realm_certainty','identity_context','own')}
    if (Path(home)/'archive.sqlite').exists():
        db=read_archive(home)
        try:
            for name,world in db.execute('select distinct character,realm from observations'):
                pid=player_id(name,world,'observed');catalogue.setdefault(pid,{'player_key':pid,'character':name,'realm':world,'realm_certainty':'observed','identity_context':'','own':True})
        finally:db.close()
        from .player_index import read_identities
        from .identity import character_key
        identities=read_identities(home)
        for entry in identities.people.get(identities.owner_person,[]):
            name,_,world=entry.partition('-')
            if not world and any(character_key(c['character'])[0]==character_key(name)[0] for c in catalogue.values()):continue
            certainty='observed' if world else 'unknown';pid=player_id(name,world,certainty)
            catalogue.setdefault(pid,{'player_key':pid,'character':name,'realm':world,'realm_certainty':certainty,'identity_context':'','own':True})
    catalogue=dict(sorted(catalogue.items(),key=lambda item:(item[1]['character'].casefold(),item[1]['realm'],item[1]['realm_certainty'])))
    if player is None and catalogue:player=next(iter(sorted(catalogue,key=lambda k:(not catalogue[k]['own'],catalogue[k]['character'],catalogue[k]['realm']))))
    chosen=[r for r in rows if r['player_key']==player]
    if chosen and (Path(home)/'archive.sqlite').exists():chosen=_event_resolution([r.copy() for r in chosen],home)
    choices={f:sorted({str(r[f]) for r in chosen if r.get(f) is not None}) for f in ('season','bracket','spec')}
    for day in (start,end):
        if day:date.fromisoformat(day)
    if start and end and start>end:raise ValueError('Start date must not follow end date')
    selected=[r.copy() for r in chosen if (not season or str(r.get('season'))==season) and (not bracket or r.get('bracket')==bracket) and (not spec or r.get('spec')==spec) and (not start or r.get('observed_at') and r['observed_at'][:10]>=start) and (not end or r.get('observed_at') and r['observed_at'][:10]<=end)]
    full_cohorts=defaultdict(list)
    for r in chosen:
        if classified(r):full_cohorts[(r['game_version'],str(r['season']),r['bracket'],r['spec'])].append(r)
    grouped=defaultdict(list);unclassified=[]
    for r in selected:
        if classified(r):grouped[(r['game_version'],str(r['season']),r['bracket'],r['spec'])].append(r)
        else:unclassified.append(r)
    summaries=[];series=[]
    for key,items in sorted(grouped.items()):
        # One logical event may have multiple immutable revisions/addon views.
        effective=_resolve_events(items)
        dated=sorted((r for r in effective if r.get('observed_at') and r.get('rating') is not None),key=lambda r:(r['observed_at'],r['id']))
        highest=_peak(effective);season_peak=_peak(_resolve_events(full_cohorts[key]))
        # Simultaneous disagreeing observations are not a reliable latest value.
        latest=[r['rating'] for r in dated if r['observed_at']==dated[-1]['observed_at']] if dated else []
        current=latest[0] if latest and len(set(latest))==1 else None
        if dated and any(r.get('observed_at') and r['observed_at']>=dated[-1]['observed_at'] and 'rating' in r['conflicting_fields'] for r in effective):current=None
        games=[r for r in effective if r.get('match_key')]
        ranks=[r for r in items if r.get('leaderboard_position') is not None];ranks.sort(key=lambda r:r.get('observed_at') or '')
        ranking=ranks[-1] if ranks else None
        summary={'game_version':key[0],'season':key[1],'bracket':key[2],'spec':key[3],'current':current,'highest_recorded':highest,'season_peak':season_peak,
            'first':(dated[0]['rating_before'] if dated[0].get('rating_before') is not None else dated[0]['rating']) if dated else None,'latest':current,'first_observed':dated[0]['observed_at'] if dated else None,'latest_observed':dated[-1]['observed_at'] if dated else None,
            'games':len(games),'wins':sum(r.get('result')=='W' for r in games),'losses':sum(r.get('result')=='L' for r in games),'unknown_results':sum(r.get('result') not in ('W','L') for r in games),
            'gains':sum(max(0,r['rating_change']) for r in games if r.get('rating_change') is not None),'loss_points':sum(min(0,r['rating_change']) for r in games if r.get('rating_change') is not None),
            'delta_samples':sum(r.get('rating_change') is not None for r in games),'observations':len(items),'conflicted_events':sum(bool(r['conflicting_fields']) for r in effective),
            'leaderboard':ranking['leaderboard_position'] if ranking else None,'rank_verification':'User-attested source; not independently fetched' if ranking and ranking.get('ranking_verified_by_user') else 'Unverified manual source' if ranking else 'Not Available',
            'rank_source':ranking.get('source_reference') if ranking else None,'ranking_region':ranking.get('ranking_region') if ranking else None,'rank_observed_at':ranking.get('observed_at') if ranking else None}
        summaries.append(summary);series.append({'label':' / '.join(key),'key':key,'points':[{'time':r['observed_at'],'rating':r['rating'],'id':r['id'],'source':r['source']} for r in dated]})
    selected.sort(key=lambda r:(r.get('observed_at') or '',r['id']),reverse=True)
    return {'player':player,'characters':list(catalogue.values()),'choices':choices,'summaries':summaries,'series':series,'observations':selected,'unclassified':len(unclassified),
        'definitions':DEFINITIONS,'leaderboard_provider':'Not Available — no leaderboard provider configured','manual_history':manual_history(home)}
