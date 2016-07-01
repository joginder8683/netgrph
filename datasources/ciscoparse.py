#!/usr/bin/env python3
#
# Generate Data for NetGrph from Cisco Configs
#
# Copyright (c) 2016 "Jonathan Yantis"
#
# This file is a part of NetGrph.
#
#    This program is free software: you can redistribute it and/or  modify
#    it under the terms of the GNU Affero General Public License, version 3,
#    as published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#    As a special exception, the copyright holders give permission to link the
#    code of portions of this program with the OpenSSL library under certain
#    conditions as described in each individual source file and distribute
#    linked combinations including the program with the OpenSSL library. You
#    must comply with the GNU Affero General Public License in all respects
#    for all of the code used other than as permitted herein. If you modify
#    file(s) with this exception, you may extend this exception to your
#    version of the file(s), but you are not obligated to do so. If you do not
#    wish to do so, delete this exception statement from your version. If you
#    delete this exception statement from all source files in the program,
#    then also delete it in the license file.
#
#
import sys
import re
import argparse
import socket
import csv
import ipaddress
from ciscoconfparse import CiscoConfParse

# Config Options
conf_dir = "/scripts/sendjob/configs/"
#conf_dir = "/tftpboot/"

# P2P networks match this cidr regex
p2p_regex = '^10\.23\.'

# Argument Parser
parser = argparse.ArgumentParser()
parser = argparse.ArgumentParser(description='Generate Cisco Configuration Details')
parser.add_argument("-vr", metavar='vlans',
                    help="Vlan range to generate L2 VLANs on (eg. 1-1005)", type=str)
parser.add_argument("-ivr", metavar='vlans',
                    help="Vlan range to generate Routed VLANs on (eg. 1-1005)", type=str)
parser.add_argument("-df", metavar='devicelist', help="Devicelist CSV file from NetGrph", type=str)
parser.add_argument("-vfile", metavar='outfile', help="VLAN CSV Output File", type=str)
parser.add_argument("-ifile", metavar='outfile', help="Interface CSV Output File", type=str)
parser.add_argument("-dfile", metavar='outfile', help="Device Output File (SNMP etc)", type=str)
parser.add_argument("-debug", help="Set debugging level", type=int)

# Argument Reference
args = parser.parse_args()

# Global Variables
vhigh = 4096
vlow = 1
switches = []
vlan_list = []
interface_list = []
device_list = []

DEBUG = 0
if args.debug: DEBUG = args.debug


# Get the High and Low VLAN Range variables
def process_vlans(vlanRange):
    global vhigh
    global vlow

    (vlow, vhigh) = get_vlan_range(vlanRange)

    if DEBUG: print("VLAN Range Low: " + str(vlow) + " High: " + str(vhigh), file=sys.stderr)

def get_vlan_range(vlan_range):
    vlans = vlan_range.rsplit("-")
    v_low  = int(vlans[0])

    if len(vlans) > 1:
        if int(vlans[1]) <= 4096:
            v_high = int(vlans[1])
        else:
            v_high = 4096
    else:
        v_high = v_low
    return(v_low, v_high)


def loadDevicelist(dev_file):
    """Load NetGrph devices.csv"""

    if DEBUG:
        print("Loading Devicelist: " + devfile, file=sys.stderr)

    f = open(dev_file)
    devdb = csv.DictReader(f)
    return devdb

def get_device_info(device):
    """Get Device Information from Config"""

    conf_file = conf_dir + device['Device'] + "-confg"

    try:
        parse = CiscoConfParse(conf_file)
    except:
        print("Warning, could not load config for ", conf_file)
        return
    else:
        dentry = parse_snmp(parse, device['Device'])
        device_list.append(dentry)


def parse_snmp(parse, device):
    """Get the SNMP Info from a device"""

    dentry = dict()
    dentry['Location'] = 'Unknown'
    dentry['Device'] = device

    snmp = parse.find_objects(r'snmp-server location')

    for s in snmp:

        location = s.text.replace('snmp-server location ', '')
        location = location.replace(',', '')
        dentry['Location'] = location

    return dentry


def get_interfaces(device):
    """Get the Interfaces off a device"""

    conf_file = conf_dir + device['Device'] + "-confg"

    if device['Type'] == 'Primary' or device['Type'] == 'Standby':

        try:
            parse = CiscoConfParse(conf_file)
        except:
            print("Warning, could not load config for ", conf_file)
            return
        else:

            vlan_ints = parse_vlan_interfaces(parse, device['Device'])

            for en in vlan_ints:
                en['MgmtGroup'] = device['MgmtGroup']
                if device['Type'] == 'Standby':
                    en['Standby'] = True
                else:
                    en['Standby'] = False
                interface_list.append(en)

            l3_ints = parse_l3_interfaces(parse, device['Device'])

            for en in l3_ints:
                en['MgmtGroup'] = device['MgmtGroup']
                if device['Type'] == 'Standby':
                    en['Standby'] = True
                else:
                    en['Standby'] = False
                interface_list.append(en)


def parse_l3_interfaces(parse, device):
    """Parse Routed interfaces and IOS Router Gi0/0.X interfaces"""

    interfaces = parse.find_objects_w_child(
       r'^interface.*(Ethernet)(\d+)(\/\d+)*(\.\d+)?$',
       'ip\saddress\s(\d+.\d+.\d+.\d+)')
    # interfaces = parse.find_objects_w_child(
    #     r'^interface.*',
    #     'ip\saddress\s(\d+.\d+.\d+.\d+)')

    ints = []

    for i in interfaces:
        ientry = dict()

        v = re.search(r'^interface.*Ethernet\d+(\/\d+)*(\.)?(\d+)?$', i.text)
        vid = 0

        # Get Subinterface ID
        if v.lastindex == 3:
            vid = v.group(3)
        ientry['vid'] = vid
        ientry['desc'] = 'None'

        full = i.all_children
        for line in full:
            ientry = parse_int(line.text, ientry)

        if 'ip' in ientry.keys():
            ientry['network'] = ipaddress.ip_network(ientry['ip'], strict=False)
            ientry['device'] = device
            if 'vrf' not in ientry.keys():
                ientry['vrf'] = 'default'
            ints.append(ientry)

    return ints


def parse_vlan_interfaces(parse, device):
    """Parse interface VlanX interfaces"""

    interfaces = parse.find_objects("^interface Vlan(\d+)$")

    ints = []

    for i in interfaces:

        ientry = dict()

        # Parse L3 VLAN interfaces
        v = re.search('interface Vlan(\d+)$', i.text)
        cvlan = v.group(1)

        if int(cvlan) >= vlow and int(cvlan) <= vhigh:
            ientry['vid'] = cvlan
            ientry['desc'] = 'None'
            full = i.all_children
            for line in full:
                ientry = parse_int(line.text, ientry)

            if 'ip' in ientry.keys():
                ientry['network'] = ipaddress.ip_network(ientry['ip'], strict=False)
                ientry['device'] = device
                if 'vrf' not in ientry.keys():
                    ientry['vrf'] = 'default'
                ints.append(ientry)

                # Secondary
                if 'sec_ip' in ientry.keys():
                    #print("Secondary", ientry['sec_ip'])
                    secentry = ientry.copy()
                    secentry['ip'] = ientry['sec_ip']
                    secentry['gateway'] = ientry['sec_gateway']
                    secentry['network'] = ipaddress.ip_network(secentry['ip'],strict=False)
                    ints.append(secentry)

    return ints

def parse_int(line, ientry):
    """Parse Individual Entry inside Interface"""

    nxip  = re.search('\s+ip\saddress\s(\d+.\d+.\d+.\d+)(/\d+)$', line)
    nxip_sec  = re.search('\s+ip\saddress\s(\d+.\d+.\d+.\d+)(/\d+) secondary$', line)
    nxhsrp = re.search('\s\s\s\s+ip\s(\d+.\d+.\d+.\d+)', line)
    catip = re.search('\s+ip address\s(\d+.\d+.\d+.\d+)\s+(255.\d+.\d+.\d+)$', line)
    catip_sec = re.search('\s+ip address\s(\d+.\d+.\d+.\d+)\s+(255.\d+.\d+.\d+) secondary$', line)
    cathsrp = re.search('\s+standby\s\d+\sip\s(\d+.\d+.\d+.\d+)', line)
    nxvrf = re.search('\s+vrf member (\w+)', line)
    catvrf = re.search('\s+ip vrf forwarding (\w+)', line)
    descre = re.search('\s+description\s+\[\s*(.*)\s*\]', line)

    # Nexus IP
    if nxip:
        ientry['ip'] = nxip.group(1) + nxip.group(2)
        ientry['gateway'] = nxip.group(1)
        if re.search(p2p_regex, nxip.group(1)):
            ientry['p2p'] = True
        else:
            ientry['p2p'] = False

    # Nexus Secondary
    elif nxip_sec:
        ientry['sec_ip'] = nxip_sec.group(1) + nxip_sec.group(2)
        ientry['sec_gateway'] = nxip_sec.group(1)

    # Nexus HSRP
    elif nxhsrp:
        network = ipaddress.ip_network(ientry['ip'],strict=False)
        if ipaddress.ip_address(nxhsrp.group(1)) in ipaddress.ip_network(network):
            ientry['gateway'] = nxhsrp.group(1)

        if 'sec_ip' in ientry.keys():
            network = ipaddress.ip_network(ientry['sec_ip'],strict=False)
            if ipaddress.ip_address(nxhsrp.group(1)) in ipaddress.ip_network(network):
                if DEBUG:
                    print("HSRP Gateway", nxhsrp.group(1), ientry['sec_ip'])
                ientry['sec_gateway'] = nxhsrp.group(1)

    # IOS Network Search
    elif catip:
        ientry['ip'] = catip.group(1) + "/" + catip.group(2)
        ientry['gateway'] = catip.group(1)
        if re.search(p2p_regex, catip.group(1)):
            ientry['p2p'] = True
        else:
            ientry['p2p'] = False

    # Secondary IP Network Search
    elif catip_sec:
        if not re.search('10\.23\.', catip_sec.group(1)):
            ientry['sec_ip'] = catip_sec.group(1) + "/" + catip_sec.group(2)
            ientry['sec_gateway'] = catip_sec.group(1)

    # IOS HSRP
    elif cathsrp:
        network = ipaddress.ip_network(ientry['ip'],strict=False)
        if ipaddress.ip_address(cathsrp.group(1)) in ipaddress.ip_network(network):
            ientry['gateway'] = cathsrp.group(1)

        if 'sec_ip' in ientry.keys():
            network = ipaddress.ip_network(ientry['sec_ip'],strict=False)
            if ipaddress.ip_address(cathsrp.group(1)) in ipaddress.ip_network(network):
                ientry['sec_gateway'] = cathsrp.group(1)

    elif nxvrf:
        ientry['vrf'] = nxvrf.group(1)
    elif catvrf:
        ientry['vrf'] = catvrf.group(1)
    elif descre:
        ientry['desc'] = descre.group(1)


    return ientry


def get_vlans(device):
    """Get the VLANs off a device"""

    conf_file = conf_dir + device['Device'] + "-confg"
    stp = dict()

    if device['MgmtGroup'] != 'None':

        try:
            parse = CiscoConfParse(conf_file)
        except:
            print("Warning, could not load config for ", conf_file)
            return
        else:
            vdb = parse_vlans(parse, device['Device'])

            stp_en = parse.find_objects('^spanning-tree\svlan\s(.*)\spriority\s(\d+)')
            for s in stp_en:
                catstp = re.search('^spanning-tree\svlan\s(.*)\spriority\s(\d+)', s.text)
                stp = getSTP(stp, catstp.group(1), catstp.group(2))

            stp_en = parse.find_objects('^\s*vlan\s+(.*)root\spriority\s(\d+)')
            for s in stp_en:
                peerstp = re.search('^\s*vlan\s+(.*)root\spriority\s(\d+)', s.text)
                stp = getSTP(stp, peerstp.group(1), peerstp.group(2))

            # for en in stp:
            #     print(device['Device'], en, stp[en])
            for vid in vdb.keys():
                stpval = 0
                name = vdb[vid]['name']
                if vid in stp.keys():
                    stpval = stp[vid]
                #print(device['MgmtGroup'],vid,name,device['Device'],stpval)

                saveVLAN(device['MgmtGroup'],vid,name,device['Device'],stpval)


def parse_vlans(parse, switch):
    """Parse config for VLANs"""

    vdb = dict()

    #vlans = parse.find_parents_w_child("^vlan", )
    vlans = parse.find_objects("^vlan (\d+)")

    for v in vlans:
        ventry = dict()

        # vlan 1,2,3,4
        vlist = re.search(r'^vlan\s+(\d+)(,\d+)+', v.text)

        # vlan 1-3
        vrange = re.search(r'^vlan\s+(\d+\-\d+)', v.text)

        # vlan 1,2,3-5,8-10 (ignore)
        nexus_list = re.search(r'^vlan\s+(\d+).*\-.*\,', v.text)

        if vlist:
            #print("VMATCH")
            vladd = vlist.group(1) + vlist.group(2)
            vla   = vladd.split(',')
            for v in vla:
                if vlow <= int(v) <= vhigh:
                    ve = dict()
                    ve['switch'] = switch
                    ve['name'] = 'NONAME'
                    ve['vid'] = str(v)
                    vdb[str(v)] = ve

        elif nexus_list:
            if DEBUG:
                print("Nexus List", v.text)

        elif vrange:
            (v_low, v_high) = get_vlan_range(vrange.group(1))
            #print("Found NoName Range",switch,v_low,v_high)

            while v_low <= v_high:
                if vlow <= int(v_low) <= vhigh:
                    ve = dict()
                    ve['switch'] = switch
                    ve['vid'] = str(v_low)
                    ve['name'] = 'NONAME'
                    vdb[str(v_low)] = ve
                    v_low = v_low + 1

        else:
            vid = v.text.replace('vlan ', '')
            vid = vid.replace(' ', '')

            if vlow <= int(vid) <= vhigh:
                ventry['vid'] = vid
                ventry['switch'] = switch
                vdb[ventry['vid']] = ventry

                # Name Search
                name = v.re_search_children(r'name')
                if name:
                    name_text = name.pop()
                    #print(name_text.text)
                    name_search = re.search(r'\s+name\s+(.*)', name_text.text)
                    if name_search:
                        ventry['name'] = name_search.group(1)
                        ventry['name'] = ventry['name'].replace(',', '')
                else:
                    ventry['name'] = 'NONAME'
                #print(name_text.text)

    return vdb


def getSTP(stp,vRange,priority):
    """Process STP Root Values"""

    # Strip spaces
    vRange = vRange.replace(' ', '')

    vr = vRange.split(',')

    for vlan in vr:
        #print(vlan, priority)
        if re.search('\-', vlan):
            (low, high) = vlan.split('-')
            #print("Range:",low,high,priority)
            for i in range(int(low), int(high) + 1):
                #print(i,priority)
                if int(priority) < 61440:
                    stp[str(i)] = priority
        else:
            #print(vlan,priority)
            stp[vlan] = priority

    return stp


# Write results to file
def save_vlan_file(data, out_file):

    save = open(out_file, "w")
    print("MGMT,VID,VName,Switch,STP", file=save)

    print(*sorted(data), sep='\n', file=save)
    save.close()


# Save vlan data to list
def saveVLAN(vlan,vid,vname,switch,stp):
    global vlan_list

    if DEBUG: print("Saving data: " + str(vlan) + "," + str(vid) + "," + str(vname) + "," + str(switch) + "," + str(stp))
    vlan_list.append(str(vlan) + "," + str(vid) + "," + str(vname) + "," + str(switch) + "," + str(stp))

# Write results to file
def save_int_file(out_file):

    save = open(out_file, "w")
    print("Subnet,VLAN,VRF,Router,Gateway,MGMT Group,Description,P2P,Standby", file=save)

    for i in interface_list:
        entry = str(i['network']) + ',' + str(i['vid']) + ',' +  i['vrf'] + ',' + i['device']
        entry += ',' + i['gateway'] + ',' + i['MgmtGroup'] + ',' + i['desc'] + ',' + str(i['p2p'])
        entry += ',' + str(i['Standby'])
        print(entry, sep='\n', file=save)
    save.close()

def save_device_file(out_file):
    save = open(out_file, "w")
    print("Device,Location", file=save)

    for d in device_list:
        entry = d['Device'] + ',' + d['Location']
        print(entry, sep='\n', file=save)

## Process Arguments to generate output
# Got VLAN Range and Switch Name
if args.df:

    devdb = loadDevicelist(args.df)

    # Process each device
    for en in devdb:
        # VLAN File
        if args.vfile:
            # L2 VLAN Range
            if args.vr:
                process_vlans(args.vr)

            vlans = get_vlans(en)
            save_vlan_file(vlan_list, args.vfile)

        # Interface File
        if args.ifile:
            # L3 Vlan Range
            if args.ivr:
                process_vlans(args.ivr)

            get_interfaces(en)
            save_int_file(args.ifile)

        # Device info file
        if args.dfile:
            get_device_info(en)
            save_device_file(args.dfile)

# Print Help
else:
    parser.print_help()
    print()