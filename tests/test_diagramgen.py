import os
import pytest
import logging
from ipaddress import ip_address

from vsdx import VisioFile

import phu.oh_diagramgen as dg

logger = logging.getLogger(__name__)


# test msu id
# test num services
# test backup if dual cpe


def get_diagram_text(filename):
    """Takes in a diagram filename, returns a list of text found in all of it's pages"""
    text = []
    with VisioFile(filename) as vis:
        for page in vis.pages:
            text.extend([shape.text.strip('\n') for shape in page.all_shapes if shape.text])
    return text


def get_ip_addrs(data):
    """Takes in a dict and returns a list of all IP address values"""
    ip_list = []
    for key, val in data.items():
        if '_ip' in key and 'sla' not in key:
            ip_list.append(val)

    return ip_list


@pytest.fixture
def html_form():
    return {
        'clli': 'TOROONKON04',
        'hospital_name': 'Sunnybrook Health Sciences Centre',
        'address': 'B-77 Browns Line, Toronto M8W 3S2'
    }


@pytest.mark.parametrize('site_type, num_pages',
                         [('single_cpe', 3),
                          ('dual_cpe', 4)])
def test_generate(html_form, site_type, num_pages):
    key_file = f'resources/keys_{site_type}.xlsx'
    out_file = 'resources/temp_diagram.vsdx'
    expected_file = f'resources/expected_{site_type}.vsdx'

    diagram = dg.OntarioHealthSrx(html_form, key_file)
    diagram.generate(out_file)
    result_text = get_diagram_text(out_file)
    expected_text = get_diagram_text(expected_file)

    with VisioFile(out_file) as vis:
        assert len(vis.pages) == num_pages
    assert len(result_text) == len(expected_text)
    assert result_text == expected_text  # Might remove this, not scalable if port mappings get changed

    os.unlink(out_file)


def test_single_cpe_vars(html_form):
    key_file = f'resources/keys_single_cpe.xlsx'
    diagram = dg.OntarioHealthSrx(html_form, key_file)
    data = diagram.data

    service_fillers = 0
    for service in data.services:
        if service.get('is_filler'):
            service_fillers += 1

    assert service_fillers == 4  # Key file only has 2 services
    assert len(data.services) == 6  # Max services set to 6 in SingleCpe
    assert data.primary
    assert not data.backup


def test_dual_cpe_vars(html_form):
    key_file = f'resources/keys_dual_cpe.xlsx'
    diagram = dg.OntarioHealthSrx(html_form, key_file)
    data = diagram.data

    assert data.primary
    assert data.backup
    assert data.backup['msu_id'][-1:] == 'B'
    assert '.70' in data.backup['site_id']

    for service in data.services:
        if not service.get('is_filler'):
            assert ':B' in service['cpe_text_backup']


def test_ip_addresses(html_form):
    key_file = f'resources/keys_dual_cpe.xlsx'
    diagram = dg.OntarioHealthSrx(html_form, key_file)
    data = diagram.data

    ip_list = []
    ip_list.extend(get_ip_addrs(data.__dict__))
    ip_list.extend(get_ip_addrs(data.primary))
    ip_list.extend(get_ip_addrs(data.backup))
    for service in diagram.data.services:
        ip_list.extend(get_ip_addrs(service))

    for ip in ip_list:
        assert ip_address(ip)


