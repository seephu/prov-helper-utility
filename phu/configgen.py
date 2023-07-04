# Standard Library
import os.path
from datetime import date
from zipfile import ZipFile
from random import randrange
from ipaddress import ip_address, ip_network
from dataclasses import dataclass

# Third party
import humps
import jinja2
import openpyxl
import pandas as pd
from vsdx import VisioFile
from loguru import logger

# Custom
import ssh
from database import COMMERCIAL_DB, OH_DB

SERVED_FILES_DIR = '../assets/served_files'
TEMPLATE_DIR = '../assets/templates'
DATABASE_DIR = '../assets/database'

DATABASE = COMMERCIAL_DB


class ConfigGen:
    def __init__(self):
        self.circuit_type_factory = {
            'internet': InternetConfigGen,
            'transparent_lan': TransparentLanConfigGen,
            'vpls': VplsConfigGen,
            'layer2_test': Layer2Test,
            'raisecom': Raisecom,
            'oh_srx': OhSrxConfigGen
        }

    def generator(self, form):
        """Factory method that returns the appropriate BaseGenerator object

        Args:
            form: an un-parsed HTML form (still in camelCase)

        Returns:
            BaseGenerator: mapped object according to circuit_type_factory
        """
        try:
            circuit_type = form['circuitType']
        except KeyError:
            circuit_type = form['circuit_type']

        if self.circuit_type_factory.get(circuit_type):
            return self.circuit_type_factory[circuit_type](form)
        else:
            logger.error('Invalid circuit type: {}', circuit_type)
            logger.warning('Available circuit mappings: \n{}', list(self.circuit_type_factory.keys()))


class BaseGenerator:
    def __init__(self, form):
        """Takes in HTML POST data from front-end

        Args:
            form (dict): HTML POST data which will get converted from camelCase to snake_case
        """
        self.html = form  # Store original camelCase fields are debugging
        self.form = self.parse_form(form)
        self.configs = None
        self.template = None
        self.filename = None

    def generate(self, template=None, context=None, strict=False):
        """Renders a Jinja2 template

        Args:
            template: path to a template file
            context: a dictionary for template rendering
            strict: a bool for whether to use StrictUndefined (raise error on any undefined keys)
        """
        if template is None:
            template = self.template

        if context is None:
            context = self.form

        # Set-up Jinja environment
        undefined = jinja2.StrictUndefined if strict else jinja2.Undefined
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=undefined
        )
        env.filters['ip_addr_plus'] = ip_addr_plus

        tmp = env.get_template(template)
        logger.debug('Rendering template: \'{}\'', tmp)
        logger.success('({} - Config Gen) - configs generated from \'{}\'', self.__class__.__name__, template)
        return tmp.render(context)

    @logger.catch
    def parse_form(self, form):
        stripped = {}
        for k, v in form.items():
            try:
                v.strip()
            except AttributeError:
                pass
            stripped.update({k: v})

        return humps.decamelize(stripped)


class BaseConfigGen(BaseGenerator):
    def __init__(self, form):
        """Takes in HTML POST data from front-end"""
        super().__init__(form)
        self.diagram_template = None

    def generate_diagram(self, out_file):
        """Generates a diagram using FormData's context"""
        with VisioFile(self.diagram_template) as vis:
            vis.jinja_render_vsdx(self.form)
            vis.save_vsdx(out_file)
            logger.success('({} - Config Gen) - {} - diagram generated', self.__class__.__name__, self.filename)
            logger.success('Saved to {}', out_file)

    def zip(self, out_file):
        """Saves the config and diagram file into a .zip archive"""
        config_file = self.filename + '.txt'
        diagram_file = self.filename + '.vsdx'
        with ZipFile(out_file, mode='w') as archive:
            archive.writestr(config_file, self.configs)
            try:
                diagram_file = self.filename + '.vsdx'
                self.generate_diagram(diagram_file)
                archive.write(diagram_file)
                os.unlink(diagram_file)
            except FileNotFoundError:
                logger.exception('Error cleaning up diagram: {}', diagram_file)


class InternetConfigGen(BaseConfigGen):
    def __init__(self, form):
        """Auto-generates configs if not a decom circuit"""
        super().__init__(form)
        self._map_vars()
        self.filename = f"{self.form['customer']} - {self.form['bandwidth']}M Internet - {self.form['circuit_id']}"
        self.template = 'internet.txt'
        self.diagram_template = os.path.join(TEMPLATE_DIR, 'internet.vsdx')
        self.configs = self.generate()

    def _map_vars(self):
        """Additional variable mappings with custom logic"""
        self.form['clli'] = DATABASE.asr9k_routers[self.form['router']]['clli']
        # self.form['full_interface'] = f"{self.form['port_speed']}{self.form['interface']}"
        self.form['isis_instance'] = 'ngn'
        self.form['p2p_ip_block'] = self.form['p2p_ip_block'].strip()
        self.form['p2p_ip_local'] = str(ip_address(self.form['p2p_ip_block']) + 1)
        self.form['p2p_ip_neighbor'] = str(ip_address(self.form['p2p_ip_block']) + 2)
        self.form['p2p_netmask'] = str(
            ip_network(f"{self.form['p2p_ip_block']}/{self.form['p2p_cidr']}", strict=False).netmask
        )
        self.form['full_interface'] = make_full_interface(
            self.form['port_speed'], self.form['interface'], self.form['vlan']
        )

        # Set POP site attributes based off db column names
        for k, v in DATABASE.pop_sites[self.form['clli']].items():
            self.form[k] = v

        # BGP keys
        if self.form['routing_protocol'] == 'bgp':
            self.form['customer_shortened'] = self.form['customer'].replace(' ', '')
            self.form['export_policy'] = 'ALL' if self.form.get('full_routing_table') else 'DEFAULT'
            self.form['default_route'] = self.form.get('default_route')
            self.form['prefix_list_obj'] = [ip.strip() for ip in self.form['prefix_list'].split(',')]

        # Assumes all older routers use '1' as the isis instance, and new PED30s+ use 'ngn'
        if 'PED0' in self.form['router']:
            self.form['isis_instance'] = '1'

        # Add layer 2 test set configs
        if self.form.get('test_set_configs'):
            self.form['layer2_test'] = Layer2Test(self.form).configs

    def generate_diagram(self, out_file):
        """Deletes either the static or BGP template page and generates a diagram"""
        with VisioFile(self.diagram_template) as vis:
            if self.form['routing_protocol'] == 'bgp':
                vis.remove_page_by_name('Static')
            else:
                vis.remove_page_by_name('BGP')

            vis.pages[0].name = 'Overview Drawing'
            vis.jinja_render_vsdx(self.form)
            vis.save_vsdx(out_file)
        logger.info(f"Diagram generated and saved: {out_file}")


class TransparentLanConfigGen(BaseConfigGen):
    def __init__(self, form):
        """Auto-generates configs if not a decom circuit"""
        super().__init__(form)
        self._map_vars()
        self.template = 'transparent_lan.txt'
        self.filename = self._make_filename()
        self.diagram_template = os.path.join(TEMPLATE_DIR, 'transparent_lan.vsdx')
        self.configs = self.generate()

    def _map_vars(self):
        """Additional variable mappings with custom logic"""
        # Router A
        self.form['clli_a'] = DATABASE.asr9k_routers[self.form['router_a']]['clli']
        self.form['router_ip_a'] = DATABASE.asr9k_routers[self.form['router_a']]['lo0_ip']
        self.form['full_interface_a'] = f"{self.form['port_speed_a']}{self.form['interface_a']}.{self.form['vlan']}"

        # Router Z
        self.form['clli_z'] = DATABASE.asr9k_routers[self.form['router_z']]['clli']
        self.form['router_ip_z'] = DATABASE.asr9k_routers[self.form['router_z']]['lo0_ip']
        self.form['full_interface_z'] = make_full_interface(
            self.form['port_speed_z'], self.form['interface_z'], self.form['vlan']
        )

        # Set POP site attributes for A and Z-end
        suffixes = ['_a', '_z']
        for sfx in suffixes:
            for k, v in DATABASE.pop_sites[self.form[f"clli{sfx}"]].items():
                self.form[f"{k}{sfx}"] = v

        # Layer 2 test set configs
        if self.form.get('test_set_configs'):
            l2_form = {
                'circuitId': self.form['circuit_id'],
                'router': self.form['router_z'],
                'portSpeed': self.form['port_speed_z'],
                'interface': self.form['interface_z'],
                'vlan': self.form['vlan'],
                'bandwidth': self.form['bandwidth']
            }
            self.form['layer2_test'] = Layer2Test(l2_form).configs

    def _make_filename(self):
        return f"{self.form['customer']} - {self.form['bandwidth']}M Transparent LAN - {self.form['circuit_id']}"


class VplsConfigGen(BaseConfigGen):
    def __init__(self, form):
        super().__init__(form)
        self._map_vars()
        self.template = 'vpls.txt'
        self.filename = f"{self.form['customer']} - {self.form['bandwidth']}M VPLS - {self.form['circuit_id']}"
        self.configs = self.generate()

    def _map_vars(self):
        self.form['description'] = self.form['description'].replace('-XXX', '')

        # Map variables for all 3 legs
        suffix = 1
        while suffix < 4:
            # Full interface
            port_speed = self.form[f"port_speed{suffix}"]
            interface = self.form[f"interface{suffix}"]
            self.form[f"full_interface{suffix}"] = f"{port_speed}{interface}.{self.form['vlan']}"

            # Router IP
            self.form[f"router_ip{suffix}"] = DATABASE.asr9k_routers[self.form[f"router{suffix}"]]['lo0_ip']
            suffix += 1


class Layer2Test(BaseConfigGen):
    def __init__(self, form):
        super().__init__(form)
        self._map_vars()
        self.filename = f"Layer 2 Test - {self.form['bandwidth']}M TLS - {self.form['circuit_id']}"
        self.template = 'layer2test.txt'
        self.configs = self.generate()

    def _map_vars(self):
        """Additional variable mappings with custom logic"""
        self.form['pw_id'] = str(randrange(100, 999))
        self.form['router_ip'] = DATABASE.asr9k_routers[self.form['router']]['lo0_ip']

        # Set random VLAN if interface is untagged
        if not self.form['vlan']:
            self.form['vlan'] = str(randrange(1000, 4000))
        self.form['full_interface'] = f"{self.form['port_speed']}{self.form['interface']}.{self.form['vlan']}"


class Raisecom(BaseConfigGen):
    def __init__(self, form):
        super().__init__(form)
        self._map_vars()
        self.filename = f"{self.form['clei']} - Raisecom {self.form['model']} Configs"
        self.template = DATABASE.raisecoms[self.form['model']]['template']
        self.configs = self.generate()

    def _map_vars(self):
        """Additional variable mappings with custom logic"""
        # Gets the default gateway of the NMS IP pool (assumes they're all /24's)
        self.form['nms_gateway'] = str(ip_network(f"{self.form['nms_ip']}/24", strict=False)[1])


class OhSrxConfigGen(BaseConfigGen):
    def __init__(self, form):
        super().__init__(form)
        VarsFile().generate(self.form)

    def generate_files(self, out_dir=SERVED_FILES_DIR, zipped=True):
        """Saves a site's generated configs to a .zip"""
        configs = self.generate_site_configs()
        filename = self._make_filename()
        output = os.path.join(out_dir, f"{filename}.zip")

        # FOR DEVELOPMENT ONLY - TO BE REMOVED
        if not zipped:
            out_dir = '../oh_srx_output'
            for fname, config in configs.items():
                with open(os.path.join(out_dir, fname), 'w') as f:
                    f.write(config)
            return

        with ZipFile(output, mode='w') as archive:
            for fname, config in configs.items():
                archive.writestr(fname, config)
            archive.write(VarsFile().generate(self.form, f"{filename} (vars).xlsx"))
        return output

    def generate_site_configs(self):
        """Generates complete configs for a site"""
        nodes = {'single': self.form['pe_router']}
        if self.form['site_type'] == 'dual':
            nodes['node0'] = nodes.pop('single')
            nodes['node1'] = self.form['pe_router_backup']

        configs = {}
        for node, pe_router in nodes.items():
            context = self.generate_node_context(pe_router, node)
            configs.update(self.generate_node_configs(context))

        return self._join_cpe_configs(configs)

    def generate_node_context(self, pe_router, node):
        """Generates context specific to a node (primary or backup).
        pe_vars and service_vars always get mapped. cpe_vars gets mapped if full site configs are required.

        Args:
            pe_router: the PE Router corresponding to a row in pe_sites sheet
            node: the node, either: single, node0, or node1

        Returns:
            a dictionary with node specific context
        """
        # Set-up node specific context
        context = self._join_form(self._map_pe_vars(pe_router, node))
        context['services'] = []
        context['node'] = node

        # Map CPE vars unless 'services only' option is selected
        if not self.form.get('only_services'):
            context.update(self._map_cpe_vars(pe_router, node))

        # Map service vars. Each service gets returned as a dict and added to services list.
        for idx, service in enumerate(range(int(self.form['num_services'])), start=1):
            context['services'].append(self._map_service_vars(idx, node))

        logger.debug('Context for node: {} -- \n{}', node, context)
        return context

    def generate_node_configs(self, context):
        """Generates configs for a node (either primary or backup)

        Args:
            context: a dict of node specific context

        Returns:
            a dictionary of: { filename: string of rendered configs }
        """
        templates = {
                '1 - Single CPE': context['cpe_router'],
                '2 - L2 Switch': context['l2_switch'],
                '3 - VPN Conc': context['vpn_conc'],
                '4 - PE Router': context['pe_router'],
                '5 - IPSLA': context['primary_ipsla_router']
        }
        file_suffix = ''
        if context['node'] == 'node1':
            templates.update({
                '1 - Dual CPE': context['cpe_router'],
                '1.1 - Terminal Server': context['term_server']
            })
            templates.pop('1 - Single CPE')
            templates.pop('5 - IPSLA')
            file_suffix = ''  # Used to be ' - (Backup)'

        configs = {}
        for template, device_name in templates.items():
            tmp = f"oh_srx/{template}.txt"
            filename = f"{template} - {device_name}{file_suffix}.txt"
            configs.update({filename: self.generate(tmp, context, strict=True)})
        return configs

    def _join_cpe_configs(self, configs):
        """Takes in configs for a whole site and joins the 2 CPE files if applicable (dual CPE)"""
        cpe_configs = ''.join([val for key, val in configs.items() if 'CPE' in key])
        for filename, config in dict(configs).items():
            if 'Dual' in filename:
                node0_filename = ''.join([key for key, val in configs.items() if 'Single CPE' in key])
                configs.pop(node0_filename)
                configs[filename] = cpe_configs
                break
        return configs

    def _join_form(self, context):
        """Returns the provided dictionary joined with the initial HTML form dict
        form does not get altered anywhere. Any additional attributes are mapped to a separate dict (context)
        """
        form = self.form.copy()
        return dict(form, **context)

    def _make_filename(self):
        return f"{self.form['site_id']} {self.form['device_type']} Configs - {date.today()}"

    def _map_pe_vars(self, pe_router, node):
        """Maps variables using the pe_site, lhin_site, & node_vars sheets"""
        pe_site = OH_DB.pe_sites[pe_router]
        lhin_site = OH_DB.lhin_sites[int(self.form['lhin_id'])]
        node_vars = OH_DB.node_vars
        pe_vars = {
            'active_backup': node_vars['active_backup'][node],
            'asr_45w_port': pe_site['asr_45w_port'],
            'asr_46w_port': pe_site['asr_46w_port'],
            'backup_ipsla_router': lhin_site['ip_sla_backup'],
            'l2_switch': pe_site['asr_name'],
            'local_pref_110': node_vars['local_pref_110'][node],
            'nms_path': f"NMS{node_vars['vpn_seq'][node]}-{self.form['cpe_router']}",
            'pe_45w_port': pe_site['pe_45w_port'],
            'pe_46w_port': pe_site['pe_46w_port'],
            'pe_logical_port': pe_site['pe_logical_port'],
            'pe_router': pe_site['pe_router'].split()[0],
            'pop_clli': pe_site['pop_clli'],
            'path_prefix': node_vars['path_prefix'][node],
            'pri_back': node_vars['pri_back'][node],
            'pri_bkp': node_vars['pri_bkp'][node],
            'primary_ipsla_router': lhin_site['ip_sla_primary'],
            'redundancy_group': node_vars['redundancy_group'][node],
            # 'reth_number': '?',  # might need to bring this back
            'reth_ped_backup': pe_site['reth_ped_backup'],
            # 'reth_ped_backup_vpn': pe_site['reth_ped_backup'].lower(),
            'reth_ped_primary': pe_site['reth_ped_primary'],
            # 'reth_ped_primary_vpn': pe_site['reth_ped_primary'].lower(),
            'vpn_conc': pe_site['srx3600_name'],
            'vpn_seq': node_vars['vpn_seq'][node],
            'xconnect_prefix': node_vars['path_prefix'][node]
        }
        return pe_vars

    def _map_service_vars(self, idx, node):
        """Variable mappings for an individual service.

        Args:
            idx: suffix of the service HTML elements, either '#' or '_backup#' (# = current service number index)

        Returns:
            a dictionary of a service's variables
        """
        suffix = ''
        if node == 'node1':
            suffix = '_backup'

        # Get database info
        service = {}
        service_type = self.form[f"service_type{idx}"]
        vpn_service = OH_DB.vpn_services[service_type]

        # Set attributes that require more than one line
        bw_minus_one = int(self.form[f"site_bandwidth{suffix}"]) - 1
        bandwidth = bw_minus_one if not self.form[f"service_bandwidth{idx}"] else self.form[f"service_bandwidth{idx}"]
        clci = self.form[f"service_clci{suffix}{idx}"]
        if node == 'node0':
            clci += ':P'

        service.update({
            'backup_ipsla_entry': self.form[f"service_backup_ipsla{idx}"],
            'bandwidth': bandwidth,
            'bgp_group': '' if service_type == 'INTERNET' else f"-{self.form[f'service_cpe_port{idx}'].split('/').pop()}",
            'clci': clci,
            'cpe_asn': vpn_service['cpe_asn'],
            'cpe_cidr': self.form[f"service_cpe_cidr{idx}"],
            'cpe_ip': ip_addr_plus(self.form[f"service_cpe_subnet{idx}"], 1),
            'cpe_next_hop_ip': ip_addr_plus(self.form[f"service_cpe_subnet{idx}"], 2),
            'cpe_port': self.form[f"service_cpe_port{suffix}{idx}"],
            'cpe_port_speed': self.form[f"service_cpe_port_speed{idx}"],
            'ipsec_abbrev': vpn_service['ipsec_abbreviation'],
            'ipsla_vrf': vpn_service['ip_sla_vrf_name'],
            'pe_cidr': '30',
            'pe_ip': ip_addr_plus(self.form[f"service_pe_subnet{suffix}{idx}"], 1),
            'pe_network': self.form[f"service_pe_subnet{suffix}{idx}"],
            'pe_vrf': vpn_service['pe_vrf_name'],
            'primary_ipsla_entry': self.form[f"service_primary_ipsla{idx}"],
            'route_target': vpn_service['route_target'],
            'routed_hosts': [host.strip() for host in self.form[f"service_routed_hosts{idx}"].split(',')],
            'service_policy_in': f"POLICE-{bandwidth}MB-IN" if service_type == 'INTERNET' else 'ce-pe-IN-v2',
            'service_policy_out': f"POLICE-{bandwidth}MB-OUT" if service_type == 'INTERNET' else f"pe-ce-shape-ge-{bandwidth}m",
            'service_type': service_type,
            'srx_exchange': vpn_service['srx_exchange'],
            'tunnel_id': self.form[f"service_cpe_port{idx}"].split('/').pop(),
            'vlan': self.form[f"service_vlan{suffix}{idx}"],
            'vpn_asn': vpn_service['vpn_asn'],
            'vpn_ip': ip_addr_plus(self.form[f"service_pe_subnet{suffix}{idx}"], 2),
        })

        return service

    def _map_cpe_vars(self, pe_router, node):
        """Variable mappings for the site if full site option was selected.

        Args:
            pe_router: the PE Router corresponding to a row in pe_sites sheet
            node: suffix of the HTML elements, either '' (primary has no suffix) or '_backup'

        Returns:
            a dictionary of the current node's variables
        """
        cpe_vars = {}
        sfx = '_backup' if node == 'node1' else ""
        pe_site = OH_DB.pe_sites[pe_router]
        reserved_ports = OH_DB.equipment_list[self.form['device_type'].lower()]

        bw_minus_one = int(self.form[f'site_bandwidth{sfx}']) - 1
        cpe_vars.update({
            'nni_port': self.form[f"nni_port_speed{sfx}"] + self.form[f"nni_interface{sfx}"],
            'asr_nms_port': pe_site['asr_nms_port'],
            'bw_minus_one': bw_minus_one,
            'clfi': f"{self.form['site_bandwidth']}M-{pe_site['pop_clli']}-{self.form['cpe_router']}",
            'current_reth': f"reth2{self.form['cpe_reth'][-1:]}" if node == 'node1' else self.form['cpe_reth'],
            'fab_port_primary': reserved_ports['fab_port_primary'],
            'fab_port_backup': reserved_ports['fab_port_backup'],
            'nms_pe_ip': self.form[f"nms_subnet{sfx}"],
            'nms_cpe_ip': ip_addr_plus(self.form[f"nms_subnet{sfx}"], 1),
            'nms_pe_port': pe_site['pe_nms_port'],
            'nms_vlan': self.form[f"nms_vlan{sfx}"],
            'reth_backup': f"reth2{self.form['cpe_reth'][-1:]}",  # move to dual_cpe_vars?
            'reth_primary': self.form['cpe_reth'],
            'stag_vlan': self.form[f"stag_vlan{sfx}"],
            'uplink_port': reserved_ports['uplink_port_primary'],  # node var
            'uplink_port_backup': reserved_ports['uplink_port_backup'],
            'vpn_cpe_ip': ip_addr_plus(self.form[f"vpn_subnet{sfx}"], 1),
            'vpn_vpn_ip': self.form[f"vpn_subnet{sfx}"],
            'vpn_path': f"{bw_minus_one}M-{pe_site['srx3600_name']}-{self.form[f'cpe_router']}",
            'vpn_vlan': self.form[f"vpn_vlan{sfx}"],
        })
        if 'node' in node:
            # NOTE: IP calculations for term server ports are done in the template itself (using ip_addr_plus filter)
            cpe_vars.update({
                'term_server_port1': reserved_ports['ts_port_primary'],
                'term_server_port2': reserved_ports['ts_port_backup'],
            })

        # logger.debug('CPE vars: {}', cpe_vars)
        return cpe_vars

class VarsFile:
    def generate(self, form, output='../assets/served_files/vars.xlsx'):
        """Generates a vars.xlsx file for form input corrections"""
        data = self._parse_services(form)

        services = data['services']
        service_headers = [f"Service #{idx}" for idx, _ in enumerate(services, start=1)]
        data.pop('services')

        # Create DataFrame objects for the respective sheets
        cpe_df = pd.DataFrame.from_dict(data, orient='index')
        services_df = pd.DataFrame(services).T

        # Write & save DataFrames to the vars file
        vars_file = pd.ExcelWriter(output, engine='openpyxl')
        cpe_df.to_excel(vars_file, sheet_name='CPE Variables', header=['value'], index_label='variable')
        services_df.to_excel(vars_file, sheet_name='Service Variables', header=service_headers, index_label='variable')
        vars_file.save()
        logger.success('Vars file saved: {}', output)
        return output


    def load(self, file):
        """Loads information from a vars file that mimics the HTML POST dict
        The 'service' prefix and '#' suffix from service vars are added back here.

          Args:
              file: filename of legacy keys file

          Returns:
              a dict with converted form fields resembling HTML POST data
        """
        df = pd.read_excel(file, sheet_name=None, dtype=str, keep_default_na=False)

        site_rows = df['CPE Variables'].to_dict(orient='records')
        services = df['Service Variables'].to_dict(orient='list')
        data = {row['variable']: row['value'] for row in site_rows}
        var_names = services.pop('variable')
        for key, values in services.items():
            sfx = key[-1:]
            for idx, val in enumerate(values):
                form_label = f"service_{var_names[idx]}{sfx}"
                data.update({form_label: val})
        return data

    def _parse_services(self, form):
        """Returns a dictionary of form inputs with services separated as a list of nested dicts.
        Individual service keys have the 'service' prefix and '#' suffix stripped from their HTML inputs.
        """
        form = dict(form)
        form['services'] = []
        service_fields = self._get_service_fields(form)
        for idx in range(1, int(form['num_services']) + 1):  # remove self
            # services.append({field.replace('service_', ''): self.form[f'{field}{idx}'] for field in service_fields})
            service = {}
            for field in service_fields:
                header = field.replace('service_', '')
                html_input = f'{field}{idx}'
                service.update({header: form[html_input]})
                form.pop(html_input)
            form['services'].append(service)
        return form

    def _get_service_fields(self, form):
        """Returns a list of HTML field names for services
        Assumes all service fields begin with service and end with a number
        """
        service_fields = []
        for field, value in form.items():
            if field.startswith('service') and not isinstance(value, list):
                field = field[:-1]
                if field not in service_fields:
                    service_fields.append(field)
        # logger.debug('Service HTML fields: {}', service_fields)
        return service_fields

def make_full_interface(port_speed, interface, vlan):
    intf = port_speed + interface
    if vlan:
        intf += f".{vlan}"
    return intf


def ip_addr_plus(ip_addr, increment):
    """Takes in an IP address and increments it"""
    return str(ip_address(ip_addr) + increment)



@logger.catch
def main():
    pass



if __name__ == '__main__':
    main()
