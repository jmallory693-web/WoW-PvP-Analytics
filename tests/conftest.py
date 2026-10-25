"""Synthetic comparison profile used only by the legacy regression scenarios.

Fresh-install tests opt out: production defaults contain no sample identities.
"""
import pytest


@pytest.fixture(scope='session',autouse=True)
def fictional_profile():
    from pvpledger_viewer import identity
    original = identity.SEED
    identity.SEED = {
        'Me':['Asterknight','Mossweaver','Dawnstalker','Skyarrow','Mistwalker'],
        'Buddy A':['Emberguard','Emberblade','Emberward'],
        'Buddy B':['Pebblebrew','Thornpaw'],
        'Buddy C':['Snowflare','Raincaller'],
        'Buddy D':[], 'Unassigned':['Unboundleaf']}
    yield
    identity.SEED = original
