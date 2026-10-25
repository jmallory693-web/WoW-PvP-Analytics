"""Generic first-run and preservation regressions, using fictional local data."""
import ast
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import pytest
from pvpledger_viewer import identity, setup
from pvpledger_viewer.identity import IdentityMap
from pvpledger_viewer.settings import SettingsStore, validate_settings
from pvpledger_viewer.service import DesktopService


@pytest.fixture(autouse=True)
def empty_defaults(monkeypatch):
    monkeypatch.setattr(identity,'SEED',{'Me':[],'Unassigned':[]})


def test_production_seed_is_empty():
    tree=ast.parse(Path(identity.__file__).read_text(encoding='utf8'))
    seed=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SEED' for t in n.targets))
    assert seed=={'Me':[],'Unassigned':[]}


def test_fresh_empty_archive_without_sample_people(tmp_path):
    home=tmp_path/'Private profile'
    assert not setup.existing_profile(home)
    setup.configure(home)
    ids=IdentityMap(home/'people.json');assert ids.people=={'Me':[],'Unassigned':[]}
    payload=DesktopService(home).snapshot()
    assert payload['history_count']==0 and not payload['catalogue'] and payload['owner_person']=='Me'
    assert payload['totals']['total']==0
    db=sqlite3.connect(home/'archive.sqlite');assert db.execute('pragma user_version').fetchone()[0]==2;db.close()


def test_own_friend_unicode_and_private_settings(tmp_path):
    home=tmp_path/'Profile é with spaces'
    setup.configure(home,display_name='Optional nickname',own=['Fayë-Example Realm'],friends=[('Teammate','Môônlet-Other Realm')],interval=600,sync_enabled=False)
    ids=IdentityMap(home/'people.json')
    assert ids.resolve('Fayë','ExampleRealm')==ids.owner_person=='Me'
    assert ids.resolve('Môônlet','Other Realm')=='Teammate'
    settings=SettingsStore(home/'settings.json').load()
    assert settings['sync_interval']==600 and not settings['sync_enabled'] and settings['source_timezone']=='UTC'


@pytest.mark.parametrize('changes',[
    {'interval':0},{'interval':True},{'zone':'Invalid/Zone'},
    {'own':['NoRealm']},{'own':['Same-Realm'],'friends':[('Friend','Same-Realm')]},
    {'friends':[('Me','Other-Realm')]},{'sources':['unavailable.lua']}])
def test_invalid_setup_is_validated_before_writes(tmp_path,changes):
    home=tmp_path/'new-profile'
    with pytest.raises((ValueError,OSError)):setup.configure(home,**changes)
    assert not home.exists()


@pytest.mark.parametrize('filename',['people.json','settings.json','archive.sqlite'])
def test_existing_profile_cannot_be_overwritten(tmp_path,filename):
    home=tmp_path/'existing';home.mkdir();p=home/filename;p.write_bytes(b'preserve exactly')
    before=p.read_bytes();assert setup.existing_profile(home)
    with pytest.raises(ValueError,match='existing profile'):setup.configure(home)
    assert p.read_bytes()==before and list(home.iterdir())==[p]


def test_legacy_owner_ids_labels_and_mappings_not_rewritten(tmp_path):
    path=tmp_path/'people.json'
    document={'version':2,'people':{'Owner ID':['Asterknight-ExampleRealm'],'Friend ID':['Pebblebrew-Other'],'Unassigned':[]},
              'profiles':{'Owner ID':{'display_name':'Local owner','nickname':'Alias'}}}
    path.write_text(json.dumps(document),encoding='utf8');before=path.read_bytes()
    ids=IdentityMap(path)
    from pvpledger_viewer.player_index import read_identities
    for value in (ids,read_identities(tmp_path)):
        assert value.owner_person=='Owner ID' and value.people==document['people']
        assert value.resolve('Asterknight','ExampleRealm')=='Owner ID'
        assert value.label('Owner ID')=='Local owner (Alias)'
    assert path.read_bytes()==before


def test_explicit_owner_does_not_depend_on_dictionary_order(tmp_path):
    path=tmp_path/'people.json';path.write_text(json.dumps({'people':{'Friend':[],'Owner':[],'Unassigned':[]},'owner_person':'Owner'}))
    assert IdentityMap(path).owner_person=='Owner'


def test_fresh_custom_archive_pointer_creates_private_parent(tmp_path,monkeypatch):
    from pvpledger_viewer.archive import set_default_home, default_home
    monkeypatch.setenv('APPDATA',str(tmp_path/'New roaming directory'))
    chosen=tmp_path/'Chosen archive';setup.configure(chosen)
    set_default_home(chosen)
    assert default_home()==chosen.resolve()
    pointer=tmp_path/'New roaming directory/PvPLedgerViewer/archive-location.json'
    assert json.loads(pointer.read_text())['path']==str(chosen.resolve())


def test_source_selection_and_discovery_ignore_backups(tmp_path,monkeypatch):
    install=tmp_path/'Games é with spaces'/'World of Warcraft'
    directory=install/'_retail_/WTF/Account/Test Account/Example Realm/Asterknight/SavedVariables'
    directory.mkdir(parents=True)
    from test_core import write_source
    p=write_source(directory/'PvPLedger.lua');(directory/'PvPLedger.lua.bak').write_text('ignored')
    before=hashlib.sha256(p.read_bytes()).hexdigest()
    monkeypatch.setenv('ProgramFiles',str(install.parent))
    assert install in setup.installation_candidates()
    assert setup.locations(install)==[p.resolve()]
    assert setup.locations(directory)==[p.resolve()]
    assert setup.discovered_characters([p])==['Asterknight-Example Realm']
    assert setup.selected_sources([directory,p])==[p.resolve()]
    home=tmp_path/'profile';setup.configure(home,sources=[str(p)])
    service=DesktopService(home);assert service.refresh()['files']==1
    assert service.refresh()['skipped']==1
    assert hashlib.sha256(p.read_bytes()).hexdigest()==before


def test_missing_installation_and_no_addon_messages(tmp_path):
    with pytest.raises(ValueError,match='existing WoW'):setup.locations(tmp_path/'missing')
    assert setup.locations(tmp_path)==[]
    with pytest.raises(ValueError,match='SavedVariables'):setup.selected_sources([tmp_path/'missing.lua'])


@pytest.mark.parametrize('value',[False,None,'300',29,True])
def test_sync_interval_validation(value):
    with pytest.raises(ValueError):validate_settings({'sync_interval':value})


@pytest.mark.parametrize('compressed',[False,True])
def test_explicit_ai_export_preserves_local_names_and_raw_data(tmp_path,compressed):
    from test_core import write_source,match,roster
    from pvpledger_viewer.full_export import export_dump
    source=write_source(tmp_path/'source.lua',[match(character='Fayë',realm='Example Realm')],[roster(player='Fayë',realm='Example Realm',**{'Is me':'Yes'})])
    home=tmp_path/'profile';setup.configure(home,own=['Fayë-Example Realm'])
    service=DesktopService(home);service.refresh(files=[source])
    path=tmp_path/('full.json.gz' if compressed else 'full.json');export_dump(home,path)
    with (gzip.open if compressed else open)(path,'rt',encoding='utf8') as f:document=json.load(f)
    encoded=json.dumps(document,ensure_ascii=False)
    assert 'Fayë' in encoded and 'Example Realm' in encoded and 'matchCSV' in encoded
    assert service.snapshot()['history_count']==1


def test_setup_window_controls_fit_1280_desktop(tmp_path):
    import tkinter as tk
    from pvpledger_viewer.ui.app import LedgerApp
    from pvpledger_viewer.ui.setup import SetupDialog
    root=tk.Tk();app=LedgerApp(root,tmp_path/'fresh',autostart=False)
    root.geometry('1280x720');root.update()
    dialog=SetupDialog(app)
    try:
        root.update()
        assert dialog.winfo_width()==900 and dialog.winfo_height()==600
        assert dialog.variables['display_name'].get()==''
        assert dialog.sync.get() and dialog.variables['interval'].get()=='300'
        buttons=[]
        def walk(widget):
            for child in widget.winfo_children():
                if child.winfo_class()=='TButton':buttons.append(child)
                walk(child)
        walk(dialog)
        start=next(b for b in buttons if b.cget('text')=='Start')
        assert start.winfo_viewable() and start.winfo_rooty()+start.winfo_height()<=dialog.winfo_rooty()+dialog.winfo_height()
        dialog.book.select(1);root.update()
        dialog.people_scroll.canvas.yview_moveto(1);root.update()
        remove=next(b for b in buttons if b.cget('text')=='Remove selected association')
        canvas=dialog.people_scroll.canvas
        assert remove.winfo_height()>=25
        assert canvas.winfo_rooty()<=remove.winfo_rooty()
        assert remove.winfo_rooty()+remove.winfo_height()<=canvas.winfo_rooty()+canvas.winfo_height()
        source=tmp_path/'Game/WTF/Account/Example Account/Example Realm/Examplehero/SavedVariables/PvPLedger.lua'
        source.parent.mkdir(parents=True);source.write_text('PvPLedgerDB={}')
        dialog.variables['wow_root'].set(str(tmp_path/'Game'));dialog.find()
        assert dialog.sources.get(0)=='PvPLedger.lua — Example Account / Example Realm / Examplehero / SavedVariables'
        dialog.sources.selection_set(0);dialog.choose_sources()
        assert dialog.paths==[str(source.resolve())]
    finally:
        dialog.destroy();app.tasks.close();root.destroy()
