import os
import pytest

from loguru import logger
from vsdx import VisioFile

import phu.configgen as cg


class TestOhConfigGen:
    def get_expected_configs(self, folder):
        files = os.listdir(folder)
        configs = {}
        for file in files:
            with open(f"{folder}/{file}", 'r') as f:
                configs.update({file: f.read()})
        return configs

    def test_generate_single(self, oh_srx):
        expected = self.get_expected_configs('resources/expected_oh_srx_single')
        site = cg.ConfigGen().generator(oh_srx)
        configs = site.generate_site_configs()
        for fname, config in configs.items():
            assert config == expected[fname]

    def test_generate_dual(self):
        expected = self.get_expected_configs('resources/expected_oh_srx_dual')
        vars_file = 'resources/vars_oh_srx_dual.xlsx'
        site = cg.ConfigGen().generator(cg.VarsFile().load(vars_file))
        configs = site.generate_site_configs()
        for fname, config in configs.items():
            assert config == expected[fname]


class TestVarsFile:
    def setup(self):
        self.vars_file = cg.VarsFile()

    def test_vars_file_load(self, oh_srx):
        # Loaded vars_file should be exact same as HTML form
        basegen = cg.BaseGenerator(oh_srx)
        parsed_form = basegen.form
        vars_file_data = self.vars_file.load('resources/oh_srx_vars.xlsx')
        assert vars_file_data == parsed_form

    def test_vars_file_load_legacy(self, oh_srx):
        basegen = cg.BaseGenerator(oh_srx)
        parsed_form = basegen.form
        vars_file_data = self.vars_file.load_legacy('resources/keys_single_cpe.xlsx')
        vars_file_data['circuit_type'] = 'single'
        min_fields = 30
        assert len(vars_file_data.keys()) > min_fields
        for k, v in parsed_form.items():
            assert k in vars_file_data


@pytest.mark.parametrize('form', [
    'bgp1',
    'bgp2',
    'isis1',
    'isis2',
    'transparent_lan1',
    'layer2_test',
    'raisecom1',
    'raisecom2',
])
def test_generate_configs(form, request):
    """Test config generator"""
    circuit = request.getfixturevalue(form)
    logger.debug("Testing form: {} with context: {}", form, circuit.form)
    with open(f"resources/expected_{form}.txt") as f:
        expected = f.read()
    assert circuit.configs == expected


@pytest.mark.parametrize('form', ['bgp1', 'bgp2', 'isis1', 'isis2', 'transparent_lan1'])
def test_generate_diagram(form, request):
    circuit = request.getfixturevalue(form)
    temp_diagram = f'output/temp.vsdx'
    circuit.generate_diagram(temp_diagram)

    with VisioFile(f'resources/expected_{form}.vsdx') as vis:
        expected = [shape.text for shape in vis.pages[0].all_shapes if shape.text]

    with VisioFile(temp_diagram) as vis:
        result = [shape.text for shape in vis.pages[0].all_shapes if shape.text]
        assert len(vis.pages) == 1
        assert vis.pages[0].name == 'Overview Drawing'

    assert result == expected
    os.unlink(temp_diagram)
    assert not os.path.exists(temp_diagram)


def test_layer2_rng():
    """Test pseudowire & VLAN IDs get generated if not provided"""
    l2_form = {
        'circuitId': '02-LMXP-0000321-HYR-000',
        'router': 'UTOPONADPED30',
        'portSpeed': 'Ten',
        'interface': '0/5/0/2',
        'vlan': '',
        'bandwidth': '1000'
    }
    l2_configs = cg.Layer2Test(l2_form)

    assert int(l2_configs.form['vlan'])
    assert l2_configs.form['full_interface'].split('.')[1] == l2_configs.form['vlan']

