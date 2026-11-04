"""Allowlisted, argument-free WING OSC name queries only. No setter API."""
import ipaddress
import socket
import time

STRIPS=tuple([f'ch/{n}' for n in range(1,41)]+[f'aux/{n}' for n in range(1,9)])

def osc_string(value):
    raw=value.encode('utf-8')+b'\0'
    return raw+b'\0'*((-len(raw))%4)

def name_query(strip,effective=True):
    if strip not in STRIPS:raise ValueError('Only known WING input-strip names may be queried.')
    return osc_string('/'+strip+('/$name' if effective else '/name'))+b',\0\0\0'

def parse_name(packet):
    def read_string(offset):
        end=packet.index(b'\0',offset)
        value=packet[offset:end].decode('utf-8',errors='replace')
        return value,(end+4)&~3
    try:
        address,offset=read_string(0);tags,offset=read_string(offset)
        if tags!=',s':return None
        strip,leaf=address[1:].rsplit('/',1)
        if strip not in STRIPS or leaf not in ('$name','name'):return None
        name,_=read_string(offset)
        return strip,name[:128]
    except (ValueError,IndexError):return None

def fetch_names(ip):
    address=ipaddress.IPv4Address(ip)
    if address.is_multicast or address.is_unspecified or str(address)=='255.255.255.255':
        raise ValueError('Enter the console\'s unicast IPv4 address.')
    result={}
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.settimeout(.04)
        for effective in (True,False):
            missing=[s for s in STRIPS if s not in result]
            for i in range(0,len(missing),8):
                expected=set(missing[i:i+8])
                for strip in missing[i:i+8]:sock.sendto(name_query(strip,effective),(str(address),2223))
                deadline=time.monotonic()+.20
                while time.monotonic()<deadline:
                    try:packet,peer=sock.recvfrom(4096)
                    except socket.timeout:continue
                    if peer!=(str(address),2223):continue
                    value=parse_name(packet)
                    if value:result[value[0]]=value[1]
                    if expected.issubset(result):break
    if not result:raise RuntimeError('No name replies received. Check IP, network reachability, and the console OSC remote lock.')
    return result
