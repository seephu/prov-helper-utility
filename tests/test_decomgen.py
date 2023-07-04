from ipaddress import ip_address
import pytest
from loguru import logger
from phu.ssh import Device
import phu.decomgen as dg


class TestOhSrx:
    def setup(self):
        form = {
            'clei': 'REDACTED',
            'peRouter': 'REDACTED',
            'nmsVlan': '1232',
            'vpnVlan': '1233',
            'nniPortSpeed': 'Ten',
            'nniInterface': '0/1/0/6',
            'serviceVlan1': '630',
            'serviceVlan2': '631',
            'serviceVlan3': '632',
            'multithreading': 'on',
            'circuitType': 'oh_srx'
        }
        self.circuit = dg.DecomGen().generator(form)
        with open(f'resources/expected_oh_srx_decom.txt') as f:
            self.expected = f.read()

    def test_rollback_edge(self):
        configs = self.circuit._rollback_edge()
        assert configs
        assert self.circuit.warnings == 0
        assert configs in self.expected

    def test_rollback_vpn_conc(self):
        configs = self.circuit._rollback_vpn_conc()
        assert configs
        assert self.circuit.warnings == 0
        assert configs in self.expected

    def test_rollback_core(self):
        configs = self.circuit._rollback_core()
        assert configs
        assert self.circuit.warnings == 0
        assert configs in self.expected


class TestVpls:
    def setup(self):
        form = {
            'router': 'REDACTED',
            'portSpeed': 'Ten',
            'interface': '0/2/0/19',
            'vlan': '500',
            'circuitType': 'vpls'
        }
        self.circuit = dg.DecomGen().generator(form)
        with open(f'resources/expected_vpls_decom.txt') as f:
            self.expected = f.read()

    def test_fetch_rollback(self, lab_asr9k):
        self.circuit.fetch_rollbacks(lab_asr9k)
        assert self.circuit.configs == self.expected

    def test_get_circuit_info(self, lab_asr9k):
        assert self.circuit._get_circuit_info(lab_asr9k)
        assert isinstance(self.circuit.form['bd_name'], str)
        assert int(self.circuit.form['vpn_id'])

    @pytest.mark.parametrize('bd_name', ['BD_NAME', 'Case-5'])
    def test_rollback_leg(self, lab_asr9k, bd_name):
        self.circuit.form.update({
            'bd_name': bd_name,
            'vpn_id': '5000'
        })
        self.circuit._rollback_leg(lab_asr9k)
        rollback = ''.join(self.circuit.form['legs'][0]['rollback'])
        assert 'Case-5' in rollback and self.circuit.form['vpn_id'] in rollback


@pytest.mark.usefixtures()
class TestInternet:

    @pytest.fixture(autouse=True)
    def setup(self, lab_asr9k, isis1_decom):
        self.circuit = dg.DecomGen().generator(isis1_decom)
        self.circuit.device = lab_asr9k
        with open(f'resources/expected_isis1_decom.txt') as f:
            self.expected = f.read()

    def test_rollback_interface(self):
        assert self.circuit._rollback_interface()
        self.circuit.form['rollback'] = self.circuit.rollback.make()
        self.circuit.generate()

        assert ip_address(self.circuit.form['neighbor_ip'])
        assert self.circuit.form['rollback']
        assert self.circuit.form['rollback'] in self.expected

    def test_rollback_isis(self):
        self.circuit.form['full_interface'] = f"{self.circuit.form['port_speed']}{self.circuit.form['interface']}.{self.circuit.form['vlan']}"
        self.circuit.form['neighbor_ip'] = '10.11.13.4'
        assert self.circuit._rollback_isis()

        self.circuit.form['rollback'] = self.circuit.rollback.make()
        self.circuit.generate()
        assert self.circuit.form['rollback']
        assert self.circuit.form['rollback'] in self.expected

    # def test_rollback_bgp(self):
    #     TODO: add test
    #     pass

    def test_rollback_bgp_error(self):
        self.circuit.form['neighbor_ip'] = '60.60.60.1'
        result = self.circuit._rollback_bgp()
        assert not result

    def test_fetch_rollbacks(self):
        self.circuit.fetch_rollbacks(self.circuit.device)
        assert self.circuit.configs == self.expected

    def test_fetch_rollbacks_bgp(self, bgp1_decom):
        circuit = dg.DecomGen().generator(bgp1_decom)
        circuit.fetch_rollbacks()
        with open(f'resources/expected_bgp1_decom.txt') as f:
            expected = f.read()
        assert circuit.configs == expected


class TestTransparentLan:

    @pytest.fixture(autouse=True)
    def setup(self, transparent_lan1_decom):
        self.circuit = dg.DecomGen().generator(transparent_lan1_decom)
        with open(f'resources/expected_transparent_lan1_decom.txt') as f:
            self.expected = f.read()

    def test_rollback_router_a(self, lab_asr9k):
        self.circuit._rollback_router_a(lab_asr9k)
        self.circuit.generate()
        assert self.circuit.form['interface_a'] in self.expected
        assert self.circuit.form['p2p_name_a'] in self.expected

    def test_rollback_router_z(self):
        self.circuit.form.update({
            'pw_id': '2',
            'router_a': 'REDACTED',
            'router_z': 'REDACTED'
        })
        self.circuit._rollback_router_z()
        self.circuit.generate()
        assert self.circuit.form['interface_z'] in self.expected
        assert self.circuit.form['p2p_name_z'] in self.expected

    def test_fetch_rollbacks(self):
        self.circuit.fetch_rollbacks()
        assert self.circuit.configs == self.expected


class TestRollback:
    def test_warnings(self, lab_asr9k):
        # Ensure we're getting warnings when passing a Rollback class
        rollback = dg.Rollback()
        child_rollback = dg.Rollback()
        rollback.add(lab_asr9k.show('version brief'))
        assert rollback.warnings == 0
        child_rollback.add(lab_asr9k.show_run('interface Gig1.1'))
        child_rollback.add(lab_asr9k.show_run('interface Gig1.2'))
        rollback.add(child_rollback)
        rollback.make()
        assert rollback.warnings == child_rollback.warnings




# @pytest.mark.parametrize('form', ['transparent_lan1_decom', 'isis1_decom', 'bgp1_decom'])
# def test_fetch_rollback(form, request):
#     circuit = dg.DecomGen().generator(request.getfixturevalue(form))
#     circuit.fetch_rollbacks()
#     with open(f'resources/expected_{form}.txt') as f:
#         expected = f.read()
#     assert circuit.configs == expected


def test_rollback():
    pass

def test_autodetect(isis1_decom):
    isis1_decom['circuitType'] = 'autodetect'
    circuit = dg.DecomGen().generator(isis1_decom)
    with open(f'resources/expected_isis1_decom.txt') as f:
        expected = f.read()
    assert circuit.configs == expected
