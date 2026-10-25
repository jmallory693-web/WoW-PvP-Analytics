"""Single-file, streamed, self-contained JSON/gzip exports with verification."""
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .archive import safe_destination
from .sync import home_lock
from .player_index import read_archive, encounters
from .metric_registry import METRICS, VERSION
from .metrics import Filters, filter_matches, match_key


class Cancelled(Exception): pass


def typed(value):
    if isinstance(value, bytes):return {'$type':'blob','base64':base64.b64encode(value).decode('ascii')}
    return value


class JsonCheck:
    """Streaming JSON grammar validation, without materializing source-byte strings."""
    def __init__(self, stream):self.stream,self.buffer,self.position=stream,'',0
    def peek(self):
        if self.position==len(self.buffer):self.buffer=self.stream.read(65536);self.position=0
        return self.buffer[self.position:self.position+1]
    def take(self):
        value=self.peek();self.position+=bool(value);return value
    def white(self):
        while self.peek() and self.peek().isspace():self.take()
    def require(self,ch):
        self.white()
        if self.take()!=ch:raise ValueError('Invalid JSON export: expected '+ch)
    def string(self):
        self.require('"')
        while True:
            c=self.take()
            if not c or ord(c)<32:raise ValueError('Invalid JSON string')
            if c=='"':return
            if c=='\\':
                e=self.take()
                if e=='u':
                    if any(self.take() not in '0123456789abcdefABCDEF' for _ in range(4)):raise ValueError('Invalid Unicode escape')
                elif e not in '"\\/bfnrt':raise ValueError('Invalid JSON escape')
    def value(self,depth=0):
        if depth>200:raise ValueError('Export nesting too deep')
        self.white();c=self.peek()
        if c=='"':self.string()
        elif c in ('{','['):
            self.take();end='}' if c=='{' else ']';self.white()
            if self.peek()==end:self.take();return
            while True:
                if c=='{':self.string();self.require(':')
                self.value(depth+1);self.white();next_=self.take()
                if next_==end:return
                if next_!=',':raise ValueError('Invalid JSON container')
        elif c in 'tfn' and c:
            word={'t':'true','f':'false','n':'null'}[c]
            if ''.join(self.take() for _ in word)!=word:raise ValueError('Invalid JSON literal')
        else:
            number=''
            while self.peek() and self.peek() in '-+0123456789.eE':number+=self.take()
            import re
            if not re.fullmatch(r'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?',number):raise ValueError('Invalid JSON number')


def validate(path):
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rt',encoding='utf8') as stream:
        checker=JsonCheck(stream);checker.value();checker.white()
        if checker.peek():raise ValueError('Trailing export content')
    digest=hashlib.sha256();tail=b''
    marker=b',"integrity":'
    with opener(path,'rb') as stream:
        while True:
            chunk=stream.read(65536)
            if not chunk:break
            tail+=chunk
            # Retain the bounded footer; everything else is hashed incrementally.
            if len(tail)>1048576:
                digest.update(tail[:-1048576]);tail=tail[-1048576:]
    position=tail.rfind(marker)
    if position<0:raise ValueError('Missing integrity footer')
    digest.update(tail[:position])
    footer=json.loads(tail[position+len(marker):-1])
    if footer['prefix_sha256']!=digest.hexdigest():raise ValueError('Export integrity mismatch')
    return footer


def export_dump(home,destination,scope='Full Archive',filters=None,players=(),character=None,progress=None,cancel=None):
    home=Path(home).resolve();destination=safe_destination(destination)
    if destination.is_relative_to(home):raise ValueError('Export outside the archive folder to avoid recursive inclusion')
    if scope not in ('Full Archive','My Characters','Individual Character','Selected Players','Current Filters'):raise ValueError('Unknown export scope')
    progress=progress or (lambda message:None);cancel=cancel or (lambda:False)
    with home_lock(home):
        db=read_archive(home)
        handle,temporary=tempfile.mkstemp(prefix='ai-dump-',suffix='.json.gz' if str(destination).endswith('.gz') else '.json',dir=destination.parent)
        os.close(handle);temporary=Path(temporary)
        try:
            from .dual_archive import project
            from types import SimpleNamespace
            from .identity import IdentityMap, character_key
            # Load existing mappings without discovery or writes.
            from .player_index import read_identities
            identities=read_identities(home)
            matches,rosters=project(SimpleNamespace(db=db))
            from .metric_registry import values
            for row in rosters: values(row) # Register source-specific objective definitions before emitting registry.
            selected=matches
            if scope=='Current Filters':selected=filter_matches(matches,rosters,filters,identities)
            if scope=='My Characters':selected=[m for m in matches if identities.resolve(m['Character'],m.get('Realm'))==identities.owner_person]
            if scope=='Individual Character':
                if not character:raise ValueError('Select an exact character and realm')
                selected=[m for m in matches if character_key(m['Character'],m.get('Realm'))==character_key(character)]
            if scope=='Selected Players' or scope=='Individual Character' and players:
                if not players:raise ValueError('Select at least one player')
                index_path=home/'intelligence.sqlite'
                if not index_path.exists():raise ValueError('Build the player index using Sync Now before exporting selected players')
                import sqlite3
                ix=sqlite3.connect(index_path.resolve().as_uri()+'?mode=ro',uri=True)
                try:events={tuple(json.loads(r[0])['canonical_key']) for r in ix.execute('SELECT data FROM sightings WHERE player_key IN ('+','.join('?' for _ in players)+')',tuple(players))}
                finally:ix.close()
                selected=[m for m in matches if match_key(m) in events]
            ids={i for m in selected for i in m['_observation_ids']}
            # Include all endpoints needed to interpret ambiguity/manual decisions.
            links=[dict(r) for r in db.execute('SELECT * FROM match_links')]
            while True:
                expanded=ids|{i for r in links if r['left_id'] in ids or r['right_id'] in ids for i in (r['left_id'],r['right_id'])}
                if expanded==ids:break
                ids=expanded
            observations=[dict(r) for r in db.execute('SELECT * FROM observations') if scope=='Full Archive' or r['id'] in ids]
            keys={(r['character'],r['realm'],r['match_id']) for r in observations}
            import_ids={r[k] for r in observations for k in ('first_import','last_import') if r[k] is not None}
            import_ids|={r['import_id'] for r in db.execute('SELECT * FROM observation_versions') if r['observation_id'] in ids}
            import_ids|={r[k] for r in db.execute('SELECT * FROM observation_files') if r['observation_id'] in ids for k in ('first_import','last_import') if r[k] is not None}
            file_ids={r['file_id'] for r in db.execute('SELECT * FROM observation_files') if r['observation_id'] in ids}
            def include(table,r):
                if scope=='Full Archive':return True
                if table=='observations':return r['id'] in ids
                if table in ('matches','rosters','overrides','snapshot_aliases'):return (r['character'],r['realm'],r['match_id']) in keys
                if table in ('observation_versions','observation_files'):return r['observation_id'] in ids
                if table=='source_files':return r['id'] in file_ids
                if table in ('match_links','link_history'):return r['left_id'] in ids or r['right_id'] in ids
                if table=='imports':return r['id'] in import_ids
                if table=='raw_rows':return r['import_id'] in import_ids
                return True # Unfamiliar tables are retained as explicitly contextual data.
            counts={};checksum=hashlib.sha256()
            opener=gzip.open if str(destination).endswith('.gz') else open
            with opener(temporary,'wb') as out:
                def write(text):
                    if cancel():raise Cancelled('Export cancelled')
                    data=text.encode('utf8');out.write(data);checksum.update(data)
                def encode(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False,default=typed)
                write('{"manifest":'+encode({'export_version':'1.4.0','application_version':'1.4.0','archive_schema':db.execute('PRAGMA user_version').fetchone()[0],
                      'created':datetime.now(timezone.utc).isoformat(),'scope':scope,'full_archive':scope=='Full Archive',
                      'include_full_source_context':True,'context_warning':'Source snapshots, global artifacts and linked evidence may contain out-of-filter records.',
                      'filters':vars(filters or Filters()),'definition':'Logical matches are analytics records; observations/revisions/raw imports are evidence and must not be added to match counts.'}))
                write(',"data_dictionary":'+encode({'database':'Every original SQL column; JSON stored in TEXT stays original TEXT. BLOBs use typed base64.',
                    'logical_matches':'Canonical owner-perspective match with all recorded participants nested. Source observation IDs connect to database tables.',
                    'source_bytes':'Exact original files, base64 encoded. Lua key distinctions preserved in these original bytes, not coerced through JSON object keys.',
                    'derived':'Calculated metrics explicitly separated; NULL is unavailable, zero is observed zero.',
                    'unresolved':'Undecodable/ambiguous source records are retained in the sidecar and original snapshots.',
                    'coverage':'Unknown completeness is not proof of full-team coverage. All rankings refer only to archived encounters.'}))
                write(',"metric_registry":'+encode({'version':VERSION,'metrics':METRICS}))
                write(',"schema_objects":'+encode([dict(r) for r in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]))
                write(',"database":{')
                tables=list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))
                for ti,table in enumerate(tables):
                    name=table['name'];quoted='"'+name.replace('"','""')+'"'
                    progress('Exporting table '+name)
                    if ti:write(',')
                    write(encode(name)+':{"definition":'+encode(table['sql'])+',"columns":'+encode([dict(r) for r in db.execute('PRAGMA table_info('+quoted+')')])+',"rows":[')
                    count=0
                    for row in db.execute('SELECT * FROM '+quoted):
                        if not include(name,row):continue
                        if count:write(',')
                        write(encode(dict(row)));count+=1
                    counts[name]=count;write(']}')
                write('},"analytical_indexes":{')
                if (home/'intelligence.sqlite').exists():
                    import sqlite3
                    ix=sqlite3.connect((home/'intelligence.sqlite').as_uri()+'?mode=ro',uri=True);ix.row_factory=sqlite3.Row
                    try:
                        for ti,table in enumerate(ix.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")):
                            name=table['name'];quoted='"'+name.replace('"','""')+'"'
                            if ti:write(',')
                            write(encode(name)+':{"definition":'+encode(table['sql'])+',"rows":[')
                            count=0
                            for row in ix.execute('SELECT * FROM '+quoted):
                                if count:write(',')
                                write(encode(dict(row)));count+=1
                            counts['sidecar.'+name]=count;write(']}')
                    finally:ix.close()
                write('},"supplemental_archive":{')
                from .supplemental import read_db as read_supplemental
                supplement=read_supplemental(home)
                if supplement:
                    try:
                        for ti,table in enumerate(supplement.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")):
                            name=table['name'];quoted='"'+name.replace('"','""')+'"'
                            progress('Exporting Excel evidence: '+name)
                            if ti:write(',')
                            write(encode(name)+':{"definition":'+encode(table['sql'])+',"columns":'+encode([dict(r) for r in supplement.execute('PRAGMA table_info('+quoted+')')])+',"rows":[')
                            count=0
                            for row in supplement.execute('SELECT * FROM '+quoted):
                                if count:write(',')
                                write(encode(dict(row)));count+=1
                            counts['supplemental.'+name]=count;write(']}')
                    finally:supplement.close()
                write('},"supplemental_dictionary":'+encode({'source':'Excel historical import is manually approved spreadsheet evidence, never a verified complete addon scoreboard.',
                    'workbooks.original_bytes':'Exact XLSX bytes in typed base64, keyed by SHA-256; document preserves all sheets, cells, original formulas, caches, comments and unimported fields.',
                    'decisions':'Append-only link/historical/reject/reverse decisions; latest per row governs projections. Original addon tables and identity mappings are never changed.',
                    'rounding':'Millions convert to base units with original values and tolerances retained. Match duration is not individual attendance. Conflicts retain both values.',
                    'scope':'Full source context intentionally includes all supplemental decisions/workbooks, including out-of-filter and reversed evidence.'}))
                write(',"rated_career":{')
                from .career import connect as read_rated,DEFINITIONS as rated_definitions,model as rated_model
                rated=read_rated(home)
                if rated:
                    try:
                        for ti,table in enumerate(rated.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")):
                            name=table['name'];quoted='"'+name.replace('"','""')+'"'
                            if ti:write(',')
                            write(encode(name)+':{"definition":'+encode(table['sql'])+',"columns":'+encode([dict(r) for r in rated.execute('PRAGMA table_info('+quoted+')')])+',"rows":[')
                            count=0
                            for row in rated.execute('SELECT * FROM '+quoted):
                                if count:write(',')
                                write(encode(dict(row)));count+=1
                            counts['rated.'+name]=count;write(']}')
                    finally:rated.close()
                write('},"rated_definitions":'+encode(rated_definitions))
                # All permanent rated context is explicit, including manual revisions
                # outside a filtered match scope. Never silently omit a career.
                rated_views=[]
                catalogue=rated_model(home,include_others=True)
                for character in catalogue['characters']:
                    career=rated_model(home,player=character['player_key'],include_others=True)
                    rated_views.append({'character':character,'summaries':career['summaries'],'progression':career['series'],'unclassified':career['unclassified']})
                write(',"rated_calculated":'+encode({'scope':'Full rated source context; may include out-of-filter characters','characters':rated_views}))
                write(',"logical_matches":[')
                coverage={name:{'known':0,'missing':0} for name in METRICS}
                for i,m in enumerate(selected):
                    if i:write(',')
                    rows=[r for r in rosters if (r['Owner character'],r['Owner realm'],r['Match ID'])==match_key(m)]
                    calculated=[]
                    for r in rows:
                        attendance=m.get('Minutes played') if r.get('Is me')=='Yes' else None
                        metrics=values(r | {'Minutes played':attendance})
                        for name,value in metrics.items():
                            coverage.setdefault(name,{'known':0,'missing':0})['known' if value is not None else 'missing']+=1
                        calculated.append({'original_projection':r,'calculated':metrics})
                    write(encode({'original_projection':m,'participants':calculated}))
                write('],"profile_artifacts":[')
                expected={Path(r['snapshot']).resolve():r['sha256'] for r in db.execute('SELECT id,snapshot,sha256 FROM imports WHERE snapshot IS NOT NULL') if scope=='Full Archive' or r['id'] in import_ids}
                # Include ALL files in full scope, including auxiliary snapshots and identity/database backups.
                files=sorted({p.resolve() for p in home.rglob('*') if p.is_file() and not p.name.endswith(('-wal','-shm','-journal'))}|set(expected))
                artifact_count=0;artifact_inventory=[]
                artifact_inventory.extend({'path':str(p.relative_to(home)),'status':'transient_sqlite_journal_excluded; committed data represented by read transactions'} for p in home.rglob('*') if p.is_file() and p.name.endswith(('-wal','-shm','-journal')))
                for path in files:
                    relative=str(path.relative_to(home)) if path.is_relative_to(home) else 'external_snapshots/'+path.name
                    if path==home/'archive.sqlite':
                        artifact_inventory.append({'path':relative,'status':'represented_losslessly_by_database_tables'});continue
                    if scope!='Full Archive' and path.parent==home/'snapshots' and path.resolve() not in expected:continue
                    if artifact_count:write(',')
                    before=path.stat();raw_digest=hashlib.sha256();size=0
                    write('{"path":'+encode(relative)+',"encoding":"base64","bytes":"')
                    with path.open('rb') as source:
                        while True:
                            chunk=source.read(49152)
                            if not chunk:break
                            raw_digest.update(chunk);size+=len(chunk);write(base64.b64encode(chunk).decode('ascii'))
                    sha=raw_digest.hexdigest()
                    if path.resolve() in expected and sha!=expected[path.resolve()]:raise ValueError('Snapshot hash mismatch: '+relative)
                    after=path.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise OSError('Profile artifact changed during export: '+relative)
                    write('","sha256":'+encode(sha)+',"size":'+str(size)+'}')
                    artifact_count+=1;artifact_inventory.append({'path':relative,'status':'embedded','sha256':sha,'size':size})
                if any(not p.is_file() for p in expected):raise OSError('Missing original snapshot; export cannot be declared complete')
                write('],"artifact_inventory":'+encode(artifact_inventory))
                write(',"completeness":'+encode({'scope_complete':True,'full_archive':scope=='Full Archive','raw_sources_verified':True,
                       'normalization_complete':False,'normalization_note':'Unsupported raw fields remain available in original bytes/rows; derived metric NULLs do not indicate zero.',
                       'logical_matches':len(selected),'artifacts':artifact_count,'table_counts':counts,'participant_metric_coverage':coverage}))
                prefix=checksum.hexdigest()
                write(',"integrity":'+encode({'algorithm':'SHA-256','definition':'UTF-8 uncompressed bytes preceding the final integrity member',
                      'prefix_sha256':prefix,'table_counts':counts,'logical_matches':len(selected),'artifacts':artifact_count})+'}')
                out.flush()
            with temporary.open('r+b') as f:os.fsync(f.fileno())
            progress('Validating JSON, decompression and integrity…')
            validation=validate(temporary)
            if cancel():raise Cancelled('Export cancelled')
            temporary.replace(destination)
            return {'path':str(destination),'bytes':destination.stat().st_size,'validation':validation}
        finally:
            db.close()
            if temporary.exists():temporary.unlink()
