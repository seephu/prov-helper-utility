import pytest
import database as db

from ipaddress import ip_address


@pytest.fixture(scope='session')
def database():
    return db.Database()


def test_database(database):
    db_loaded = 0
    for value in vars(database).values():
        if isinstance(value, dict):
            db_loaded += 1
    num_sheets = dict(vars(database))
    num_sheets.pop('db_file')
    assert len(num_sheets) >= 1
    assert db_loaded == len(num_sheets)


def test_asr9k_routers(database):
    asr9k_routers = database.asr9k_routers
    pop_clli_list = database.get_all('pop_sites')
    ip_addrs = []

    for router, val in asr9k_routers.items():
        ip_addrs.append(val['lo0_ip'])
        assert val['clli'] in pop_clli_list, f"{val['clli']} not found in POP site db"
        assert database.get_hostname(val['lo0_ip']) == router
        assert ip_address(val['lo0_ip'])
    assert len(set(ip_addrs)) == len(ip_addrs)  # Checks for duplicate IPs


def test_raisecoms(database):
    raisecoms = database.raisecoms
    for raisecom, values in raisecoms.items():
        assert isinstance(values['uplink_ports'], list)
        assert isinstance(values['client_ports'], list)
        assert '.txt' in values['template']

