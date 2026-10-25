import argparse
import json
from .archive import Archive, safe_destination
from .discovery import discover
from .identity import IdentityMap
from .metrics import Filters, filter_matches, character_comparison, ally_comparisons
from .export import export_folders, ai_report, copy_to_clipboard


def add_filters(parser):
    parser.add_argument('--start', help='Inclusive YYYY-MM-DD')
    parser.add_argument('--end', help='Inclusive YYYY-MM-DD')
    parser.add_argument('--character', help='Name or Name-Realm')
    parser.add_argument('--type', dest='match_type')
    parser.add_argument('--map', dest='map_name')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--premade', dest='premade', action='store_const', const=True, default=None)
    mode.add_argument('--solo', dest='premade', action='store_const', const=False)
    parser.add_argument('--ally', help='Mapped person present on own team')


def get_filters(args):
    return Filters(**{key: getattr(args, key, None) for key in Filters.__dataclass_fields__})


def main(argv=None):
    parser = argparse.ArgumentParser(description='PvP Ledger Viewer — archive, identities, analytics and exports')
    parser.add_argument('--archive-dir', help='Default: %%APPDATA%%/PvPLedgerViewer')
    sub = parser.add_subparsers(dest='command', required=True)
    imp = sub.add_parser('import'); imp.add_argument('file'); imp.add_argument('--character'); imp.add_argument('--realm'); imp.add_argument('--timezone', default='America/Los_Angeles')
    scan = sub.add_parser('scan'); scan.add_argument('wow_root'); scan.add_argument('--timezone', default='America/Los_Angeles')
    sub.add_parser('totals')
    reconcile_parser=sub.add_parser('reconcile',help='Read-only Excel audit; never commits supplemental imports')
    reconcile_parser.add_argument('workbook');reconcile_parser.add_argument('--output',required=True);reconcile_parser.add_argument('--timezone',default='America/Los_Angeles')
    sub.add_parser('sources')
    sub.add_parser('duplicates')
    decision = sub.add_parser('link'); decision.add_argument('left', type=int); decision.add_argument('right', type=int)
    decision.add_argument('--decision', choices=['confirmed', 'separate', 'unlink'], default='confirmed')
    diag = sub.add_parser('diagnostics'); diag.add_argument('--import-id', type=int)
    people = sub.add_parser('people')
    actions = people.add_subparsers(dest='action', required=True)
    actions.add_parser('list')
    assign = actions.add_parser('assign'); assign.add_argument('character'); assign.add_argument('person')
    unassign = actions.add_parser('unassign'); unassign.add_argument('character')
    remove = actions.add_parser('remove'); remove.add_argument('character')
    characters = sub.add_parser('characters'); add_filters(characters); characters.add_argument('--recent', type=int, default=20)
    allies = sub.add_parser('allies'); add_filters(allies)
    export = sub.add_parser('export'); export.add_argument('destination'); add_filters(export)
    report = sub.add_parser('report'); add_filters(report)
    report.add_argument('--limit', type=int, default=20)
    report.add_argument('--copy', action='store_true', help='Copy complete report to Windows clipboard')
    report.add_argument('--output', help='Optional UTF-8 BOM text report file')
    args = parser.parse_args(argv)
    archive = None
    try:
        if args.command=='reconcile':
            from .archive import default_home
            from .reconcile import reconcile,write_report
            result=reconcile(args.archive_dir or default_home(),args.workbook,args.timezone)
            print(json.dumps({'counts':result['counts'],'report':write_report(result,args.output)},ensure_ascii=False,indent=2));return 0
        archive = Archive(args.archive_dir)
        if args.command == 'import':
            result = archive.import_file(args.file, args.character, args.realm, args.timezone)
        elif args.command == 'scan':
            result = [archive.import_file(f, source_timezone=args.timezone) for f in discover(args.wow_root)]
        elif args.command == 'totals':
            result = archive.totals()
        elif args.command == 'sources':
            result = archive.source_totals()
        elif args.command == 'duplicates':
            result = archive.duplicate_review()
        elif args.command == 'link':
            archive.decide_link(args.left, args.right, args.decision)
            result = archive.source_totals()
        elif args.command == 'diagnostics':
            result = archive.diagnostics(args.import_id)
        else:
            identities = IdentityMap(archive.home / 'people.json')
            matches, rosters = archive.read_matches(), archive.read_rosters()
            identities.discover_unassigned(rosters)
            if args.command == 'people':
                if args.action == 'assign':
                    identities.assign(args.character, args.person)
                elif args.action == 'unassign':
                    identities.unassign(args.character)
                elif args.action == 'remove':
                    identities.remove(args.character)
                result = {'people': identities.people}
            elif args.command == 'characters':
                selected = filter_matches(matches, rosters, get_filters(args), identities)
                result = character_comparison(selected, rosters, identities, args.recent)
            elif args.command == 'allies':
                selected = filter_matches(matches, rosters, get_filters(args), identities)
                result = ally_comparisons(selected, rosters, identities)
            elif args.command == 'export':
                result = export_folders(matches, rosters, identities, args.destination, get_filters(args))
            else:
                text = ai_report(matches, rosters, identities, get_filters(args), args.limit)
                if args.output:
                    target = safe_destination(args.output)
                    if target.suffix.lower() != '.txt':
                        raise ValueError('AI report output must use a .txt extension')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text, encoding='utf-8-sig', newline='')
                if args.copy:
                    copy_to_clipboard(text)
                    result = {'copied': True, 'characters': len(text), 'output': args.output}
                else:
                    print(text, end='')
                    return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(any(r.get('status') == 'failed' for r in (result if isinstance(result, list) else [result])))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)})); return 1
    finally:
        if archive:
            archive.close()
