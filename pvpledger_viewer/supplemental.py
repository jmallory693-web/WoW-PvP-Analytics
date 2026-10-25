"""Approved, reversible Excel evidence in a separate versioned SQLite store.

No SQL in this module writes to archive.sqlite or identity/configuration files.
"""
from datetime import datetime,timezone
import hashlib,json,sqlite3,uuid,shutil
from pathlib import Path
from .archive import safe_destination
from .identity import character_key
from .metrics import match_key
from .sync import home_lock

SCHEMA=1
SOURCE='Excel historical import'


def now():return datetime.now(timezone.utc).isoformat()


def read_db(home):
    path=Path(home)/'supplemental.sqlite'
    if not path.exists():return None
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    if db.execute('pragma user_version').fetchone()[0]!=SCHEMA:db.close();raise ValueError('Unsupported supplemental schema; original data retained')
    db.execute('BEGIN');return db


def generation(home):
    db=read_db(home)
    if db is None:return 0
    try:return db.execute('select coalesce(max(id),0) from decisions').fetchone()[0]
    finally:db.close()


def active(db):
    return [dict(r) for r in db.execute('''select d.* from decisions d join
        (select row_id,max(id) id from decisions group by row_id) latest on latest.id=d.id
        where d.action in ('link','historical') order by d.id''')]


def history(home):
    db=read_db(home)
    if db is None:return []
    try:return [dict(r) for r in db.execute('select * from decisions order by id desc')]
    finally:db.close()


def _backup(home):
    root=Path(home);folder=safe_destination(root/'backups'/('excel_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]));folder.mkdir(parents=True)
    for name in ('archive.sqlite','supplemental.sqlite'):
        if (root/name).exists():
            a=sqlite3.connect((root/name).resolve().as_uri()+'?mode=ro',uri=True);b=sqlite3.connect(folder/name)
            try:a.backup(b);assert b.execute('pragma integrity_check').fetchone()[0]=='ok'
            finally:a.close();b.close()
    for name in ('people.json','settings.json'):
        if (root/name).exists():shutil.copy2(root/name,folder/name)
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')


def _write_db(home):
    db=sqlite3.connect(safe_destination(Path(home)/'supplemental.sqlite'));db.row_factory=sqlite3.Row
    if db.execute('pragma user_version').fetchone()[0] not in (0,SCHEMA):db.close();raise ValueError('Unsupported supplemental schema')
    db.execute('pragma foreign_keys=ON');db.executescript('''
    create table if not exists workbooks(sha256 text primary key,path text not null,size integer not null,
      original_bytes blob not null,document text not null,first_import text not null);
    create table if not exists batches(id text primary key,workbook_sha text references workbooks(sha256),
      created text not null,archive_generation text not null,decision_count integer not null);
    create table if not exists decisions(id integer primary key,batch_id text references batches(id),
      workbook_sha text not null references workbooks(sha256),row_id text not null,sheet text not null,row_number integer not null,
      action text not null check(action in ('link','historical','reject','reverse')),target text,anchor integer,
      approved_fields text not null,include_roster integer not null,realm text,classification text not null,
      field_comparisons text not null,row_fingerprint text not null,reason text not null,created text not null,reverses integer);
    create index if not exists decision_rows on decisions(row_id,id);
    pragma user_version=1;''');return db


def commit(home,report,selections,*,approved=False):
    if approved is not True:raise PermissionError('Explicit approval is required before committing supplemental imports')
    if not selections:raise ValueError('Stage at least one reviewed decision')
    from .reconcile import reconcile,MISSING,EXACT
    from .excel_reader import digest
    home=safe_destination(home)
    with home_lock(home):
        raw=Path(report['workbook']['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=report['workbook']['sha256']:raise ValueError('Workbook changed; reconcile the current file again')
        source_rows={r['id']:r for r in report['workbook']['matches']}
        previous=read_db(home)
        if previous:
            identical=True
            for choice in selections:
                row=source_rows.get(choice['row_id']);old=previous.execute('select * from decisions where row_id=? order by id desc limit 1',(choice['row_id'],)).fetchone()
                expected={'action':choice['action'],'target':json.dumps(choice.get('target')) if choice['action']=='link' else None,
                    'approved_fields':json.dumps(sorted(set(choice.get('fields',[])))),'include_roster':int(bool(choice.get('include_roster'))),
                    'realm':choice.get('realm') or (row['normalized'].get('Realm') if row else None),'reason':str(choice.get('reason','')).strip()}
                if not old or any(old[k]!=v for k,v in expected.items()):identical=False
            previous.close()
            if identical:return {'decisions_added':0,'workbooks_added':0,'historical_events_added':0,'repeated':True}
        verified=reconcile(home,report['workbook']['path'],report['timezone'])
        current=verified['archive_generation']
        if current!=report['archive_generation']:raise ValueError('Archive changed since reconciliation; run the audit again before approving')
        if digest(verified['workbook'])!=digest(report['workbook']):raise ValueError('Workbook evidence changed or was edited; run reconciliation again')
        report=verified;matches=[entry['match'] for entry in report['archive_catalogue']]
        catalogue={tuple(match_key(m)):m for m in matches};rows={r['id']:r for r in report['workbook']['matches']};reviews={r['row_id']:r for r in report['results']}
        prepared=[];fingerprints={};prior=read_db(home)
        if prior:
            for old in active(prior):
                if old['action']=='historical':fingerprints[old['row_fingerprint']]=old['row_id']
            prior.close()
        seen=set()
        for choice in selections:
            row_id=choice['row_id']
            if row_id in seen:raise ValueError('One decision per workbook row in a commit')
            seen.add(row_id)
            if row_id not in rows:raise ValueError('Unknown workbook row')
            row=rows[row_id];review=reviews[row_id];action=choice['action'];fields=sorted(set(choice.get('fields',[])));target=choice.get('target');reason=str(choice.get('reason','')).strip();realm=choice.get('realm') or row['normalized'].get('Realm')
            if action not in ('link','historical','reject'):raise ValueError('Choose link, historical event, or reject')
            if any(f not in row['fields'] for f in fields):raise ValueError('Unknown approval field')
            anchor=None;comparisons=[]
            if action=='link':
                key=tuple(target or ())
                if key not in catalogue:raise ValueError('Choose an existing archived match')
                m=catalogue[key]
                if character_key(row['owner'],realm)!=character_key(m['Character'],m.get('Realm')):raise ValueError('A different character perspective cannot receive this owner’s statistics')
                suggested=next((c for c in review['candidates'] if tuple(c['key'])==key),None)
                if not suggested and len(reason)<12:raise ValueError('Explain a manual link outside the proposed candidates (at least 12 characters)')
                comparisons=suggested['fields'] if suggested else []
                anchor=next(iter(m.get('_observation_ids',[])),None)
            if action=='historical':
                if not row['owner'] or not realm:raise ValueError('An exact owner character and realm must be supplied for a historical event')
                other=fingerprints.get(row['fingerprint'])
                if other and other!=row_id:raise ValueError('This spreadsheet event is already approved from another row; link or reverse it instead')
                if review['classification']==EXACT:raise ValueError('An exact identified counterpart exists; link it instead of creating a duplicate historical event')
                if review['classification']!=MISSING and len(reason)<12:raise ValueError('Explain why the supported counterpart is a different event before creating a historical match')
                fingerprints[row['fingerprint']]=row_id
            prepared.append({'workbook_sha':report['workbook']['sha256'],'row_id':row_id,'sheet':row['sheet'],'row_number':row['row'],
                'action':action,'target':json.dumps(target) if action=='link' else None,'anchor':anchor,
                'approved_fields':json.dumps(fields),'include_roster':int(bool(choice.get('include_roster'))),
                'realm':realm,'classification':review['classification'],'field_comparisons':json.dumps(comparisons,ensure_ascii=False),
                'row_fingerprint':row['fingerprint'],'reason':reason,'created':now(),'reverses':None})
        _backup(home);db=_write_db(home)
        try:
            fresh=[]
            for p in prepared:
                old=db.execute('select * from decisions where row_id=? order by id desc limit 1',(p['row_id'],)).fetchone()
                semantic=('action','target','approved_fields','include_roster','realm','reason')
                if old and all(old[f]==p[f] for f in semantic):continue
                fresh.append(p)
            if not fresh:return {'decisions_added':0,'workbooks_added':0,'historical_events_added':0,'repeated':True}
            with db:
                added=db.execute('insert or ignore into workbooks values (?,?,?,?,?,?)',(report['workbook']['sha256'],report['workbook']['path'],len(raw),raw,json.dumps(report['workbook'],ensure_ascii=False),now())).rowcount
                batch=uuid.uuid4().hex;db.execute('insert into batches values (?,?,?,?,?)',(batch,report['workbook']['sha256'],now(),current,len(fresh)))
                for p in fresh:
                    p={'batch_id':batch}|p;columns=','.join(p)
                    db.execute('insert into decisions ('+columns+') values ('+','.join('?' for _ in p)+')',list(p.values()))
            return {'decisions_added':len(fresh),'workbooks_added':added,'historical_events_added':sum(p['action']=='historical' for p in fresh),'repeated':False}
        finally:db.close()


def reverse(home,row_id,*,approved=False,reason='User reversed the supplemental decision'):
    if approved is not True:raise PermissionError('Explicit approval is required to reverse an imported decision')
    with home_lock(home):
        if not (Path(home)/'supplemental.sqlite').exists():raise ValueError('No supplemental history exists')
        _backup(home);db=_write_db(home)
        try:
            old=db.execute('select * from decisions where row_id=? order by id desc limit 1',(row_id,)).fetchone()
            if not old:raise ValueError('Unknown supplemental row')
            if old['action']=='reverse':return {'reversed':False,'already_reversed':True}
            p=dict(old);p.pop('id');p.update(action='reverse',reason=reason,created=now(),reverses=old['id'])
            with db:db.execute('insert into decisions ('+','.join(p)+') values ('+','.join('?' for _ in p)+')',list(p.values()))
            return {'reversed':True}
        finally:db.close()


def approved_rows(home):
    db=read_db(home)
    if db is None:return []
    try:
        documents={r['sha256']:json.loads(r['document']) for r in db.execute('select sha256,document from workbooks')};out=[]
        for decision in active(db):
            row=next(r for r in documents[decision['workbook_sha']]['matches'] if r['id']==decision['row_id'])
            out.append((decision,row))
        return out
    finally:db.close()


def _selected(decision,row):
    fields=json.loads(decision['approved_fields']);values={}
    for label in fields:
        target=row['field_map'].get(label)
        if target and not target.startswith('Objective: '):values[target]=row['normalized'].get(target)
    objective_labels=[label for label in fields if row['field_map'].get(label,'').startswith('Objective: ')]
    objectives='; '.join(row['field_map'][label].removeprefix('Objective: ')+'='+str(row['normalized'][row['field_map'][label]]) for label in objective_labels if row['normalized'].get(row['field_map'][label]) is not None)
    if objectives:values['My objectives']=objectives
    return values


def _roster(decision,row,key,match):
    raw_rows=row['roster'] if decision['include_roster'] else []
    own=next((r['normalized'] for r in raw_rows if character_key(r['normalized']['Player'],r['normalized'].get('Realm'))==character_key(key[0],key[1])),None)
    output=[]
    for original in raw_rows:
        r=original['normalized'];self_=character_key(r['Player'],r.get('Realm'))==character_key(key[0],key[1])
        team='Mine' if own and r.get('Faction') and r.get('Faction')==own.get('Faction') else 'Enemy' if own and r.get('Faction') else None
        output.append({k:r.get(k) for k in ('Player','Realm','Faction','KB','HK','Deaths','Damage','Healing','Notes')}|
            {'Owner character':key[0],'Owner realm':key[1],'Match ID':key[2],'Team':team,'Is me':'Yes' if self_ else 'No',
             'Objectives':'; '.join(k.removeprefix('Objective: ')+'='+str(v) for k,v in r.items() if k.startswith('Objective: ') and v is not None) or None,
             '_scoreboard_incomplete':True,'_excel_historical':True,'_excel_source':{'sha256':decision['workbook_sha'],'sheet':original['sheet'],'row':original['row']}})
    if not any(r['Is me']=='Yes' for r in output):
        output.append({'Player':key[0],'Realm':key[1],'Owner character':key[0],'Owner realm':key[1],'Match ID':key[2],
            'Team':'Mine','Is me':'Yes','Damage':match.get('Damage'),'Healing':match.get('Healing'),'KB':match.get('KB'),'HK':match.get('HK'),
            'Deaths':match.get('Deaths'),'Objectives':match.get('My objectives'),'_scoreboard_incomplete':True,'_excel_historical':True})
    return output


def project(home,matches,rosters):
    """Read-time overlay. Addon values are never replaced, even for conflicts."""
    approvals=approved_rows(home)
    if not approvals:return matches,rosters
    matches=[m.copy() for m in matches];rosters=[r.copy() for r in rosters]
    for d,row in approvals:
        selected=_selected(d,row);ref={'workbook_sha256':d['workbook_sha'],'sheet':d['sheet'],'row':d['row_number'],
            'decision_id':d['id'],'classification_before_manual_review':d['classification'],'approval':'Explicit user approval',
            'fields':json.loads(d['approved_fields']),'original_values':{k:row['fields'][k] for k in json.loads(d['approved_fields'])},
            'field_comparisons':json.loads(d['field_comparisons']),'reason':d['reason']}
        if d['action']=='historical':
            key=(row['owner'],d['realm'],'Excel-'+row['id'])
            m={'Character':key[0],'Realm':key[1],'Match ID':key[2],'Source':SOURCE,'Date':None,'Time':None,'Type':row['normalized'].get('Type'),
               '_partial':True,'_scoreboard_incomplete':True,'Minutes played':None,'_observation_ids':[],
               '_excel_historical':True,'_excel_id':row['id'],'_excel_supplements':[ref],'_provenance':{f:[SOURCE] for f in selected},'_conflicts':[]}|selected
            from .reconcile import timestamps
            stamps=timestamps(m,row.get('timezone','America/Los_Angeles'))
            m['_timestamp_utc']=stamps[0] if len(stamps)==1 else None
            matches.append(m);rosters.extend(_roster(d,row,key,m));continue
        target=tuple(json.loads(d['target']));m=next((m for m in matches if match_key(m)==target or d['anchor'] is not None and d['anchor'] in m.get('_observation_ids',[])),None)
        if not m:continue # Decision and source remain visible in history/export; never relink by proximity.
        m.setdefault('_excel_supplements',[]);m['_excel_supplements']=[*m['_excel_supplements'],ref]
        m['Display source']=str(m.get('Source') or '')+' + Excel supplement'
        comparisons={f.get('normalized_field'):f for f in json.loads(d['field_comparisons'])}
        for f,value in selected.items():
            # Unknown manual semantics and values found in retained addon evidence
            # remain separate supplemental evidence rather than analytic replacements.
            if m.get(f) is None and value is not None and comparisons.get(f,{}).get('status')=='Missing from normalized archive':
                m[f]=value;m['_provenance']={**m.get('_provenance',{}),f:[SOURCE]};m['_scoreboard_incomplete']=True
        for label in json.loads(d['approved_fields']):
            field=row['field_map'].get(label,'')
            if field.startswith('Objective: ') and comparisons.get(field,{}).get('status')=='Missing from normalized archive':
                value=row['normalized'].get(field);name=field.removeprefix('Objective: ')
                if value is not None:
                    existing=str(m.get('My objectives') or '')
                    if not any(part.strip().partition('=')[0].casefold()==name.casefold() for part in existing.split(';')):
                        m['My objectives']=(existing+'; ' if existing else '')+name+'='+str(value)
                        m['_provenance']={**m.get('_provenance',{}),'My objectives':list(dict.fromkeys(m.get('_provenance',{}).get('My objectives',[])+[SOURCE]))}
        existing={(r['Player'],r.get('Realm')):r for r in rosters if (r['Owner character'],r['Owner realm'],r['Match ID'])==match_key(m)}
        for r in _roster(d,row,match_key(m),m):
            person=(r['Player'],r.get('Realm'))
            if person not in existing:rosters.append(r);existing[person]=r
            else:
                destination=existing[person]
                for f,value in r.items():
                    if not f.startswith('_') and destination.get(f) is None and value is not None:
                        destination[f]=value;destination['_provenance']={**destination.get('_provenance',{}),f:[SOURCE]}
    return matches,rosters


def sightings(home,matches,event_ids):
    """Only explicitly approved Excel player facts, never relabelled addon stats."""
    from .player_index import uid
    from .metric_registry import values
    facts=[]
    for d,row in approved_rows(home):
        key=(row['owner'],d['realm'],'Excel-'+row['id']) if d['action']=='historical' else tuple(json.loads(d['target']))
        match=next((m for m in matches if match_key(m)==key or d['anchor'] is not None and d['anchor'] in m.get('_observation_ids',[])),None)
        if match is None:continue
        key=match_key(match);selected=_selected(d,row);pseudo={'Character':key[0],'Realm':key[1],**selected}
        for original in _roster(d,row,key,pseudo):
            own=original['Is me']=='Yes';world=original.get('Realm') or ''
            certainty='inferred' if own and d['action']=='historical' else 'observed' if world else 'unknown'
            player=uid([*character_key(original['Player'],world),certainty,key[1] if certainty!='observed' else ''])
            event=event_ids[key];sid=uid(['excel-decision',d['id'],player,event])
            record={f:match.get(f) for f in ('Date','Time','Type','Map','Map ID','Epoch','Duration (s)')};record.update(original)
            record.update(player_key=player,event_id=event,realm_certainty=certainty,source=SOURCE,
                source_hash=d['workbook_sha'],import_id=d['id'],perspective=list(key),canonical_key=list(key),sighting_id=sid,
                relationship='self' if own else 'ally' if original.get('Team')=='Mine' else 'opponent' if original.get('Team')=='Enemy' else 'unknown',
                _cohort_verified_complete=False,_scoreboard_incomplete=True,
                quality='Excel; manually approved; rounded inputs; incomplete cohort',
                provenance={'workbook_sha256':d['workbook_sha'],'sheet':d['sheet'],'row':d['row_number'],
                            'decision_id':d['id'],'approved_fields':json.loads(d['approved_fields']),'tolerances':row['tolerances']})
            record['Minutes played']=None
            if own:record.update({'Honor':selected.get('Honor (scoreboard)'),'Rating change':selected.get('Rating change')})
            outcome=match.get('Result');record['Result']=outcome if own or original.get('Team')=='Mine' else {'W':'L','L':'W'}.get(outcome) if original.get('Team')=='Enemy' else None
            record['metrics']=values(record);facts.append(record)
    return facts
