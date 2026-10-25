import base64,gzip,hashlib,json,sqlite3
from pathlib import Path
from copy import deepcopy
import pytest
from pvpledger_viewer.archive import Archive
from pvpledger_viewer.career import recover,observations,model,save_manual,reverse_manual,manual_history,connect,validate_manual
from pvpledger_viewer.career_sources import extract,player_id
from pvpledger_viewer.lua_reader import loads
from pvpledger_viewer.full_export import export_dump
from pvpledger_viewer.service import DesktopService
from test_dual_archive import lua
from test_core import match,write_source

REAL=Path(__file__).parent/'fixtures/v14/REFlex.lua'


def raw_record(stamp=1792880000,owner='Me',world='Realm',season=42,rating=1500,change=20,shuffle=False):
    players=[]
    for n in range(6 if shuffle else 4):
        p=[owner+'-'+world if n==0 else f'Other{n}-Elsewhere',0,0,0,0,n%2,'Human','Paladin','PALADIN',1234,123, rating if n==0 else 1000,change if n==0 else 0,1800,0,'Retribution',1]
        players.append(p)
    return {'Version':3501,'Season':season,'Time':stamp,'isRated':True,'isArena':True,'isSoloShuffle':shuffle,'isRatedSoloShuffle':shuffle,'PlayerNum':1,'PlayerSide':0,'Winner':0,'Players':players,'PlayersNum':len(players),'Map':1504,'Duration':90,'GameVersion':'Retail 12.0'}


def imported(tmp_path,records):
    home=tmp_path/'archive';source=tmp_path/'REFlex.lua';source.write_text('REFlexDatabase='+lua(records),encoding='utf8')
    a=Archive(home);a.import_file(source,'Me','Realm');a.close();recover(home);return home,source


def manual(**fields):
    return {'character':'Me','realm':'Realm','realm_certainty':'observed','spec':'Retribution','game_version':'Retail 12.0','season':'42','bracket':'2v2 Arena','rating':1800,'observed_at':'2026-10-25T12:00:00+00:00','source':'Manual','source_reference':'','ranking_region':'','notes':''}|fields


def own(home):return [r for r in observations(home) if r['own']]


def test_real_snapshot_recovers_personal_rating_separate_from_mmr():
    before=hashlib.sha256(REAL.read_bytes()).hexdigest();rows,issues=extract(loads(REAL.read_text(encoding='utf8')),'Asterknight','ExampleRealm')
    shuffle=[r for r in rows if r['own'] and r['bracket']=='Solo Shuffle']
    assert [(r['rating_before'],r['rating_change'],r['rating_after']) for r in shuffle]==[(0,891,891),(891,192,1083),(1083,0,1083)]
    assert all(r['season']==42 and r['game_version'] is None and r['result'] is None for r in shuffle)
    assert len(rows)==30 and not issues and hashlib.sha256(REAL.read_bytes()).hexdigest()==before


def test_character_realm_and_certainty_are_isolated(tmp_path):
    h,s=imported(tmp_path,[raw_record()]);before=own(h)[0]['player_key']
    save_manual(h,manual(realm='Other',rating=2100),approved=True)
    save_manual(h,manual(realm_certainty='inferred',identity_context='RecordingRealm',rating=2200),approved=True)
    assert model(h,player=before)['summaries'][0]['current']==1520
    assert len({r['player_key'] for r in own(h)})==3
    assert player_id('MÉ',' Realm ','observed')==player_id('mé','realm','observed')


def test_brackets_versions_specs_and_seasons_never_mix(tmp_path):
    h,s=imported(tmp_path,[raw_record()])
    for changes in ({'season':'43'},{'bracket':'3v3 Arena'},{'game_version':'Retail 12.1'},{'spec':'Holy'}):save_manual(h,manual(**changes),approved=True)
    data=model(h,player=own(h)[0]['player_key']);assert len(data['summaries'])==5
    assert all(g['observations']==1 for g in data['summaries'])
    assert len(model(h,player=own(h)[0]['player_key'],season='43')['summaries'])==1


def test_duplicate_scans_and_reordered_history_do_not_duplicate_ratings(tmp_path):
    first=raw_record();second=raw_record(stamp=first['Time']+300,rating=1520,change=-10)
    h,s=imported(tmp_path,[first,second]);before=own(h)
    assert recover(h)['added']==0
    s.write_text('REFlexDatabase='+lua([second,first]),encoding='utf8');a=Archive(h);a.import_file(s,'Me','Realm');a.close();recover(h)
    assert len(own(h))==len(before)==2
    data=model(h,player=before[0]['player_key']);assert data['summaries'][0]['games']==2


def test_historical_snapshots_survive_pruning_and_rebuild_without_originals(tmp_path):
    first=raw_record();second=raw_record(stamp=first['Time']+300,rating=1520,change=-10)
    h,s=imported(tmp_path,[first,second]);s.write_text('REFlexDatabase={}',encoding='utf8')
    a=Archive(h);a.import_file(s,'Me','Realm');a.close();recover(h);ids={r['id'] for r in own(h)}
    # An isolated destructive scenario: the retained rated source bytes alone
    # must recreate history if external snapshot files become unavailable.
    for p in (h/'snapshots').glob('*'):p.unlink()
    assert recover(h,True)['observations']>=2 and {r['id'] for r in own(h)}==ids


def test_manual_entry_correction_reversal_keeps_original_and_source(tmp_path):
    h,s=imported(tmp_path,[raw_record()]);original=(h/'archive.sqlite').read_bytes();source=own(h)[0].copy()
    with pytest.raises(PermissionError):save_manual(h,manual())
    one=save_manual(h,manual(rating=2300),approved=True);two=save_manual(h,manual(rating=1800),one['id'],'Correct mistyped rating',True)
    pid=source['player_key'];assert model(h,player=pid)['summaries'][0]['season_peak']==1800
    with pytest.raises(ValueError,match='latest'):save_manual(h,manual(),one['id'],'Stale correction',True)
    with pytest.raises(PermissionError):reverse_manual(h,two['id'])
    reverse_manual(h,two['id'],True)
    assert model(h,player=pid)['summaries'][0]['season_peak']==1520
    assert [r['action'] for r in manual_history(h)]==['reverse','record','record']
    assert own(h)[0]==source and (h/'archive.sqlite').read_bytes()==original


def test_peak_first_latest_and_point_deltas_are_recorded_not_estimated(tmp_path):
    h,s=imported(tmp_path,[raw_record(),raw_record(stamp=1792881000,rating=1520,change=-40)])
    summary=model(h,player=own(h)[0]['player_key'])['summaries'][0]
    assert (summary['current'],summary['season_peak'],summary['gains'],summary['loss_points'],summary['games'])==(1480,1520,20,-40,2)
    assert summary['wins']==2 and summary['leaderboard'] is None and summary['rank_verification']=='Not Available'
    assert summary['first']==1500


def test_date_filter_does_not_relabel_window_peak_as_season_peak(tmp_path):
    h,s=imported(tmp_path,[raw_record()]);pid=own(h)[0]['player_key']
    save_manual(h,manual(rating=2000,observed_at='2026-10-25T12:00:00Z'),approved=True)
    data=model(h,player=pid,end='2026-10-24');summary=data['summaries'][0]
    assert summary['season_peak']==2000 and summary['highest_recorded']==1520 and summary['current']==1520


def test_rank_requires_source_metadata_and_attestation_is_not_api_verification(tmp_path):
    h,s=imported(tmp_path,[raw_record()])
    with pytest.raises(ValueError,match='documented'):save_manual(h,manual(leaderboard_position=450),approved=True)
    save_manual(h,manual(leaderboard_position=450,ranking_region='US',source='Official leaderboard (manual citation)',source_reference='https://worldofwarcraft.blizzard.com/en-us/game/pvp/leaderboards/3v3',ranking_verified_by_user=True),approved=True)
    summary=model(h,player=own(h)[0]['player_key'])['summaries'][0]
    assert summary['leaderboard']==450 and summary['current']==1800
    assert 'not independently fetched' in summary['rank_verification'] and summary['ranking_region']=='US'


@pytest.mark.parametrize('fields',[{'rating':-1},{'rating':True},{'rating':'nan'},{'leaderboard_position':0},{'observed_at':'2026-10-24T12:00:00'},{'realm_certainty':'guessed'},{'realm_certainty':'inferred','identity_context':''},{'ranking_verified_by_user':'false'},{'bracket':'Random BG'}])
def test_manual_bad_values_fail_visibly(fields):
    with pytest.raises((ValueError,TypeError)):validate_manual(manual(**fields))


def test_missing_ratings_and_cohort_metadata_do_not_turn_into_zero_or_season_guesses(tmp_path):
    raw=raw_record();raw.pop('GameVersion');raw.pop('Season');raw['Players'][0][11]=None;raw['Players'][0][12]=None
    h,s=imported(tmp_path,[raw]);data=model(h,player=own(h)[0]['player_key']);r=data['observations'][0]
    assert r['rating'] is None and r['mmr_before']==1800 and data['summaries']==[] and data['unclassified']==1
    save_manual(h,manual(game_version='',season='',spec='',rating=0),approved=True)
    assert len(model(h,player=r['player_key'])['observations'])==2 and not model(h,player=r['player_key'])['summaries']


def test_shuffle_outcomes_not_inferred_from_rating_and_incomplete_arena_not_classified():
    raw=raw_record(shuffle=True);rows,issues=extract({'REFlexDatabase':[raw]},'Me','Realm');assert all(r['result'] is None for r in rows)
    raw=raw_record();raw['Players']=raw['Players'][:2]
    rows,issues=extract({'REFlexDatabase':[raw]},'Me','Realm');assert rows[0]['bracket'] is None


def test_unknown_reflex_schema_withholds_ratings_and_reports_problem():
    raw=raw_record();raw['Version']=9999;rows,issues=extract({'REFlexDatabase':[raw]},'Me','Realm')
    assert not rows and issues[0]['code']=='unverified_reflex_rating_schema'


def test_unknown_and_inferred_realms_stay_separate():
    raw=raw_record();raw['Players'][1][0]='Opponent';rows,issues=extract({'REFlexDatabase':[raw]},'Me','Realm')
    r=rows[1];assert r['realm_certainty']=='inferred' and r['identity_context']=='Realm'
    assert r['player_key']!=player_id('Opponent','Realm','observed')
    v=validate_manual(manual(realm='',realm_certainty='unknown',identity_context='RecordingRealm'))
    assert v['realm']=='' and v['player_key']!=player_id('Me','Realm','observed')


@pytest.mark.parametrize('compressed',[False,True])
def test_ai_export_keeps_all_rating_sources_manual_revisions_and_definitions(tmp_path,compressed):
    h,s=imported(tmp_path,[raw_record()]);one=save_manual(h,manual(),approved=True);save_manual(h,manual(rating=1850),one['id'],'Corrected screenshot entry',True)
    original=(h/'archive.sqlite').read_bytes();out=tmp_path/('full.json.gz' if compressed else 'full.json');export_dump(h,out)
    with (gzip.open(out,'rt',encoding='utf8') if compressed else out.open(encoding='utf8')) as f:d=json.load(f)
    assert d['database']['observations']['rows'] and d['supplemental_archive']=={}
    rated=d['rated_career'];assert len(rated['manual_revisions']['rows'])==2 and len(rated['observations']['rows'])==4
    raw=base64.b64decode(rated['sources']['rows'][0]['bytes']['base64']);assert raw==s.read_bytes()
    assert d['rated_definitions']['rank'] and any(c['summaries'] for c in d['rated_calculated']['characters'])
    assert (h/'archive.sqlite').read_bytes()==original and sqlite3.connect(h/'archive.sqlite').execute('pragma user_version').fetchone()[0]==2


def test_sync_automatically_recovers_ratings_and_unchanged_scans_are_noops(tmp_path):
    h,s=imported(tmp_path,[raw_record()]);service=DesktopService(h)
    first=service.refresh(files=[s]);second=service.refresh(files=[s]);assert first['rated_career']['added']==0 and second['skipped']==1 and second['rated_career']['added']==0


def test_no_rating_history_character_profile_is_not_someone_else(tmp_path):
    h,s=imported(tmp_path,[raw_record()]);data=model(h)
    empty=next(c for c in data['characters'] if c['character']=='Skyarrow');profile=model(h,player=empty['player_key'])
    assert profile['player']==empty['player_key'] and not profile['observations'] and not profile['summaries']


def test_conflicting_same_event_revisions_do_not_double_count_or_fabricate_current(tmp_path):
    a=raw_record();h,s=imported(tmp_path,[a]);a['Players'][0][11]=1600
    s.write_text('REFlexDatabase='+lua([a]),encoding='utf8');archive=Archive(h);archive.import_file(s,'Me','Realm');archive.close();recover(h)
    g=model(h,player=own(h)[0]['player_key'])['summaries'][0]
    assert g['games']==1 and g['conflicted_events']==1 and g['current'] is None


def test_pvp_ledger_delta_and_mmr_never_become_personal_rating(tmp_path):
    p=write_source(tmp_path/'PvPLedger.lua',[match(**{'Type':'Solo Shuffle','Rated':'Yes','Rating change':25,'MMR before':1800,'MMR after':1825})])
    a=Archive(tmp_path/'archive');a.import_file(p);a.close();recover(tmp_path/'archive');rows=observations(tmp_path/'archive')
    assert rows and rows[0]['rating'] is None and rows[0]['rating_change']==25 and rows[0]['mmr_after']==1825
