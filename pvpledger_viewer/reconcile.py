"""Read-only, evidence-based reconciliation; suggestions are never imports."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from .excel_reader import read_workbook,digest,number,clock
from .player_index import read_archive,read_identities
from .identity import character_key,normalized
from .metrics import match_key,numeric

VERSION='1.0'
EXACT='EXACT MATCH';PROBABLE='PROBABLE MATCH';AMBIGUOUS='AMBIGUOUS MATCH';MISSING='NOT FOUND'


def archive_evidence(home):
    """Include all retained revisions and decodable snapshots, without index writes."""
    from .dual_archive import project
    from .lua_reader import loads
    from .normalize import normalize
    from .reflex_reader import parse_reflex
    db=read_archive(home)
    try:
        settings=Path(home)/'settings.json'
        source_zone=json.loads(settings.read_text(encoding='utf-8-sig')).get('source_timezone','America/Los_Angeles') if settings.exists() else 'America/Los_Angeles'
        matches,rosters=project(SimpleNamespace(db=db,_exclude_supplemental=True))
        from .supplemental import project as supplemental_project,generation as supplemental_generation
        excel_matches,excel_rosters=supplemental_project(home,[],[])
        matches+=excel_matches;rosters+=excel_rosters;by_key={match_key(m):m for m in matches}
        obs={r['id']:dict(r) for r in db.execute('SELECT * FROM observations')};targets={};evidence=defaultdict(list)
        for m in matches:
            for oid in m.get('_observation_ids',[]):
                r=obs[oid]
                for original in (r['original_id'],r['match_id']):targets[(r['character'],r['realm'],original)]=match_key(m)
        for r in db.execute('SELECT * FROM snapshot_aliases'):
            key=(r['character'],r['realm'],r['match_id'])
            if key in targets:targets[(r['character'],r['realm'],r['snapshot_id'])]=targets[key]
        for version in db.execute('SELECT * FROM observation_versions'):
            r=obs.get(version['observation_id'])
            if not r:continue
            target=targets.get((r['character'],r['realm'],r['original_id']))
            if target:evidence[target].append({'match':json.loads(version['payload']),'roster':json.loads(version['roster']),
                 'provenance':{'observation_id':r['id'],'version_digest':version['digest'],'import_id':version['import_id'],'addon':r['addon']}})
        problems=[];seen=set()
        for imported in db.execute('SELECT id,source,snapshot,sha256 FROM imports WHERE snapshot IS NOT NULL ORDER BY id'):
            if imported['sha256'] in seen:continue
            seen.add(imported['sha256'])
            try:
                raw=Path(imported['snapshot']).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=imported['sha256']:raise ValueError('Snapshot hash mismatch')
                doc=loads(raw.decode('utf-8-sig'));source=Path(imported['source']);owner=realm=None
                if source.parent.name=='SavedVariables' and source.parent.parent.parent.name!='Account':owner,realm=source.parent.parent.name,source.parent.parent.parent.name
                if not owner or not realm:
                    owners={(r['character'],r['realm']) for r in obs.values() if imported['id'] in (r['first_import'],r['last_import'])}
                    if len(owners)==1:owner,realm=next(iter(owners))
                if 'REFlexDatabase' in doc:ms,rs,aliases,issues=parse_reflex(doc,owner,realm,source_zone)
                elif 'PvPLedgerDB' in doc:ms,rs,aliases,issues=normalize(doc,owner,realm)
                else:continue
                for source_key,m in ms.items():
                    target=targets.get(match_key(m))
                    if target:evidence[target].append({'match':m,'roster':rs.get(source_key,[]),
                        'provenance':{'snapshot_sha256':imported['sha256'],'import_id':imported['id'],'source':imported['source']}})
            except (OSError,ValueError,TypeError,KeyError) as exc:problems.append({'snapshot':imported['snapshot'],'problem':str(exc)})
        for key,m in by_key.items():
            evidence[key].insert(0,{'match':m,'roster':[r for r in rosters if (r['Owner character'],r['Owner realm'],r['Match ID'])==key],
                                  'provenance':{'kind':'current canonical projection','observation_ids':m.get('_observation_ids',[])}})
        for variants in evidence.values():
            for version in variants:version['match']['_source_timezone']=source_zone
        generation=digest([matches,rosters,[tuple(r) for r in db.execute('SELECT observation_id,digest FROM observation_versions')],
                           [tuple(r) for r in db.execute('SELECT * FROM match_links')],supplemental_generation(home)])
        return matches,evidence,generation,problems
    finally:db.close()


def timestamps(m,zone):
    if m.get('_timestamp_utc') is not None:return [m['_timestamp_utc']]
    if m.get('Epoch'):return [m['Epoch']]
    if not m.get('Date') or not m.get('Time'):return []
    try:
        stamp=datetime.fromisoformat(m['Date']+'T'+m['Time'])
        if stamp.tzinfo:return [stamp.timestamp()]
        tz=ZoneInfo(zone);values=[]
        for fold in (0,1):
            candidate=stamp.replace(tzinfo=tz,fold=fold)
            if datetime.fromtimestamp(candidate.timestamp(),tz).replace(tzinfo=None)==stamp:values.append(candidate.timestamp())
        return sorted(set(values))
    except (ValueError,TypeError):return []


def same(value,other,tolerance=0):
    if value is None or other is None:return False
    if numeric(value) and numeric(other):return abs(value-other)<=tolerance+1e-7
    return normalized(str(value))==normalized(str(other))


def candidate(row,m,versions,zone):
    x=row['normalized'];best=None
    for version in versions:
        y=version['match'];xt,yt=timestamps(x,zone),timestamps(y,y.get('_source_timezone',zone))
        delta=min((abs(a-b) for a in xt for b in yt),default=None)
        date_hint=y.get('Date')
        if not date_hint:
            try:date_hint=datetime.strptime(str(y.get('Match ID',''))[:8],'%Y%m%d').date().isoformat()
            except ValueError:pass
        date_agrees=x.get('Date')==date_hint and bool(x.get('Date'))
        if not date_agrees and (delta is None or delta>90):continue
        if delta is not None and delta>90:continue
        anchors=[];agreements=[];conflicts=[]
        for f in ('Damage','Healing','KB','HK','Deaths','Honor (scoreboard)','Rating change','Duration (s)'):
            if f=='Duration (s)' and 'Solo Shuffle' in (x.get('Type'),y.get('Type')):continue
            a,b=x.get(f),y.get(f)
            if a is None or b is None:continue
            if same(a,b,row['tolerances'].get(f,1 if f=='Duration (s)' else 0)):
                agreements.append(f)
                if f in ('Damage','Healing','Rating change','Duration (s)') and a>0:anchors.append(f)
            else:conflicts.append(f)
        roster_hits=set()
        for r in row['roster']:
            p=r['normalized']
            if not p.get('Realm'):continue
            for q in version['roster']:
                if character_key(p['Player'],p['Realm'])==character_key(q['Player'],q.get('Realm')) and any(
                    same(p.get(f),q.get(f),r['tolerances'].get(f,0)) and (p.get(f) or 0)>0 for f in ('Damage','Healing','KB')):
                    roster_hits.add(character_key(p['Player'],p['Realm']))
        if len(roster_hits)>=2:anchors.append('Distinctive roster statistics')
        map_agrees=same(x.get('Map'),y.get('Map'))
        # Date/result alone cannot qualify. Rounded combat stats plus a known
        # timestamp, or several independent statistics, are required.
        qualified=len(anchors)>=2 or bool(delta is not None and delta<=60 and anchors and (map_agrees or len(agreements)>=3))
        if not qualified:continue
        exact=bool(delta is not None and delta<=60 and len(anchors)>=2 and len(xt)==len(yt)==1)
        score=(int(exact),len(anchors),len(agreements),int(map_agrees),-(delta or 0))
        model={'key':list(match_key(m)),'source':m.get('Source'),'match':m,'evidence':version['provenance'],
               'time_difference_seconds':delta,'date_agrees':date_agrees,'map_agrees':map_agrees,
               'anchors':anchors,'agreements':agreements,'statistic_conflicts':conflicts,'roster_matches':len(roster_hits),'exact_supported':exact}
        if best is None or score>best[0]:best=score,model
    return best[1] if best else None


def compare_fields(row,m,versions):
    output=[];seen=set()
    for label,cell in row['fields'].items():
        f=row['field_map'].get(label);a=row['normalized'].get(f) if f else cell['value'];b=observed_value(m,f) if f else None
        if f=='Time':b=clock(b)
        if f:seen.add(f)
        raw=[{'value':observed_value(v['match'],f),'provenance':v['provenance']} for v in versions if f and observed_value(v['match'],f) is not None]
        note='';status=''
        xt,yt=timestamps(row['normalized'],row.get('timezone','America/Los_Angeles')),timestamps(m,m.get('_source_timezone','America/Los_Angeles'))
        same_instant=bool(xt and yt and min(abs(u-v) for u in xt for v in yt)<=60)
        if cell['formula'] and cell['value'] is None:status='Not directly comparable';note='Formula cache unavailable; no evaluation was attempted'
        elif f in ('Date','Time') and a is not None and b is not None and same_instant:status='Identical';note='Same instant within recorded minute precision; original timezone representations retained'
        elif not f:status='Spreadsheet-only data';note='No verified equivalent field; original units/formula retained'
        elif f=='Duration (s)' and 'Solo Shuffle' in (row['normalized'].get('Type'),m.get('Type')):status='Not directly comparable';note='Round versus complete-session duration semantics are unverified'
        elif f=='Map' and isinstance(a,str) and len(a)<=4 and a.isupper() and b and not same(a,b):status='Not directly comparable';note='Unverified arena abbreviation retained without guessing'
        elif a is None:status='Missing from Excel' if b is not None else 'Not directly comparable'
        elif b is None:status='Present in raw addon data but not normalized' if raw else 'Missing from normalized archive'
        elif same(a,b,row['tolerances'].get(f,1 if f=='Duration (s)' else 0)):
            status='Identical';note='Compatible within workbook rounding precision' if numeric(a) and a!=b else ''
        else:status='Conflicting'
        output.append({'field':label,'normalized_field':f,'sheet':row['sheet'],'cell':cell['cell'],'excel_original':cell['original'],
                       'excel_value':cell['value'],'excel_normalized':a,'archive_value':b,'status':status,'note':note,
                       'original_units':'millions' if label.endswith(' (M)') else cell['number_format'],
                       'tolerance':row['tolerances'].get(f,0),'retained_addon_evidence':raw,
                       'archive_provenance':m.get('_provenance',{}).get(f,[])})
    for f,b in m.items():
        if not f.startswith('_') and f not in seen and b is not None:
            output.append({'field':f,'normalized_field':f,'excel_value':None,'archive_value':b,'status':'Missing from Excel','archive_provenance':m.get('_provenance',{}).get(f,[])})
    return output


def observed_value(m,field):
    if not field:return None
    if field.startswith('Objective: '):
        label=field.removeprefix('Objective: ')
        for entry in str(m.get('My objectives') or m.get('Objectives') or '').split(';'):
            key,separator,value=entry.strip().partition('=')
            if separator and normalized(key)==normalized(label):
                try:return int(value.strip())
                except ValueError:return None
        return None
    return m.get(field)


def reconcile(home,path,zone='America/Los_Angeles',document=None):
    ZoneInfo(zone);document=document or read_workbook(path)
    matches,evidence,generation,problems=archive_evidence(home);owners=defaultdict(set)
    for m in matches:owners[normalized(m['Character'])].add(m.get('Realm') or '')
    results=[];possible=set()
    for row in document['matches']:
        row['timezone']=zone
        owner=row['normalized'].get('Character');worlds=owners[normalized(owner or '')]
        row['normalized']['Realm']=next(iter(worlds)) if len(worlds)==1 else None
        row['realm_certainty']='inferred from unique archived owner' if len(worlds)==1 else 'unknown'
        candidates=[]
        for m in matches:
            if normalized(m['Character'])!=normalized(owner or ''):continue
            if row['normalized']['Realm'] and normalized(m.get('Realm') or '')!=normalized(row['normalized']['Realm']):continue
            item=candidate(row,m,evidence[match_key(m)],zone)
            if item:candidates.append(item)
        candidates.sort(key=lambda c:(not c['exact_supported'],-len(c['anchors']),c['time_difference_seconds'] or 0,str(c['key'])))
        classification=MISSING if not candidates else AMBIGUOUS if len(candidates)>1 or row['duplicate_rows'] else EXACT if candidates[0]['exact_supported'] else PROBABLE
        for c in candidates:
            possible.add(tuple(c['key']));c['fields']=compare_fields(row,c['match'],evidence[tuple(c['key'])])
        chosen=candidates[0] if len(candidates)==1 else None
        results.append({'row_id':row['id'],'sheet':row['sheet'],'row':row['row'],'game':row['game'],'character':owner,
                        'classification':classification,'candidates':candidates,'duplicate_rows':row['duplicate_rows'],
                        'field_conflict':bool(chosen and any(f['status']=='Conflicting' for f in chosen['fields'])),
                        'spreadsheet_only_fields':[f['field'] for f in chosen['fields'] if f['status'] in ('Spreadsheet-only data','Missing from normalized archive')] if chosen else []})
    counts=Counter(r['classification'] for r in results)
    counts.update({'MATCH ROWS':len(results),'ROSTER ROWS':len(document['rosters']),'SHEETS':len(document['sheets']),
                   'NONEMPTY WORKBOOK ROWS':document['row_count'],'FIELD CONFLICT':sum(r['field_conflict'] for r in results),
                   'SPREADSHEET-ONLY DATA':sum(bool(r['spreadsheet_only_fields']) for r in results),
                   'ARCHIVE ONLY':sum(match_key(m) not in possible for m in matches)})
    return {'version':VERSION,'created':datetime.now(timezone.utc).isoformat(),'workbook':document,'archive_generation':generation,
            'timezone':zone,'timezone_note':'Workbook wall times use the selected recording timezone; missing times are not invented. DST ambiguity prevents exact confirmation.',
            'counts':{k:counts[k] for k in (EXACT,PROBABLE,AMBIGUOUS,MISSING,'MATCH ROWS','ROSTER ROWS','SHEETS','NONEMPTY WORKBOOK ROWS','FIELD CONFLICT','SPREADSHEET-ONLY DATA','ARCHIVE ONLY')},
            'results':results,'archive_only':[m for m in matches if match_key(m) not in possible],
            'archive_catalogue':[{'key':list(match_key(m)),'match':m} for m in matches],'archive_problems':problems,
            'policy':'Read only. All classifications are suggestions. Even exact suggestions require explicit approval before supplemental storage. No uncertain links are automatic.'}


def write_report(report,destination):
    from .archive import safe_destination
    destination=safe_destination(destination);destination.mkdir(parents=True,exist_ok=True)
    (destination/'reconciliation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# Excel match-log reconciliation','',report['policy'],'',f"Workbook SHA-256: `{report['workbook']['sha256']}`",'']
    lines+=['| Classification | Count |','|---|---:|']+[f'| {k} | {v} |' for k,v in report['counts'].items()]
    lines+=['',report['timezone_note'],'','Field-conflict and spreadsheet-only counts are overlapping row flags, not additional match rows. Archive-only excludes every supported possible candidate, including uncertain candidates. Blank cells are unknown, not zero. Full cell/formula/notes and candidate field comparisons are in reconciliation.json.','', '## Sheets inspected','']
    lines += [f"- {s['name']}: {s['kind']}, {s['nonempty_rows']} nonempty rows, {len(s['cells'])} populated/comment cells." for s in report['workbook']['sheets']]
    lines+=['','## Match review','']
    for r in report['results']:
        lines += [f"### {r['sheet']} row {r['row']} (game {r['game']}): {r['classification']}"]
        for c in r['candidates']:
            lines += [f"Candidate {c['key']}: {c['source']}; anchors {', '.join(c['anchors'])}; time difference {c['time_difference_seconds']} seconds."]
            for f in c['fields']:
                if f['status'] not in ('Identical','Missing from Excel'):lines.append(f"- {f.get('cell','')} {f['field']}: {f['status']}. Excel {str(f.get('excel_value'))[:180]}; archive {str(f.get('archive_value'))[:120]}. {f.get('note','')}")
        if not r['candidates']:lines.append('No candidate met the evidence threshold. This does not prove the game was never captured in undecodable raw data.')
        lines.append('')
    (destination/'RECONCILIATION.md').write_text('\n'.join(lines),encoding='utf8')
    return str(destination/'RECONCILIATION.md')
