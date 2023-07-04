# prov-helper-utility
A portable Flask app that automates most of our department's manual tasks.

This app gets frozen into a lightweight executable for easy distribution.

![Main screen](https://i.imgur.com/wW8h3Ly.png)
![Example configuration generator form](https://i.imgur.com/cj2Ogcs.png)

Our daily tasks that used to take ~7-8 hours have now been streamlined into a click of a button.

I've developed automations to help with tasks ranging from network configuration management, REST API queries, database entry, and much more.
* Network configuration generators for Cisco IOS-XR/XE, Juniper JunOS, Ciena Waveserver, & Raisecom media converters.
  * Configs for L2VPN, MPLS, BGP, & IS-IS circuits.
  * Fortinet SD-WAN
  * Juniper NGFWs
* Decommission generators (grabs a snapshat of a specific circuit's configs in the case of a rollback).
* MS Visio diagram generators for all of our Layer 2 & Layer 3 circuits.
* MS Visio diagram parser to extract information into a structured format
* SSH utilities to abstract away time-consuming CLI tasks
* Many scripts have integrations with our internal REST APIs to ensure data integrity e.g.
  * API calls to our NMS (Infoblox NetMRI) for network config management tasks (routing table entries, equipment config & data, etc.)
  * Database queries when deploying new circuits (to get available VLANs, IP addresses, and unique circuit IDs)
* Assistance with database entry

