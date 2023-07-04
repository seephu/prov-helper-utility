# -*- coding: utf-8 -*-
"""
Created on Wed Jun 15 11:09:12 2022

@author: 210018
"""
import os

from pandas import read_excel
from ipaddress import IPv4Address
from vsdx import VisioFile
from loguru import logger


class SiteData:
    """@DynamicAttrs"""
    def __init__(self, form, key_file):
        """Holds the form, key file, and PE site info.
        Logic for additional variables are handled in SingleCpe or DualCpe class

        Args:
            form (dict): HTML form fields
            key_file (str): filename of the config gen key file
        """
        self.template = '../assets/templates/oh_standard.vsdx'
        self.data = {'primary': {}, 'backup': {}}
        self.data.update(form)

        self._load_key_file(key_file)
        self._load_database()
        self._set_data()

    def _load_key_file(self, file):
        """Loads information from key file"""
        df = read_excel(file, sheet_name=None, dtype=str, keep_default_na=False)
        services = df['Services'].to_dict(orient='records')
        site_rows = df['Device'].to_dict(orient='records')
        data = {row['Python_key']: row['Python_value'] for row in site_rows}
        data['services'] = services

        self.data.update(data)

    def _load_database(self):
        """Saves PE Site sheet as a dict of dicts"""
        db_file = '../assets/database/oh_database.xlsx'
        df = read_excel(db_file, sheet_name=['pe_sites'])

        # Format pe_sites into a dict of dicts. Key = first column, value = dict of the row's values
        pe_sites = {}
        for _, values in df.items():
            site = {val[list(val.keys())[0]]: val for val in values.to_dict(orient='records')}
            pe_sites.update(site)

        self.pe_sites = pe_sites

    def _set_data(self):
        """Dynamically set all attributes from data dict"""
        self.data['primary'] = self.pe_sites[self.data['pe_router_primary']]
        if self.data['site_type'] == 'dual':
            self.data['backup'] = self.pe_sites[self.data['pe_router_backup']]

        for k, v in self.data.items():
            self.__setattr__(k, v)

        # Clean-up pe_sites and data attributes from instance
        del self.pe_sites
        del self.data
        # logger.debug(f"Attributes set: {self.__dict__}")


class OntarioHealthSrx:
    def __init__(self, form, key_file):
        """Generates a diagram for standard SRX single & dual CPE sites

        Args:
            form (dict): HTML form fields
            key_file (str): filename of the config gen key file
        """
        self.data = SiteData(form, key_file)
        self.filename = f"Site {self.data.site_id} - {self.data.hospital_name}.vsdx"

        cpe_types = ['primary']
        if self.data.site_type == 'single':
            self._map_vars(cpe_types)
        else:
            cpe_types.append('backup')
            self._map_vars(cpe_types)
            self._map_backup_vars()

    def _map_vars(self, cpe_types):
        """Maps all variables for single CPE, and some for dual CPE.
        Dual CPE variables mapped here are standardized aka:
            1) suffixed with _primary or _backup
            2) Stored in SiteData's primary/backup dict
        Non-standard dual CPE vars will be handled in _map_backup_vars func.

        Args:
            cpe_types (list): always contains 'primary', and if dual CPE then also 'backup'
        """
        data = self.data
        clfi_counter = 1

        for cpe in cpe_types:
            # The current CPE dict, either primary or backup
            current = getattr(data, cpe)

            # PE Router - only keep the hostname
            data.pe_router_primary = data.pe_router_primary.split()[0]

            # IP Addresses
            current[f"nms_cpe_ip"] = self._ip_addr_plus(getattr(data, f"nms_pe_ip_{cpe}"), 1)
            current[f"vpn_cpe_ip"] = self._ip_addr_plus(getattr(data, f"vpn_vpn_ip_{cpe}"), 1)

            # NNI Interface
            data.primary['nni_interface'] = f"{data.vendorNNIInterface[0:2]}{data.vendorNNIPort}"

            # CLFI
            uplink_bw = getattr(data, f"uplink_bandwidth_{cpe}")
            clfi = f"000{clfi_counter}-{uplink_bw}M-{current['pop_clli']}-{data.cpe_router}"
            current.update({'clfi': clfi})
            clfi_counter += 1

            # Services
            for service in data.services:
                if not service.get('is_filler'):
                    cpe_text = f"{service['service_type']} - {service['clci']} - " \
                               f"{service['ce_net_address']} /{service['cpe_cidr']}"
                    if cpe == 'backup':
                        cpe_text = cpe_text.replace(':P', ':B')

                    pe_text = f"{current['pe_logical_port']} {service[f'vlan_{cpe}']} (VRF: {service['service_type']})"

                    service.update({
                        f'cpe_text_{cpe}': cpe_text,
                        f'pe_port_{cpe}': pe_text,
                        f'pe_ip_{cpe}': self._ip_addr_plus(service[f'pe_network_{cpe}'], 1),
                        f'vpn_ip_{cpe}': self._ip_addr_plus(service[f'pe_network_{cpe}'], 2),
                        f'vlan_{cpe}_vlan': f"VLAN{service[f'vlan_{cpe}']}"
                    })

            # Fills empty services to avoid KeyErrors in the diagram
            max_services = 6
            services_to_add = max_services - len(data.services)
            for _ in range(services_to_add):
                data.services.append({'is_filler': True})

    def _map_backup_vars(self):
        """Maps additional variables for Dual CPE"""
        data = self.data
        # Site ID
        data.backup['site_id'] = data.site_id.replace('.60', '.70')

        # MSU ID - if 'A' is the last character, replace with 'B' otherwise just append 'B'
        data.backup['msu_id'] = data.msu_id[:-1] + 'B'
        if data.msu_id[-2:] == 'AB':
            data.backup['msu_id'].replace('AB', 'B')

        # Terminal Server IPs
        data.term_server_port1_ip = self._ip_addr_plus(data.term_server_netaddress1, 2)
        data.term_server_port2_ip = self._ip_addr_plus(data.term_server_netaddress2, 2)

        # NNI Interface
        data.backup['nni_interface'] = f"{data.vendorNNIInterfaceBackup[0:2]}{data.vendorNNIPortBackup}"

    def _ip_addr_plus(self, ip_addr, increment):
        """Takes in an IP address and increments it"""
        return str(IPv4Address(ip_addr) + increment)

    def generate(self, out_file):
        """Generates a diagram and removes pages according to site type

        Args:
            out_file (str): output file path
        """
        saved_file = os.path.join(out_file)

        with VisioFile(self.data.template) as vis:
            if self.data.site_type == 'single':
                vis.remove_page_by_name('L3-Service Design - Dual CPE')
                vis.remove_page_by_name('L2-Redundant')
                l3_page = vis.get_page_by_name('L3-Service Design - Single CPE')
            else:
                vis.remove_page_by_name('L3-Service Design - Single CPE')
                l3_page = vis.get_page_by_name('L3-Service Design - Dual CPE')

            logger.debug('Generating diagram with context: {}', self.data.__dict__)
            vis.jinja_render_vsdx(context=self.data.__dict__)

            # Remove CPE connectors but preserve the PE-VPN VLAN textbox
            filler_services = l3_page.find_shapes_by_text('None')
            for shape in filler_services:
                if 'VLAN' in shape.text:
                    shape.text = ''
                else:
                    shape.remove()

            vis.save_vsdx(saved_file)


def main():
    pass


if __name__ == "__main__":
    main()
    print()

