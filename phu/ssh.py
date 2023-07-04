# -*- coding: utf-8 -*-
"""
Created on Tue Jan 25 22:11:52 2022

@author: 210018
"""
import time

import itsdangerous.exc
import sys
import re
import os
import logging
import ipaddress
from contextlib import ExitStack

import dotenv
from itsdangerous import URLSafeSerializer
from loguru import logger
from ttp import ttp
from netmiko import ConnectHandler, redispatch, NetmikoTimeoutException, NetmikoAuthenticationException, exceptions
from dataclasses import dataclass

from database import COMMERCIAL_DB

# Environment variables
dotenv.load_dotenv()
GATEWAY_IP = os.getenv('GATEWAY_IP')
SSH_USER = os.getenv('SSH_USER')
SSH_PASS = os.getenv('SSH_PASS')

class SSHConnection:
    def __init__(self, gateway_creds=None):
        """Creates an abstraction of a Netmiko ConnectHandler object with full SSH functionality.

        Args:
            hostname (str): Hostname of the device
            gateway_creds (Credentials): A Credentials object to authenticate the gateway connection
            device_type (str): Device type e.g. juniper_junos, linux, etc. - see Netmiko docs
        """
        self.gateway_creds = gateway_creds if gateway_creds else Credentials()
        self.ssh_creds = Credentials(username=SSH_USER, password=SSH_PASS)
        self.ssh_creds.deserialized()
        self.connection = None

    def connect_host(self, hostname, device_type):
        """Returns a valid Netmiko SSH connection"""
        # Establish gateway connection
        net_connect = self.connect_gateway(self.gateway_creds)
        if not net_connect:
            logger.error('No gateway connection. Verify credentials for {}', self.gateway_creds.username)
            return

        # With a valid gateway connection, attempt SSH connection to the host
        logger.info(f'Connecting to: {hostname}')
        net_connect.write_channel(f'ssh {self.ssh_creds.username}@{hostname}\n')
        time.sleep(3)
        output = net_connect.read_channel()

        # If first time connecting to the host, bypass authenticity check
        if 'RSA' in output or 'fingerprint' in output:
            logger.info('Bypassing authenticity check (first time connecting to host).')
            net_connect.write_channel('yes\r\n')
            time.sleep(1)

        # Password prompt
        max_attempts = 3
        for i in range(max_attempts):
            net_connect.write_channel(self.ssh_creds.password + '\r\n')
            time.sleep(2)
            output = net_connect.read_channel()
            if '>' in output or '#' in output:
                break

            # i starts at 0
            if i == max_attempts - 1:
                logger.error("""Error connecting to the device.. possible causes:\n
                    1) SSH credentials in the .env file are invalid.
                    2) The device can't be connected to. Check if you can you connect manually.
                    """)
                return

        # Connection successful
        try:
            redispatch(net_connect, device_type=device_type)
        except exceptions.ReadTimeout:
            logger.exception('Timed out during connection.')
        else:
            if hostname in net_connect.find_prompt().upper() or self.ssh_creds.username in net_connect.find_prompt():
                logger.success(f"Successfully connected to {hostname}")
                logger.info(net_connect.find_prompt())
                self.connection = net_connect
                return net_connect

        logger.error('Exiting.. could not establish a connection to: {}', hostname)
        net_connect.disconnect()
        return

    def connect_gateway(self, gateway_creds):
        """Returns a Netmiko connection to the jump host"""
        gateway_creds.deserialized()
        gateway = {
            'device_type': 'linux',
            'host': GATEWAY_IP,
            'username': gateway_creds.username,
            'password': gateway_creds.password
        }
        try:
            logger.info('Connecting to {} as {}', gateway['host'], gateway_creds.username)
            net_connect = ConnectHandler(**gateway)
            logger.success('Gateway connection established')
            return net_connect
        except NetmikoTimeoutException:
            logger.error("Gateway connection timed out. Are you connected to the Hydro One VPN?")
        except NetmikoAuthenticationException:
            logger.error('Invalid credentials for user {}', gateway_creds.username)

class Device:
    def __init__(self, hostname, device_type='cisco_xr'):
        """Creates an abstraction of a Netmiko ConnectHandler object with full SSH functionality.

        Args:
            hostname (str): Hostname of the device
            gateway_creds (Credentials): A Credentials object to authenticate the gateway connection
            device_type (str): Device type e.g. juniper_junos, linux, etc. - see Netmiko docs
        """
        self.hostname = hostname.upper()
        self.device_type = device_type
        self.connection = None

    def connect(self):
        conn = SSHConnection()
        return conn.connect_host(self.hostname, self.device_type)

    def detect_circuit_type(self, full_intf):
        """Using an active Device connection, runs show commands to try and detect the circuit type"""
        output = self.show_run_interface(full_intf)
        if output is None:
            logger.error("Interface {} doesn't exist", full_intf)
            return

        interface_data = output['data'][0]
        if interface_data.get('ipv4'):
            return 'internet'

        output = self.show_run(f"formal l2vpn | i {interface_data['interface']}")
        if 'bridge group' in output:
            return 'vpls'

        if 'xconnect group' in output:
            # TODO: add check for Local-Switch l2vpns
            return 'transparent_lan'

        logger.error('Unable to detect circuit type')

    def fetch_next_pw_id(self, neighbor):
        """Takes in a neighbor hostname and returns the lowest available pseudowire ID"""
        logger.info('Fetching next available pseudowire ID to: {}', neighbor)
        output = self.show_run(f"l2vpn xconnect group {neighbor.upper()}")

        psw_id_re = r'(pw-id)\s(\d{1,2})'
        pattern = re.compile(psw_id_re)
        matches = pattern.finditer(str(output))

        psw_id_list = [match.group(2) for match in matches]
        logger.info('Pseudowire IDs found: {}', psw_id_list)
        i = 1
        while True:
            if str(i) not in psw_id_list:
                return str(i)
            i += 1

    def fetch_loopback(self):
        """Returns the lo0 IP of the host"""
        logger.info('Fetching lo0 IP of {}', self.hostname)
        tmp = " ipv4 address {{ ip_addr }} {{ mask }}"
        output = self.connection.send_command(f"show run int lo0", use_ttp=True, ttp_template=tmp)[0][0]
        result = output['ip_addr']
        logger.success('Found IP address: {}', self.hostname)
        return result

    def get_bridge_domain_name(self, value_type, value):
        """Using either the interface or VPN ID, returns a dict of the bridge-domain info

        Args:
            value_type: either the full interface (port speed not necessary) or VPN ID
            value: value of the value type

        Returns:
            string: bridge-domain name
        """
        templates = {
            'interface': "{{ _ | PHRASE }} bridge-domain {{ bd_name }} interface {{ interface }}",
            'vpn_id': '{{ _ | PHRASE }} bridge-domain {{ bd_name }} {{ __ | PHRASE }}',
        }
        commands = {
            'interface': f"formal l2vpn | i {value}",
            'vpn_id': f'formal l2vpn | i vpn-id | i {value}',
        }
        output = self.show_run(commands[value_type], templates[value_type])
        if output is None:
            logger.warning('No bridge-domain configured with {} {}', value_type, value)
            return
        logger.success('Discovered bridge-domain: {}', output['data'][0]['bd_name'])
        return output['data'][0]['bd_name']

    def get_bd_interfaces(self, bd_name):
        """Takes in a bridge-domain name and returns a list of interfaces configured on it"""
        tmp = '{{ _ | PHRASE }} interface {{ interface }}'
        output = self.show_run(f'formal l2vpn | i {bd_name}', template=tmp)
        if output:
            return [intf['interface'] for intf in output['data']]

    def get_vpn_id(self, bd_name):
        """Takes in a bridge-domain name and returns a VPN ID"""
        tmp = '{{ _ | PHRASE }} 19752:{{ vpn_id }}'
        output = self.show_run(f"formal l2vpn | i {bd_name} | i 19752", template=tmp)
        if not output:
            return

        vpn_id = output['data'][0]['vpn_id']
        logger.success('Discovered VPN ID: {}', vpn_id)
        return vpn_id

    def show(self, command, template=''):
        """Runs show commands and returns the ouput

        Args:
            command (str): command after "show"
            template (str): a TTP template to parse the output through

        Returns:
            Returns a string of the command's CLI output if found, otherwise None.
        """
        conn = self.connection

        # Get command and store output
        command = f"show {command}"
        output = conn.send_command(command)
        logger.info('{}: {}', conn.find_prompt(), command)
        logger.debug('{}:\n{}', conn.find_prompt(), output)

        if not self._is_valid_output(output):
            return

        if template:
            return {'cli': output, 'data': self.parse(output, template)}

        return output

    def show_run(self, command, template='', strip_lines=0, read_timeout=10):
        """Removes the date of show run commands and optionally parses it with ttp

        Args:
            command (str): command after "show running-config"
            template (str): a TTP template to parse the output through
            strip_lines (int): number of lines to strip at beginning of output
            read_timeout (int):  override send_command's default timeout of 10 seconds

        Returns:
            any: a string of the command's CLI output if no template is provided.
            Otherwise, returns a dict with the rollback ('cli') and parsed data ('data')
        """
        conn = self.connection

        # Get command and store output
        command = f"show running-config {command}"
        output = conn.send_command(command, read_timeout=read_timeout)
        logger.info('{}: {}', conn.find_prompt(), command)
        logger.debug('{}:\n{}', conn.find_prompt(), output)

        # Remove header lines from CLI output
        output = self._strip_lines(output, strip_lines)
        if output is None:
            return

        # Parse output through a template if provided
        if template:
            return {'cli': output, 'data': self.parse(output, template)}
        return output

    def show_run_interface(self, interface, strip_lines=0):
        """Returns a dict of the output's CLI and interface data"""
        return self.show_run(command=f'interface {interface}', template='interface', strip_lines=strip_lines)

    def show_run_l2vpn_xconnect(self, interface, strip_lines=0):
        pass

    def show_configuration(self, command, template=''):
        """Runs show configuration commands on Juniper devices
        Args:
            command (str): command after "show configuration | display set"
            template (str): a TTP template to parse the output through
        """
        conn = self.connection

        command = f"show configuration | display set | {command}"
        output = conn.send_command(command)
        logger.info('{}: {}', conn.find_prompt(), command)
        logger.debug('{}:\n{}', conn.find_prompt(), output)

        return output

    def parse(self, output, template, structure='flat_list'):
        """Parses an output with a ttp template

        Args:
            output (str): CLI output
            template (str): either a key that maps to the filename of a TTP template, or a direct string template
            structure (str): TTP parameter used to format the output hierarchy (see TTP docs for options)

        Returns:
            a list of dicts (if the default 'structure' param is kept)
        """
        # TODO: add template_file variable
        templates = {
            'interface': '../assets/templates/show_run_interface.txt',
            'l2vpn_xconnect': '../assets/templates/l2vpn_xconnect.txt'
        }
        if templates.get(template):
            tmp = templates[template]
            logger.debug('Parsing with template from file: {}', tmp)
        else:
            tmp = template
            logger.debug('Parsing with string template: {}', tmp)

        parser = ttp(output, tmp)
        parser.parse()
        result = parser.result(structure=structure)
        logger.debug('Parsed result: {}', result)
        return result

    def _strip_lines(self, output, to_strip):
        """Strips header lines from the CLI output"""
        if self.device_type == 'cisco_xr':
            to_strip = 2

        if to_strip:
            output = '\n'.join(output.split('\n')[to_strip:])

        if self._is_valid_output(output):
            return output

    @staticmethod
    def _is_valid_output(output):
        """Checks for invalid or empty text"""
        invalid_text = ['Invalid', 'No such', 'not found']
        if any(text in output for text in invalid_text) or not output:
            logger.warning("No configurations returned.")
            return
        return True


@dataclass
class Credentials(Device):
    username: str = ''
    password: str = ''
    valid: bool = False

    def __post_init__(self):
        """Load the credentials from .env if manual credentials aren't provided"""
        if not self.username and not self.password:
            self.username = os.getenv('GATEWAY_USER')
            self.password = os.getenv('GATEWAY_PASS')

    def verify(self):
        """Returns True if gateway credentials are authenticated"""
        connection = self.connect_gateway(self)
        if connection:
            connection.disconnect()
            self.valid = True
            return True

    def save(self):
        """Saves credentials to the .env file and replaces existing environment variables"""
        logger.debug('Overwriting credentials with {}', self.username)
        dotenv.set_key('.env', 'GATEWAY_USER', self.username)
        dotenv.set_key('.env', 'GATEWAY_PASS', self._serialize(self.password))
        os.environ['GATEWAY_USER'] = self.username
        os.environ['GATEWAY_PASS'] = self._serialize(self.password)
        dotenv.load_dotenv()
        logger.success('Credentials for {} saved', os.getenv('GATEWAY_USER'))

    def deserialized(self):
        """Decrypts the username and password"""
        self.username = self._deserialize(self.username)
        self.password = self._deserialize(self.password)

    def _deserialize(self, text):
        """Un-obfuscates a string (not actual encryption)"""
        key = URLSafeSerializer('GhHC4q1gj4')
        try:
            return key.loads(text)
        except itsdangerous.exc.BadSignature:
            return text

    def _serialize(self, text):
        """Obfuscates a string (not actual encryption)"""
        key = URLSafeSerializer('GhHC4q1gj4')
        return key.dumps(text)


def discover_legs(vpn_id):
    """Checks the route reflector for any hosts using a VPN ID

    Args:
        vpn_id (str): a VPLS VPN ID

    Returns:
         a list of hostnames
    """
    device = Device('EBCKONCBVRR01')
    with device.connect():
        tmp = 'Route Distinguisher: {{ ip_addr }}:{{ ignore }}'
        output = device.show(f'bgp l2vpn vpls all | i {vpn_id}', template=tmp)

    if output is None:
        logger.warning('No route distinguishers found with VPN ID {}', vpn_id)
        return

    hostnames = []
    for ip in [data['ip_addr'] for data in output['data']]:
        if COMMERCIAL_DB.get_hostname(ip) is None:
            logger.warning("Found IP {} but there's no matching hostname in the database", ip)
        else:
            hostnames.append(COMMERCIAL_DB.get_hostname(ip))
    logger.success('Discovered ({}) VPLS legs: {}', len(hostnames), list(hostnames))
    return hostnames



@logger.catch
def main():
    pass

if __name__ == "__main__":
    main()
