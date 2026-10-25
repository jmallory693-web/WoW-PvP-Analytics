"""Rebuildable index of every retained snapshot, including older roster sightings."""
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from .sync import sidecar, home_lock
from .lua_reader import loads, sequence
from .normalize import normalize
from .schema import parse_row
from .reflex_reader import parse_reflex, DEFAULT_ZONE
from .identity import character_key, normalized, IdentityMap
from .metric_registry import values


def read_identities(home):
    """Resolve mappings without seeding or writing a missing people.json."""
    from .identity import SEED
    value = object.__new__(IdentityMap)
    value.path = Path(home)/'people.json'
    document = json.loads(value.path.read_text(encoding='utf-8-sig')) if value.path.exists() else {'people':SEED}
    from .identity import owner_id
    value.owner_person = owner_id(document)
    value.people = document['people'];value.profiles = document.get('profiles',{})
    value._validate()
    return value


def uid(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read_archive(home):
    db = sqlite3.connect((Path(home) / 'archive.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    return db


def rebuild(home, force=False):
    home = Path(home)
    with home_lock(home):
        db = read_archive(home)
        index = sidecar(home)
        try:
            identities_raw = (home / 'people.json').read_bytes() if (home / 'people.json').exists() else b'{}'
            from .supplemental import generation as supplemental_generation
            signature = uid(['index-algorithm-1.3-excel',supplemental_generation(home),list(map(tuple, db.execute('SELECT id,sha256,status FROM imports'))),
                             list(map(tuple, db.execute('SELECT * FROM overrides'))), list(map(tuple, db.execute('SELECT * FROM match_links'))), identities_raw.hex()])
            existing = index.execute("SELECT value FROM index_meta WHERE key='signature'").fetchone()
            if not force and existing and existing[0] == signature:
                return stats(index)
            from .dual_archive import project
            matches, projected_rows = project(SimpleNamespace(db=db))
            from .comparisons import same_event
            from .metrics import group_rosters, match_key
            grouped = group_rosters(projected_rows)
            event_groups = []
            for match in matches:
                possible = [g for g in event_groups if all(same_event(match, other, grouped.get(match_key(match), []), grouped.get(match_key(other), [])) for other in g)]
                if len(possible) == 1:possible[0].append(match)
                else:event_groups.append([match])
            event_ids = {match_key(m): 'event:'+str(min((i for member in g for i in member['_observation_ids']),default='Excel-'+g[0].get('_excel_id','unknown'))) for g in event_groups for m in g}
            event_map, canonical = {}, {}
            obs = {r['id']: r for r in db.execute('SELECT * FROM observations')}
            for m in matches:
                event = event_ids[match_key(m)]
                for oid in m['_observation_ids']:
                    r = obs[oid]
                    event_map[(r['character'], r['realm'], r['original_id'])] = event
                    event_map[(r['character'], r['realm'], r['match_id'])] = event
                    canonical[(r['character'], r['realm'], r['original_id'])] = m
                    canonical[(r['character'], r['realm'], r['match_id'])] = m
            for r in db.execute('SELECT * FROM snapshot_aliases'):
                target = (r['character'], r['realm'], r['match_id'])
                if target in event_map:
                    alias = (r['character'], r['realm'], r['snapshot_id'])
                    event_map[alias] = event_map[target];canonical[alias] = canonical[target]
            sightings, unresolved, seen_hashes = {}, {}, set()
            recovery_records, recovery_fields = set(), set()
            zone = DEFAULT_ZONE
            if (home / 'settings.json').exists(): zone = json.loads((home / 'settings.json').read_text(encoding='utf-8-sig')).get('source_timezone', zone)
            for imported in db.execute('SELECT id,source,sha256,snapshot FROM imports WHERE snapshot IS NOT NULL ORDER BY id'):
                digest = imported['sha256']
                if digest in seen_hashes: continue
                seen_hashes.add(digest)
                path = Path(imported['snapshot'])
                try:
                    raw = path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != digest: raise ValueError('Snapshot hash mismatch')
                    document = loads(raw.decode('utf-8-sig'))
                    source = Path(imported['source'])
                    owner = realm = None
                    if source.parent.name == 'SavedVariables' and source.parent.parent.parent.name != 'Account':
                        owner, realm = source.parent.parent.name, source.parent.parent.parent.name
                    if not owner or not realm:
                        owners = {(r[0],r[1]) for r in db.execute('''SELECT DISTINCT o.character,o.realm FROM observations o
                            LEFT JOIN observation_versions v ON v.observation_id=o.id
                            WHERE o.first_import=? OR o.last_import=? OR v.import_id=?''', (imported['id'],)*3)}
                        if len(owners)==1:
                            owner,realm = next(iter(owners))
                    if 'REFlexDatabase' in document:
                        addon = 'REFlex'
                        ms, rs, aliases, problems = parse_reflex(document, owner, realm, zone)
                    elif 'PvPLedgerDB' in document:
                        addon = 'PvP Ledger'
                        ms, rs, aliases, problems = normalize(document, owner, realm)
                        # Preserve all earlier players, not only the selected largest/latest orphan snapshot.
                        for line in sequence(document['PvPLedgerDB'].get('rosterCSV')):
                            row = parse_row(line, 'roster', [])
                            if not row or not row.get('Player'): continue
                            keys = [k for k in ms if k[2] == row['Match ID']]
                            keys += [v for k,v in aliases.items() if k[2] == row['Match ID']]
                            if not keys and len({k[:2] for k in ms}) == 1:
                                c,w = next(iter(ms))[:2]; keys = [(c,w,row['Match ID'])]
                            if keys:
                                key = keys[0]
                                if key not in ms:
                                    ms[key] = {'Character':key[0], 'Realm':key[1], 'Match ID':key[2], '_partial':True}
                                rs.setdefault(key, []).append(row)
                            else:
                                unresolved[uid([digest,line])] = {'source_hash':digest,'raw':line,'reason':'No unambiguous recording perspective'}
                    else:
                        continue # Auxiliary data remains in the lossless snapshots/export.
                    for issue in problems:
                        if issue.get('code','').startswith(('invalid','missing','ambiguous','unverified')):
                            unresolved[uid([digest,issue])] = {'source_hash':digest,'diagnostic':issue}
                    for key, m in ms.items():
                        event = event_map.get(key, 'unresolved-event:' + uid(key))
                        cm = canonical.get(key, m)
                        effective = m.copy()
                        user_overrides = {field:cm.get(field) for field,providers in cm.get('_provenance',{}).items() if 'User override' in providers}
                        effective.update(user_overrides)
                        if m.get('Schema version') == 5:
                            recovery_records.add(key)
                            old = next((json.loads(r['data']) for r in db.execute('SELECT data FROM matches WHERE character=? AND realm=? AND match_id=?',key)), {})
                            recovery_fields.update((key,k) for k,v in m.items() if not k.startswith('_') and v is not None and old.get(k) is None)
                        rows = rs.get(key, [])
                        # Owner-only records remain searchable even when there is no captured scoreboard.
                        if not any(character_key(r['Player'],r.get('Realm')) == character_key(key[0],key[1]) for r in rows):
                            rows = rows + [dict(m, Player=key[0], Realm=key[1], **{'Is me':'Yes','Team':'Mine'})]
                        for row in rows:
                            name, world = row.get('Player'), row.get('Realm') or ''
                            if not name: continue
                            own = character_key(name,world) == character_key(key[0],key[1])
                            certainty = 'observed' if world else 'unknown'
                            from .reflex_reader import at
                            if addon == 'REFlex' and not own and '-' not in str(at(row.get('_raw_reflex_player',{}),1) or ''):
                                certainty = 'inferred' if world else 'unknown'
                            player = uid([*character_key(name,world), certainty, key[1] if certainty != 'observed' else ''])
                            record = {f:effective.get(f) for f in ('Date','Time','Type','Map','Map ID','Duration (s)','Epoch')}
                            if record.get('Epoch'):
                                stamp = datetime.fromtimestamp(record['Epoch'],timezone.utc)
                                from zoneinfo import ZoneInfo
                                stamp = stamp.astimezone(ZoneInfo(zone));record.update(Date=stamp.strftime('%Y-%m-%d'),Time=stamp.strftime('%H:%M'))
                            record.update(row)
                            record['user_overrides'] = user_overrides
                            record.update(player_key=player,event_id=event,Player=name,Realm=world,realm_certainty=certainty,
                                          source=addon,source_hash=digest,import_id=imported['id'],perspective=list(key),
                                          canonical_key=[cm['Character'],cm.get('Realm'),cm['Match ID']],
                                          _cohort_verified_complete=False, _scoreboard_incomplete=True,
                                          relationship='self' if own else 'ally' if row.get('Team')=='Mine' else 'opponent' if row.get('Team')=='Enemy' else 'unknown')
                            # Source count equality cannot prove all intended team
                            # members or departures were captured.
                            record['_source_reported_complete'] = addon=='REFlex' and not m.get('_scoreboard_incomplete')
                            if own:
                                record['Minutes played'] = effective.get('Minutes played')
                                for f in ('Damage','Healing','Deaths','KB','HK','Class','Spec'):
                                    if m.get(f) is not None: record[f] = m[f]
                            else: record['Minutes played'] = None
                            result = cm.get('Result')
                            record['Result'] = result if own or row.get('Team')=='Mine' else {'W':'L','L':'W'}.get(result) if row.get('Team')=='Enemy' else None
                            record['metrics'] = values(record)
                            record['quality'] = 'last seen' if row.get('Left early') else 'observed; cohort completeness unverified' if not record['_cohort_verified_complete'] else 'source scoreboard complete'
                            record['provenance'] = {'snapshot_sha256':digest,'original_record':row.get('_raw',row.get('_raw_reflex_player'))}
                            sid = uid([key,player,addon,row.get('_raw',row.get('_raw_reflex_player')),m.get('_raw',m.get('_raw_reflex'))])
                            sightings[sid] = record | {'sighting_id':sid}
                except (OSError,ValueError,TypeError,KeyError) as exc:
                    unresolved[uid([digest,'file'])] = {'source_hash':digest,'reason':str(exc),'snapshot':str(path)}
            # Old observation revisions remain a second evidence path when a
            # snapshot is absent/undecodable. Never make the index their only copy.
            present = {(r['event_id'],r['player_key']) for r in sightings.values()}
            for version in db.execute('SELECT * FROM observation_versions ORDER BY import_id DESC'):
                observation = obs.get(version['observation_id'])
                if observation is None:continue
                key = (observation['character'],observation['realm'],observation['original_id'])
                m = json.loads(version['payload'])
                event = event_map.get(key,'unresolved-event:'+uid(key))
                cm = canonical.get(key,m)
                for row in json.loads(version['roster']):
                    if not row.get('Player'):continue
                    name,world = row['Player'],row.get('Realm') or ''
                    own = character_key(name,world)==character_key(key[0],key[1])
                    from .reflex_reader import at
                    certainty = 'observed' if world else 'unknown'
                    raw_player=row.get('_raw_reflex_player',{})
                    raw_name=raw_player.get('1',at(raw_player,1)) if isinstance(raw_player,dict) else at(raw_player,1)
                    if observation['addon']=='REFlex' and not own and '-' not in str(raw_name or ''):certainty='inferred' if world else 'unknown'
                    player = uid([*character_key(name,world),certainty,key[1] if certainty!='observed' else ''])
                    if (event,player) in present:continue
                    record = {f:m.get(f) for f in ('Date','Time','Type','Map','Map ID','Duration (s)','Epoch')}
                    record.update(row)
                    record.update(player_key=player,event_id=event,realm_certainty=certainty,source=observation['addon'],
                                  source_hash=None,import_id=version['import_id'] or 0,perspective=list(key),
                                  canonical_key=[cm['Character'],cm.get('Realm'),cm['Match ID']],
                                  relationship='self' if own else 'ally' if row.get('Team')=='Mine' else 'opponent' if row.get('Team')=='Enemy' else 'unknown',
                                  _cohort_verified_complete=False,_scoreboard_incomplete=True,
                                  quality='Retained observation revision; completeness unverified',
                                  provenance={'observation_id':version['observation_id'],'version_digest':version['digest']})
                    record['Minutes played'] = m.get('Minutes played') if own else None
                    result = cm.get('Result')
                    record['Result'] = result if own or row.get('Team')=='Mine' else {'W':'L','L':'W'}.get(result) if row.get('Team')=='Enemy' else None
                    record['metrics'] = values(record)
                    sid = uid(['observation-version',version['observation_id'],version['digest'],player])
                    record['sighting_id']=sid;sightings[sid]=record;present.add((event,player))
            from .supplemental import sightings as excel_sightings
            for fact in excel_sightings(home,matches,event_ids):sightings[fact['sighting_id']]=fact
            with index:
                index.execute('DELETE FROM sightings');index.execute('DELETE FROM unresolved')
                index.executemany('INSERT INTO sightings VALUES (?,?,?,?)', [(k,v['player_key'],v['event_id'],json.dumps(v,ensure_ascii=False)) for k,v in sightings.items()])
                index.executemany('INSERT INTO unresolved VALUES (?,?)',[(k,json.dumps(v,ensure_ascii=False)) for k,v in unresolved.items()])
                index.execute('INSERT OR REPLACE INTO index_meta VALUES (?,?)',('signature',signature))
                index.execute('INSERT OR REPLACE INTO index_meta VALUES (?,?)',('recovery',json.dumps({'records':len(recovery_records),'fields':len(recovery_fields)})))
            return stats(index)
        finally:
            db.close();index.close()


def stats(index):
    recovery = index.execute("SELECT value FROM index_meta WHERE key='recovery'").fetchone()
    return {'sightings':index.execute('SELECT count(*) FROM sightings').fetchone()[0],
            'players':index.execute('SELECT count(distinct player_key) FROM sightings').fetchone()[0],
            'unresolved':index.execute('SELECT count(*) FROM unresolved').fetchone()[0],
            'recovery':json.loads(recovery[0]) if recovery else {}}


def encounters(home, player=None, perspective=None):
    rebuild(home)
    db = sidecar(home)
    try:
        rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM sightings' + (' WHERE player_key=?' if player else ''), (player,) if player else ())]
        if perspective:
            rows = [r for r in rows if tuple(r['canonical_key']) == tuple(perspective)]
        best = {}
        for row in rows:
            key = (row['event_id'],row['player_key'])
            quality = (row.get('source')!='Excel historical import',row.get('Epoch') or 0, row.get('Left early') != 1, row['import_id'],sum(v is not None for v in row['metrics'].values()))
            if key not in best or quality > best[key][0]:best[key] = quality,row
        output = []
        for (_,player),(_,r) in best.items():
            alternatives = [s for s in rows if s['event_id']==r['event_id'] and s['player_key']==player]
            r['recording_perspectives'] = sorted({tuple(s['perspective'][:2]) for s in alternatives})
            r['source_sighting_ids'] = [s['sighting_id'] for s in alternatives]
            r['source_addons'] = sorted({s['source'] for s in alternatives})
            # Preserve every addon value. Approved spreadsheet facts can fill
            # genuinely missing participant metrics, with their own provenance.
            supplements=[s for s in alternatives if s['source']=='Excel historical import']
            for field in ('Damage','Healing','KB','HK','Deaths','Honor','Rating change','Objectives'):
                if r.get(field) is None and not any(s.get(field) is not None for s in alternatives if s['source']!='Excel historical import'):
                    provider=next((s for s in supplements if s.get(field) is not None),None)
                    if provider:
                        r[field]=provider[field];r.setdefault('supplemental_provenance',{})[field]=provider['provenance'];r['quality']='Manually supplemented; observed cohort only'
            r['metrics'] = values(r)
            output.append(r)
        return sorted(output,key=lambda r:(r.get('Date') or '',r.get('Time') or '',r['sighting_id']))
    finally:db.close()


def directory(home, query='', class_name='', spec='', page=0, page_size=100):
    rows = encounters(home)
    identities = read_identities(home)
    groups = defaultdict(list)
    for r in rows:
        if class_name and r.get('Class') != class_name or spec and r.get('Spec') != spec:continue
        groups[r['player_key']].append(r)
    result = []
    q = normalized(query)
    for key, seen in groups.items():
        r = seen[-1];name=normalized(r['Player']);full=normalized(r['Player']+'-'+r['Realm'])
        priority = 0 if not q or q in (name,full) else 1 if name.startswith(q) else 2 if q in full else 3 if SequenceMatcher(None,q,name).ratio()>=.6 else 4
        if priority==4:continue
        result.append({'player_key':key,'Player':r['Player'],'Realm':r['Realm'],'Realm certainty':r['realm_certainty'],
                       'Class':r.get('Class'),'Spec':r.get('Spec'),'Person':identities.label(identities.resolve(r['Player'],r['Realm'])),
                       'Relationship':', '.join(sorted({s['relationship'] for s in seen})), 'Encounters':len(seen),
                       'First':seen[0].get('Date'),'Last':r.get('Date'),'Available statistics':', '.join(k for k in r['metrics'] if any(s['metrics'].get(k) is not None for s in seen)),
                       'Quality':r['quality'],'_priority':priority})
    result.sort(key=lambda r:(r['_priority'],normalized(r['Player']),r['Realm'],r['Realm certainty']))
    return {'total':len(result),'page':page,'rows':result[page*page_size:(page+1)*page_size]}
