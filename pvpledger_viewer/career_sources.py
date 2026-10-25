"""Conservative rated adapters. Raw evidence is kept by career.py.

REFlex 3500/3501 stores GetBattlefieldScore: slot 12 is pre-match
personal rating, 13 is rating change. Rating after = before + change,
as in Blizzard PVPMatchResultsRatingMixin.Init. TeamData MMR is never CR.
No season, build, bracket or Shuffle session outcome is guessed.
"""
from datetime import datetime, timezone
from pathlib import Path
from .lua_reader import sequence
from .reflex_reader import at, capture_time, parse_reflex, pvp_time
from .normalize import normalize
from .schema import clean
from .identity import character_key
from .player_index import uid

BRACKETS=('2v2 Arena','3v3 Arena','Solo Shuffle','Rated Battlegrounds','Battleground Blitz')


def integer(value, signed=False):
    return int(value) if isinstance(value,(int,float)) and not isinstance(value,bool) and float(value).is_integer() and (signed or value>=0) else None


def player_id(name,realm,certainty,context=''):
    return uid([*character_key(name,realm),certainty,context if certainty!='observed' else ''])


def context(path):
    p=Path(path)
    if p.parent.name=='SavedVariables' and p.parent.parent.parent.name!='Account':return p.parent.parent.name,p.parent.parent.parent.name
    return None,None


def extract(document,owner=None,realm=None,zone='America/Los_Angeles',captured=None):
    out=[];problems=[]
    if 'REFlexDatabase' in document:
        # Stable normalized match identifiers and timestamp conversion are shared
        # with the established adapter; no primary archive changes are required.
        ms,rs,aliases,issues=parse_reflex(document,owner,realm,zone)
        lookup={id(m['_raw_reflex']):(k,m) for k,m in ms.items()}
        for position,raw in enumerate(sequence(document['REFlexDatabase']),1):
            if not isinstance(raw,dict) or raw.get('isRated') is not True:continue
            if raw.get('Version') not in (3500,3501):
                problems.append({'code':'unverified_reflex_rating_schema','position':position,'version':raw.get('Version')});continue
            pair=lookup.get(id(raw))
            if pair is None:
                problems.append({'code':'unresolved_rated_record_owner','position':position});continue
            key,m=pair;players=sequence(raw.get('Players'));count=integer(raw.get('PlayersNum'))
            shuffle=raw.get('isRatedSoloShuffle') is True and raw.get('isSoloShuffle') is True
            # Complete, balanced two-team arena roster is required to distinguish
            # 2v2 from 3v3. BG roster size does not prove RBG versus Blitz.
            sides=[at(p,6) for p in players]
            bracket='Solo Shuffle' if shuffle else None
            if raw.get('isArena') is True and not raw.get('isSoloShuffle') and count in (4,6) and len(players)==count and sides.count(0)==sides.count(1)==count//2:
                bracket='2v2 Arena' if count==4 else '3v3 Arena'
            if raw.get('isArena') is False:
                if raw.get('isRatedSoloRBG') is True:bracket='Battleground Blitz'
                elif raw.get('isRatedBattleground') is True:bracket='Rated Battlegrounds'
            for index,p in enumerate(players,1):
                name,sep,world=clean(str(at(p,1) or '')).partition('-')
                if not name:continue
                own=index==raw.get('PlayerNum');world=world or key[1]
                certainty='observed' if sep or own else 'inferred'
                before=integer(at(p,12));change=integer(at(p,13),True)
                after=before+change if before is not None and change is not None and before+change>=0 else None
                result=None
                if not raw.get('isSoloShuffle') and at(p,6) in (0,1) and raw.get('Winner') in (0,1):result='W' if at(p,6)==raw['Winner'] else 'L'
                out.append({'player_key':player_id(name,world,certainty,key[1]),'character':name,'realm':world,'realm_certainty':certainty,
                    'identity_context':key[1] if certainty!='observed' else '', 'own':own,'spec':at(p,16) or None,'class':at(p,8) or None,
                    'game_version':raw.get('GameVersion') or None,'season':integer(raw.get('Season')),'bracket':bracket,
                    'observed_at':datetime.fromtimestamp(m['_timestamp_utc'],timezone.utc).isoformat() if m.get('_timestamp_utc') is not None else None,
                    'captured_at':captured,'rating':after if after is not None else before,'rating_before':before,'rating_after':after,'rating_change':change,
                    'rating_semantics':'GetBattlefieldScore pre-rating + observed delta; post-rating is arithmetic derived',
                    'mmr_before':integer(at(p,14)),'mmr_after':None,'result':result,'match_key':list(key),
                    'event_key':uid([list(key),character_key(name,world),certainty]),'source':'REFlex','source_record':position,
                    'raw':raw,'quality':['No recorded game version'] if not raw.get('GameVersion') else []})
        problems.extend({'code':'adapter_diagnostic','detail':i} for i in issues if i.get('code','').startswith(('invalid','missing','unverified')))
    elif 'PvPLedgerDB' in document:
        ms,rs,aliases,issues=normalize(document,owner,realm)
        for key,m in ms.items():
            if m.get('Rated')!='Yes':continue
            bracket={'Solo Shuffle':'Solo Shuffle','Rated Battleground':'Rated Battlegrounds','Rated Battlegrounds':'Rated Battlegrounds','Blitz':'Battleground Blitz','Battleground Blitz':'Battleground Blitz'}.get(m.get('Type'))
            out.append({'player_key':player_id(key[0],key[1],'observed'),'character':key[0],'realm':key[1],'realm_certainty':'observed','identity_context':'',
                'own':True,'spec':m.get('Spec'),'class':m.get('Class'),'game_version':None,'season':None,'bracket':bracket,
                'observed_at':datetime.fromtimestamp(m.get('Epoch') or pvp_time(m,zone),timezone.utc).isoformat() if m.get('Epoch') or pvp_time(m,zone) is not None else None,
                'captured_at':captured,'rating':None,'rating_before':None,'rating_after':None,'rating_change':integer(m.get('Rating change'),True),
                'rating_semantics':'Only rating change retained; MMR is not personal rating','mmr_before':integer(m.get('MMR before')),'mmr_after':integer(m.get('MMR after')),
                'result':None if bracket=='Solo Shuffle' else m.get('Result') if m.get('Result') in ('W','L') else None,
                'match_key':list(key),'event_key':uid([list(key),character_key(key[0],key[1]),'observed']),
                'source':'PvP Ledger','source_record':key[2],'raw':m,'quality':['Game version and season unrecorded; no personal rating']})
    return out,problems
