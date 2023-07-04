# -*- coding: utf-8 -*-
"""
Created on Tue Jan 25 22:11:52 2022

@author: 210018
"""
import re
import sys, os
import ipaddress
import win32com.client as win32

from ssh import Device, Credentials
from loguru import logger


class IPValidator:
    def __init__(self, filename, hostname):
        self.filename = filename
        self.device = Device(hostname)
        self.results = []
        self.errors = []

    def validate(self):
        ip_list = self.read_diagram()
        # implement max loops
        with self.device.connect() as conn:
            for ip in ip_list:
                command = f'show ip bgp vpnv4 all | i {ip}/'
                output = conn.send_command(command)
                if output:
                    logger.warning('{}: {}  ... conflict found', conn.find_prompt(), command)
                    result = True
                else:
                    logger.success('{}: {}  ... ok', conn.find_prompt(), command)
                    result = False
                self.results.append({'ip_address': ip, 'conflict': result})
        logger.debug('Results: {}', self.results)
    
    def read_diagram(self):
        try:
            logger.debug('Reading IPs from {}', self.filename)
            visio = win32.Dispatch('Visio.Application')
            visio.Visible = 0
            diagram = visio.Documents.Open(self.filename)
            for i, page in enumerate(diagram.Pages):
                i += 1
                if '3' in page.Name:
                    shape_text = [shape.Text.split() for shape in diagram.Pages.Item(i).Shapes]
            
            ip_list = [ip.strip(',') for text in shape_text for ip in text if self.match_ip(ip)]
        except:
            logger.exception('Error parsing diagram.')
            return
        finally:
            visio.Quit()
            cleaned = self.clean_ip_list(ip_list)
            logger.success("IP's found: {}", cleaned)
            return cleaned

    def match_ip(self, ip_addr):
        pattern = re.compile(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})')
        validated_ip = re.search(pattern, ip_addr)
        
        if validated_ip:
            return True
    
    def clean_ip_list(self, ip_list):
        cleaned_ip_list = []
    
        for ip in ip_list:
            if '/' in ip:
                address = ip.split('/')[0]
                subnet = ip.split('/')[1]
            elif 'lo' in ip:
                address = ip.split(':')[1]
                subnet = '32'
            else:
                address = ip
                subnet = '30'
            cleaned_ip_list.append(self.calculate_network_ip(address, subnet))
    
        return list(set(cleaned_ip_list))
        
    def calculate_network_ip(self, ip, subnet):
        try:
            ipaddress.ip_address(ip)
            full_ip = ip + '/' + subnet
            full_network_ip = ipaddress.ip_interface(full_ip).network
            network_ip = str(full_network_ip).split('/')[0]
            return network_ip
        except ValueError:
            self.errors.append(ip)


def get_base_dir(filename):
    if getattr(sys,'frozen', False):
        app_path = os.path.dirname(sys.executable)
    else:
        app_path = os.path.dirname(__file__)
    return os.path.join(app_path, filename)


def main():
    print('WARNING: Save & close all Visio diagrams before continuing.')
    hostname = 'PED30'
    diagram = get_base_dir('../assets/upload/Diagram.vsd')
    print('\nExtracting IPs from: {}\n{}'.format(os.path.basename(diagram), '-'*50))
    
    ip_validator = IPValidator(diagram, hostname)
    ip_validator.validate()
    input()


if __name__ == "__main__":
    main()
    

    
    
    
    
    
    
    
    
    
    
    
    
    
    