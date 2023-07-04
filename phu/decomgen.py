import sys
import ssh
import os
from dataclasses import dataclass
from ipaddress import ip_address
from contextlib import ExitStack

import concurrent.futures as cf

import ssh
import configgen as cg
import database
from jinja2 import Template
from loguru import logger

COMMERCIAL_DB = database.COMMERCIAL_DB
OH_DATABASE = database.OH_DB


class Rollback:
    def __init__(self, parent=''):
        """
        Args:
            parent (str): a top-level parent line for show commands without one (e.g. service instances, VRFs)
        """
        self.rollback = [parent + '\n'] if parent else []
        self.warnings = 0

    def add(self, output, newlines=0):
        """Appends a string output to the rollback list

        Args:
            output (Any): takes in CLI output in the form of a string, list of strings, or Rollback object
            newlines (int): number of new line spacers to add after the output
        """
        line_spacer = ''
        if newlines:
            line_spacer = '\n!\n' * newlines

        if not output:
            self.warnings += 1
            return

        if isinstance(output, list):
            output = self._filter(output)
        elif isinstance(output, Rollback):
            self.warnings += output.warnings
            output = output.make()

        output += line_spacer
        self.rollback.append(output)

    def make(self, newlines=0):
        """Joins a list of rollback strings

        Args:
            newlines (int): number of new line spacers to add between each string
        """
        line_spacer = ''
        if newlines:
            line_spacer = '!\n' * newlines
        return line_spacer.join(self.rollback)

    def _filter(self, output):
        """Takes in a list of strings, filters out NoneTypes and returns a joined string"""
        errors = len([e for e in output if not e])
        if errors:
            self.warnings += errors
        return ''.join(filter(None, output))

    def warn(self):
        if self.warnings:
            logger.warning('WARNING: # of missing configs: ({}) ... see logs for further details', self.warnings)
        else:
            logger.success('No warnings - configs gathered successfully! (manual verification still required)')


class DecomGen(cg.ConfigGen):
    def __init__(self):
        super().__init__()
        self.circuit_type_factory = {
            'autodetect': self.autodetect,
            'internet': InternetDecomGen,
            'transparent_lan': TransparentLanDecomGen,
            'vpls': VplsDecomGen,
            'oh_srx': OhSrxDecomGen
        }

    def autodetect(self, form):
        """Returns a Device object with an active connection if circuit detection was successful"""
        logger.info('Circuit type detection enabled')
        full_intf = f"{form['portSpeed']}{form['interface']}"
        if form['vlan']:
            full_intf += f".{form['vlan']}"

        device = ssh.Device(form['router'])
        with device.connect():
            circuit_type = device.detect_circuit_type(full_intf)
            if circuit_type:
                logger.success('Detected circuit type: {}', circuit_type.upper())
                circuit = self.circuit_type_factory[circuit_type](form)
                circuit.fetch_rollbacks(device)
                return circuit


class InternetDecomGen(cg.BaseGenerator):
    def __init__(self, form):
        super().__init__(form)
        self.template = os.path.join(cg.TEMPLATE_DIR, 'decom/internet.txt')
        self.filename = 'Internet disconnect configs.txt'
        self.rollback = Rollback()
        self.form['rollback'] = None

    def fetch_rollbacks(self, device=None):
        """Gets rollback configs starting with interface, then IS-IS, then BGP

        Args:
            device (Device): a Device object with an active SSH connection

        Returns:
            bool: True if configs were gathered successfully
        """
        errors = 0  # Error flag, gets incremented if there's an error fetching a routing protocol's rollback
        max_errors = 2
        self.device = device
        # Allows for an active context manager to be passed (from circuit autodetect function)
        with ExitStack() as stack:
            if self.device is None:
                self.device = ssh.Device(self.form['router'])
                stack.enter_context(self.device.connect())

            if not self._rollback_interface():
                return

            self._rollback_isis()
            self._rollback_bgp()

        self.form['rollback'] = self.rollback.make()
        logger.success('All rollbacks fetched.')
        self.configs = self.generate()

    def _rollback_interface(self):
        logger.info('Getting interface configs')

        # Append VLAN to the interface if it exists
        self.form['full_interface'] = f"{self.form['port_speed']}{self.form['interface']}"
        if self.form.get('vlan'):
            self.form['full_interface'] += f".{self.form['vlan']}"

        output = self.device.show_run_interface(f"{self.form['full_interface']}")
        if not output:
            logger.error("Interface {} doesn't exist", self.form['full_interface'])
            return

        self.rollback.add(output['cli'])
        try:
            self.form['neighbor_ip'] = ip_address(output['data'][0]['ipv4']) + 1
        except KeyError:
            logger.error('Interface {} has no IP address', self.form['full_interface'])
            return

        logger.success('Fetched rollback configs for {}', self.form['full_interface'])
        return True

    def _rollback_isis(self):
        """Checks if the interface is configured in the IS-IS instance"""
        logger.info('Checking for IS-IS configs')
        # Assumes old PED0# routers use instance '1' and PED30+ routers use 'ngn'
        self.form['isis_instance'] = '1' if 'PED0' in self.form['router'] else 'ngn'
        self.form['has_isis'] = False # fine to remove?
        # ONLY FOR DEVELOPMENT (LAB ROUTERS)
        if 'PED' not in self.form['router']:
            self.form['isis_instance'] = '1'

        # Get rollback for IS-IS circuit, if applicable
        output = self.device.show_run(
            f"router isis {self.form['isis_instance']} interface {self.form['full_interface']}"
        )
        if output:
            logger.success("IS-IS configs found.. checking for any static routes")
            self.form['has_isis'] = True  # Sometimes configs exist for both IS-IS and BGP
            self.rollback.add(output)

            # Circuit found in IS-IS instance, check for static routes
            # TODO: move this into a method and get multiple routes
            # e.g. husky - 02-LMXP-000702-HYR-000
            template = '  {{ static_route }} {{ neighbor_ip }}'
            output = self.device.show_run(
                command=f"router static address-family ipv4 unicast | i {self.form['neighbor_ip']}",
                template=template
            )
            if output:
                self.form['static_route'] = output['data'][0]['static_route']
                logger.success('Static route found: {}', self.form['static_route'])
                self.rollback.add(self.device.show_run(
                    f"router static address-family ipv4 unicast {self.form['static_route']} {self.form['neighbor_ip']}")
                )
        return self.form['has_isis']

    def _rollback_bgp(self):
        """Checks for BGP neighbor, route-policy, and prefix-set configs"""
        logger.info('Getting BGP rollbacks')
        # Get rollback for BGP neighbor and get the route-policy name
        template = '   route-policy {{ route_policy }} in'
        output = self.device.show_run(f"router bgp 19752 neighbor {self.form['neighbor_ip']}", template)
        if not output:
            logger.warning('No configs found for BPG neighbor {}', self.form['neighbor_ip'])
            self.form['routing_protocol'] = 'isis'
            return

        self.form['routing_protocol'] = 'bgp'
        self.rollback.add(output['cli'])
        self.form['route_policy'] = output['data'][0]['route_policy']
        logger.success('Fetched rollback for BGP neighbor {}', self.form['neighbor_ip'])

        # Get rollback for route-policy, return False if not found since prefix-set depends on these configs
        template = "  if destination in {{ prefix_set | exclude('MARTIANS') }} then"
        output = self.device.show_run(f"route-policy {self.form['route_policy']}", template)
        if not output['data'][0]:
            logger.error("No route-policy found")
            return

        self.rollback.add(output['cli'])
        self.form['prefix_set'] = output['data'][0]['prefix_set']
        logger.success('Fetched rollback for route-policy {}', self.form['route_policy'])

        # Get rollback for prefix-set
        self.rollback.add(self.device.show_run(f"prefix-set {self.form['prefix_set']}"))
        logger.success("Fetched rollback for prefix-set {}", self.form['prefix_set'])


class TransparentLanDecomGen(cg.BaseGenerator):
    def __init__(self, form):
        super().__init__(form)
        self.template = os.path.join(cg.TEMPLATE_DIR, 'decom/transparent_lan.txt')
        self.filename = 'Transparent LAN disconnect configs.txt'

    def fetch_rollbacks(self, device=None):
        """Gets rollback configs starting with A-end router, then Z-end.

        Args:
            device (Device): a Device object with an active SSH connection

        Returns:
            bool: True if rollbacks for both ends were gathered successfully
        """
        if self._rollback_router_a(device):
            self._rollback_router_z()
            self.configs = self.generate()

    def _rollback_router_a(self, device=None):
        """Discovers router_z, pw_id, and pseudowire info using the logical interface

        Args:
            device (Device): a Device object with an active SSH connection
        """
        self.form['router_a'] = self.form['router']
        # Allows for an active context manager to be passed (from circuit autodetect function)
        with ExitStack() as stack:
            if device is None:
                device = ssh.Device(self.form['router_a'])
                stack.enter_context(device.connect())

            # Get Router Z hostname
            template = 'l2vpn xconnect group {{ neighbor }} p2p {{ p2p_name }} interface {{ interface }}'
            output = device.show_run(
                f"formal | i {self.form['interface']}.{self.form['vlan']}", template=template
            )['data'][0]

            try:
                self.form['router_z'] = output['neighbor']
                p2p_name = output['p2p_name']
                logger.success('Discovered Z-end router: {}', self.form['router_z'])
            except KeyError:
                logger.error('No pseudowire found with interface {}.{}', self.form['interface'], self.form['vlan'])
                return

            # Get pseudowire info
            # TODO: make this a function?
            output = device.show_run(
                f"l2vpn xconnect group {self.form['router_z']} p2p {p2p_name}", template='l2vpn_xconnect'
            )
            pseudowire = output['data'][0]
            self.form['pw_id'] = pseudowire['pw_id']
            self._make_rollbacks(device, pseudowire, '_a')
        return True

    def _rollback_router_z(self):
        """Gets pseudowire info using the pw-id. Requires Router A rollback to be successful"""
        device = ssh.Device(self.form['router_z'])
        with device.connect():
            output = device.show_run(f"l2vpn xconnect group {self.form['router_a']}", template='l2vpn_xconnect')
            pseudowire = [pw for pw in output['data'] if pw['pw_id'] == self.form['pw_id']][0]
            self._make_rollbacks(device, pseudowire, '_z')

    def _make_rollbacks(self, device, pseudowire, suffix):
        """Gets interface and pseudowire rollbacks for one end of a TLS

        Args:
            device (ssh.Device): Device object with an active connection
            pseudowire (dict): parsed pseudowire information (p2p name, full interface, etc.)
            suffix (str): either _a or _z depending on the TLS end
        """
        logger.info(f"Fetching rollback configs for {device.hostname}")
        neighbor = self.form['router_z'] if device.hostname == self.form['router_a'] else self.form['router_a']

        # Fetch CLI output
        rollback = Rollback()
        rollback.add(device.show_run(f"interface {pseudowire['interface']}"))
        rollback.add(device.show_run(f"l2vpn xconnect group {neighbor} p2p {pseudowire['p2p_name']}"))

        # Set key/values according to router end
        self.form[f"interface{suffix}"] = pseudowire['interface']
        self.form[f"p2p_name{suffix}"] = pseudowire['p2p_name']
        self.form[f"rollback{suffix}"] = rollback.make()
        logger.success('Rollback configs gathered for {}', device.hostname)


class VplsDecomGen(cg.BaseGenerator):
    def __init__(self, form):
        super().__init__(form)
        self.template = os.path.join(cg.TEMPLATE_DIR, 'decom/vpls.txt')
        self.filename = 'VPLS disconnect configs.txt'
        self.form['legs'] = []

    def fetch_rollbacks(self, device=None):
        """Gets rollback configs starting with A-end router, then Z-end.

        Args:
            device (Device): a Device object with an active SSH connection

        Returns:
            True if rollbacks for both ends were gathered successfully
        """
        if not self._get_circuit_info(device):
            return

        # Get rollback for provided leg and discover any other legs
        self._rollback_leg(device)
        logger.success('Attempting to discover other legs.')
        legs = ssh.discover_legs(self.form['vpn_id'])
        if legs is None:
            logger.warning('No other VPLS legs found.')
        else:
            legs.remove(device.hostname)
            for leg in legs:
                device = ssh.Device(leg)
                with device.connect():
                    self._rollback_leg(device)
        self.configs = self.generate()

    def _get_circuit_info(self, device=None):
        """Get rollback configs for the provided leg and set the bridge-domain name & VPN ID for leg discovery"""
        with ExitStack() as stack:
            if device is None:
                device = ssh.Device(self.form['router'])
                stack.enter_context(device.connect())

            try:
                # Set the bridge-domain name and VPN ID
                self.form['bd_name'] = device.get_bridge_domain_name(
                    value_type='interface', value=f"{self.form['interface']}.{self.form['vlan']}"
                )
                self.form['vpn_id'] = device.get_vpn_id(self.form['bd_name'])
            except KeyError:
                logger.error('Error discovering the bridge-domain name and/or VPN ID')
                return
            return True

    def _rollback_leg(self, device):
        """Gets rollback configs for a leg. Assumes the bridge-domain name and VPN ID is already set."""
        bd_name = self.form['bd_name']
        rollback = Rollback()
        # Using the bridge-domain name of the first leg, get all interfaces configured on it
        interfaces = device.get_bd_interfaces(bd_name)
        if interfaces is None:
            # Get bridge-domain name of this specific leg
            logger.warning("Mismatch of bridge-domain names between legs.. discovering this legs bd-name")
            bd_name = device.get_bridge_domain_name(value_type='vpn_id', value=self.form['vpn_id'])
            interfaces = device.get_bd_interfaces(bd_name)

        # Set leg specific info and rollbacks
        for intf in interfaces:
            rollback.add(device.show_run(f'interface {intf}'))
        rollback.add(device.show_run(f'l2vpn bridge group VPLS bridge-domain {bd_name}'))
        self.form['legs'].append({
            'rollback': rollback.make(),
            'hostname': device.hostname,
            'bd_name': bd_name,
            'interfaces': interfaces
        })
        logger.success('Fetched rollbacks for leg {}.', device.hostname)


class OhSrxDecomGen(cg.BaseGenerator):
    def __init__(self, form):
        super().__init__(form)
        self.template = '../assets/templates/decom/oh_standard.txt'
        self.filename = 'OH Disconnect Configs.txt'
        self._map_vars()
        self.warnings = 0

    def fetch_rollbacks(self):
        threads = 1
        if self.form.get('multithreading'):
            threads = 3

        logger.info('Fetching rollback configs with ({}) thread(s).', threads)
        futures = {}
        with cf.ThreadPoolExecutor(max_workers=threads) as executor:
            futures.update({'edge_router': executor.submit(self._rollback_edge)})
            # futures.update({'vpn_conc': executor.submit(self._rollback_vpn_conc)})
            # futures.update({'core_router': executor.submit(self._rollback_core)})
        self.form['rollback'] = {host: future.result() for host, future in futures.items()}
        self.configs = self.generate()

    def _map_vars(self):
        # Parses services into a nested dictionary.
        # Sets each service as { service_vlan: {} } - empty dict to be filled during rollback fetching
        self.form['services'] = {v: {} for k, v in self.form.items() if 'service_vlan' in k}

        # Gets PE site info
        data = OH_DATABASE.pe_sites[self.form['pe_router']]
        for k, v in data.items():
            self.form[k] = v

        # Keeps hostname only for PE Routers with multiple options (e.g. 1G/10G)
        self.form['pe_router'] = data['pe_router'].split()[0]

    def _rollback_edge(self):
        rollback = Rollback()

        device = ssh.Device(self.form['asr_name'])
        with device.connect():
            # Logical interfaces
            nni_port = f"{self.form['nni_port_speed']}{self.form['nni_interface']}"
            interfaces = [
                f"{self.form['asr_45w_port']}.{self.form['vpn_vlan']}",
                f"{self.form['asr_46w_port']}.{self.form['vpn_vlan']}",
                f"{self.form['asr_nms_port']}.{self.form['nms_vlan']}",
                f"{nni_port}.{self.form['vpn_vlan']}",
                f"{nni_port}.{self.form['nms_vlan']}"
            ]
            for intf in interfaces:
                rollback.add(device.show_run(f"interface {intf}"))

            # Get pseudowire and bridge group/domain names
            # def get_p2p_name
            template = "l2vpn xconnect group Local-Switch p2p {{ p2p_name }}\n" \
                       "l2vpn bridge group {{ bridge_group | contains('SRX') }} bridge-domain {{ bd_name }}"
            data = device.show_run(f"formal | i {self.form['clei']}", template=template)['data'][0]

            # Pseudowire & bridge-domain
            # TODO: check if this handles MPLS properly
            try:
                rollback.add(device.show_run(f"l2vpn xconnect group Local-Switch p2p {data['p2p_name']}"))
                rollback.add(device.show_run(
                    f"l2vpn bridge group {data['bridge_group']} bridge-domain {data['bd_name']}")
                )
            except KeyError:
                logger.warning("Couldn't parse l2vpn info.. ensure this is a standard Layer 2 circuit.")
        logger.success('Fetched rollbacks for {}', device.hostname)
        rollback.warn()
        return rollback.make()

    def _rollback_vpn_conc(self):
        rollback = Rollback()
        host = self.form['srx3600_name']
        # Attempts connection to back-up VPN Concentrator if connection to primary fails
        # Assumes VPN concentrator has common naming convention ending in '5W' & '6W'
        for _ in range(2):
            try:
                device = ssh.Device(hostname=host, device_type='juniper')
                with device.connect():
                    rollback.add(device.show_configuration(f"match {self.form['clei']}"))
                    # TODO: spacer inbetween quotes of match ' vlan '. do this for services too
                    rollback.add(device.show_configuration(f"match \"security zones\" | match .{self.form['vpn_vlan']}"))
                    rollback.add(device.show_configuration(f"match interfaces | match \"unit {self.form['vpn_vlan']} \""))
                    for vlan in self.form['services'].keys():
                        rollback.add(device.show_configuration(f"match interfaces | match \"unit {vlan} \""))
                    logger.success('Fetched rollbacks for {}', host)
                    rollback.warn()
                    return rollback.make(newlines=1)
            except AttributeError:
                logger.warning(f"Couldn't connect to the primary VPN concentrator.. trying the backup")
                host = host.replace('5W', '6W')

    def _rollback_core(self):
        rollback = Rollback()

        device = ssh.Device(hostname=self.form['pe_router'], device_type='cisco_xe')
        with device.connect():
            # Empty rollbacks
            bridge_domains = Rollback()
            route_maps = Rollback()
            bgp_vrf = Rollback(f'router bgp 21992')

            # NMS BDI & VRF - allows script to fail silently if there's no NMS BDI info
            output = device.show_run_interface(f"BDI{self.form['nms_vlan']}", strip_lines=4)
            if output is None:
                rollback.warnings += 2
            else:
                rollback.add(output['cli'])
                self.form['nms_neighbor_ip'] = str(ip_address(output['data'][0]['ipv4']) + 1)

                # NMS BGP VRF
                bgp_vrf.add([
                    f" address-family ipv4 vrf {'CPE-MGMT'}\n",
                    device.show_run(f"vrf CPE-MGMT | include {self.form['nms_neighbor_ip']}", read_timeout=20)],
                    newlines=1)

            # NMS bridge-domain
            bridge_domains.add(
                f"bridge-domain {self.form['nms_vlan']}\n"
                f'''{device.show_run(f"bridge-domain {self.form['nms_vlan']}", strip_lines=4)}''')

            # TODO: NMS SI on physical port

            # Parent interface command for each service instance
            primary_vpn_conc = Rollback(f"interface {self.form['pe_45w_port']}")
            backup_vpn_conc = Rollback(f"interface {self.form['pe_46w_port']}")
            for vlan, values in self.form['services'].items():
                # Service BDI's
                output = device.show_run_interface(f"BDI{vlan}", strip_lines=4)
                rollback.add(output['cli'])
                values.update({
                    'vrf': output['data'][0]['vrf'],
                    'neighbor_ip': str(ip_address(output['data'][0]['ipv4']) + 1)
                })

                # PE - VPN Conc. ports for primary & backup
                primary_vpn_conc.add(device.show_run(f"interface {self.form['pe_45w_port']} | section {vlan}"), newlines=1)
                backup_vpn_conc.add(device.show_run(f"interface {self.form['pe_46w_port']} | section {vlan}"), newlines=1)
                bridge_domains.add([
                    f"bridge-domain {vlan}\n",
                    device.show_run(f"bridge-domain {vlan}", strip_lines=4)
                ])

                # BGP VRF's
                bgp_vrf.add([
                    f" address-family ipv4 vrf {values['vrf']}\n",
                    device.show_run(f"vrf {values['vrf']} | include {values['neighbor_ip']}")],
                    newlines=1)

                # Route maps
                vrf = values['vrf']
                if vrf == 'INTERNET-VRF':  # maybe take this from the database?
                    vrf = 'INTERNET'
                route_maps.add(
                    device.show_run(f"| section {self.form['clei']}-{vrf}-IN permit", read_timeout=20),
                    newlines=1)

            # Add individual rollbacks
            rollback.add(primary_vpn_conc)
            rollback.add(backup_vpn_conc)
            rollback.add(bridge_domains)
            rollback.add(bgp_vrf)
            rollback.add(route_maps)

            logger.success('Fetched rollbacks for {}', device.hostname)
            rollback.warn()
            return rollback.make(newlines=1)

    def _rollback_core_services(self):
        pass


@logger.catch
def main():
    pass


if __name__ == "__main__":
    main()
