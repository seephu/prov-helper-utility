import os
import sys
from ipaddress import ip_address

import dotenv
import pytest
from loguru import logger

import ssh
from phu.ssh import Credentials, Device, discover_legs

logger.add('../logs/tests.log', level='DEBUG', mode='w')


# @pytest.fixture
# def valid_credentials():
#     return Credentials()
#
#
# @pytest.fixture
# def invalid_credentials():
#     return Credentials(username='Username', password='Password')
#
#
# def test_credentials(valid_credentials, invalid_credentials):
#     valid_credentials.verify()
#     invalid_credentials.verify()
#     assert invalid_credentials.valid is False
#     assert valid_credentials.valid


def test_fetch_next_pw_id(lab_asr9k):
    neighbor_host = 'Godzilla'
    pw_id = lab_asr9k.fetch_next_pw_id(neighbor_host)
    assert int(pw_id)


def test_fetch_loopback(lab_asr9k):
    lo0_ip = lab_asr9k.fetch_loopback()
    assert (ip_address(lo0_ip))


def test_show_run(lab_asr9k):
    assert lab_asr9k.show_run('policy-map') is not None
    assert lab_asr9k.show_run('interface Gig0/0/0/0.9999') is None

    output = lab_asr9k.show_run('l2vpn xconnect group GODZILLA', template='l2vpn_xconnect')
    assert isinstance(output['data'], list)
    data = output['data'][0]
    assert isinstance(data, dict)
    assert int(data['pw_id'])
    assert ip_address(data['neighbor_ip'])


def test_show_run_interface(lab_asr9k):
    assert lab_asr9k.show_run_interface('Gig1.1') is None
    assert lab_asr9k.show_run_interface('Gig0/0/0/0.9999') is None

    interface = 'TenGigE0/2/0/19.100'
    output = lab_asr9k.show_run_interface(interface)
    assert interface in output['cli']
    assert interface == output['data'][0]['interface']

    data = lab_asr9k.show_run_interface('Gig0/2/0/9.2100')['data'][0]
    assert ip_address(data['ipv4'])


@pytest.mark.parametrize('circuit_type, interface', [
    ('transparent_lan', 'Ten0/2/0/19.100'),
    ('vpls', 'Ten0/2/0/19.500'),
    ('internet', 'Gig0/2/0/9.2100'),
    (None, 'Gig1.1')
])
def test_detect_circuit_type(lab_asr9k, circuit_type, interface):
    result = lab_asr9k.detect_circuit_type(interface)
    assert result == circuit_type


@pytest.mark.parametrize('value_type, value, expected', [
    ('interface', '0/2/0/19.500', 'Case-5'),
    ('vpn_id', '6000', 'Case-6'),
    ('vpn_id', 'Gig1.1', None)
])
def test_get_bridge_domain_name(lab_asr9k, value_type, value, expected):
    result = lab_asr9k.get_bridge_domain_name(value_type, value)
    assert result == expected


@pytest.mark.parametrize('bd_name, expected', [
    ('Case-5', ['TenGigE0/2/0/19.500']),
    ('Case-123', None)
])
def test_get_bd_interfaces(lab_asr9k, bd_name, expected):
    result = lab_asr9k.get_bd_interfaces(bd_name)
    assert result == expected


@pytest.mark.parametrize('bd_name, expected', [
    ('Case-5', '5000'),
    ('Case-6', '6000'),
    ('Case-123', None)
])
def test_get_vpn_id(lab_asr9k, bd_name, expected):
    result = lab_asr9k.get_vpn_id(bd_name)
    assert result == expected


def test_discover_legs():
    hosts = ssh.discover_legs('5371')
    if hosts:
        assert isinstance(hosts, list)
        for host in hosts:
            assert isinstance(host, str)


def test_parse():
    # all device types
    pass
