from collections import namedtuple

import datetime
import json
import os
import re
import socket

from lib.components import shared


_SSHKey = namedtuple('SSHKey', ['file', 'type', 'fingerprint', 'size'])
_SSHSession = namedtuple('SSHSession', ['username', 'active_since', 'ip'])
_ConnectionStatus = namedtuple('ConnectionStatus', [
    'l3_name',
    'l4_name',
    'src_addr',
    'src_port',
    'dest_addr',
    'dest_port',
    'rx',
    'tx',
    'state',
    'ttl',
])
_FixedLease = namedtuple('FixedLease', [
    'mac',
    'ip',
    'enabled',
    'next_server',
    'filename',
    'root_path',
    'remark',
])
_VulnerabilityLookup = namedtuple('VulnerabilityLookup', [
    'description',
    'cves'])
_KnownVulnerability = namedtuple('KnownVulnerability', [
    'name',
    'description',
    'cves',
    'vulnerability_status',
    'vulnerability_description',
])

_VULNERABILITY_STATUS = {
    'Not affected': 'NOT_AFFECTED',
    'Vulnerability: ': 'VULNERABLE',
    'Mitigation: ': 'MITIGATED',
}

_VULNERABILITIES = {
    'l1tf': _VulnerabilityLookup(
        description='Foreshadow',
        cves=['CVE-2018-3620'],
    ),
    'mds': _VulnerabilityLookup(
        description='Fallout/ZombieLoad/RIDL',
        cves=[
            'CVE-2018-12126',
            'CVE-2018-12130',
            'CVE-2018-12127',
            'CVE-2019-11091']
    ),
    'meltdown': _VulnerabilityLookup(
        description='Meltdown',
        cves=['CVE-2017-5754'],
    ),
    'spec_store_bypass': _VulnerabilityLookup(
        description='Spectre Variant 4',
        cves=['CVE-2018-3639'],
    ),
    'spectre_v1': _VulnerabilityLookup(
        description='Spectre Variant 1',
        cves=['CVE-2017-5753'],
    ),
    'spectre_v2': _VulnerabilityLookup(
        description='Spectre Variant 2',
        cves=['CVE-2017-5715'],
    ),
}


def _generate_vulnerabilities():
  c = []
  vuln_dir = '/sys/devices/system/cpu/vulnerabilities/'
  for v in os.listdir(vuln_dir):
    data = shared.get_sys_output(
        'cat {path}'.format(path=os.path.join(vuln_dir, v)))
    m = re.match(
        '^(?P<status>(Not affected|Vulnerable: |Mitigation: ))(?P<description>.*)$',
        data)
    c.append(_KnownVulnerability(
        name=v,
        vulnerability_status=_VULNERABILITY_STATUS[
            m.groupdict().get('status', '')],
        vulnerability_description=m.groupdict().get('description', ''),
        **_VULNERABILITIES.get(
            v, _VulnerabilityLookup(description='', cves=[]))._asdict()
    )._asdict())
  return c


def _generate_ssh_sessions():
  return [
      _SSHSession(
          username=username,
          active_since=str(
              datetime.datetime.strptime(
                  '{date} {time}'.format(date=date_since, time=time_since),
                  '%Y-%m-%d %H:%M')),
          ip=ip.strip('()'),
      )._asdict() for (username, _, date_since, time_since, ip) in [
        l.split() for l in shared.get_sys_output('who -s').split('\n')
      ]
  ]


def _generate_ssh_keys():
  return [
      _SSHKey(
          file=fn,
          type=type,
          size=int(shared.get_sys_output(
              '/usr/bin/ssh-keygen -lf {file}  | cut -d" " -f1'.format(
                  file=fn))),
          fingerprint=shared.get_sys_output(
              '/usr/bin/ssh-keygen -lf {file}  | cut -d" " -f2'.format(
                  file=fn)),
      )._asdict() for (fn, type) in set([
          ('/etc/ssh/ssh_host_key.pub', 'RSA1'),
          ('/etc/ssh/ssh_host_rsa_key.pub', 'RSA2'),
          ('/etc/ssh/ssh_host_dsa_key.pub', 'DSA'),
          ('/etc/ssh/ssh_host_ecdsa_key.pub', 'ECDSA'),
          ('/etc/ssh/ssh_host_ed25519_key.pub', 'ED25519'),
      ])
      if os.path.exists(fn)
  ]


def _process_connection(conn_entry):
  l4_protocol_name_lookup = {
      int(protocol_number): protocol_name[8:].upper()
      for (protocol_name, protocol_number) in vars(socket).items()
      if protocol_name.startswith('IPPROTO')
  }

  l3_protocol_name_translate = {
      'IPV6': 'IPv6',
      'IPV4': 'IPv4',
  }

  conn_entry_parts = conn_entry.split()

  (l3_protocol_name, _, _, l4_protocol_number, ttl) = conn_entry_parts[0:5]

  l3_protocol_name = l3_protocol_name_translate.get(
      l3_protocol_name.upper(),
      l3_protocol_name.upper()
  )

  l4_protocol_name = l4_protocol_name_lookup.get(
      int(l4_protocol_number),
      l4_protocol_number).upper()

  src_addr_entries = [
      e.split('=')[-1] for e in conn_entry_parts if e.startswith('src=')]
  src_port_entries = [
      int(e.split('=')[-1]) for e in conn_entry_parts if e.startswith(
          'sport=')]
  dest_addr_entries = [
      e.split('=')[-1] for e in conn_entry_parts if e.startswith('dst=')]
  dest_port_entries = [
      int(e.split('=')[-1]) for e in conn_entry_parts if e.startswith(
          'dport=')]
  (tx, rx) = [
      int(e.split('=')[-1]) for e in conn_entry_parts if e.startswith(
          'bytes=')]

  return _ConnectionStatus(
      l3_name=l3_protocol_name,
      l4_name=l4_protocol_name,
      src_addr=src_addr_entries,
      src_port=src_port_entries,
      dest_addr=dest_addr_entries,
      dest_port=dest_port_entries,
      rx=rx,
      tx=tx,
      state=conn_entry_parts[5].upper() if l4_protocol_name == 'TCP' else '',
      ttl=int(ttl),
  )._asdict()


def _generate_connections():
  return [
      _process_connection(c) for c in shared.get_sys_output(
          '/usr/local/bin/getconntracktable').split('\n') if c]


def _generate_dhcp_leases():
  with open('config/ipfire_shim.json') as fp:
    ipfire_root = json.loads(fp.read())['ipfire_root']

  return {
      'fixed': [
          _FixedLease(*l.split(','))._asdict() for l in shared.get_sys_output(
              'cat {ipfire_root}/dns/fixleases'.format(
                  ipfire_root=ipfire_root))
      ],
      'dynamic': [],
  }


def get_statuses():
  return {
    shared.Component.REMOTE: {
        'keys': _generate_ssh_keys(),
        'sessions': _generate_ssh_sessions(),
    },
    shared.Component.VULNERABILITY: _generate_vulnerabilities(),
    shared.Component.CONNECTIONS: _generate_connections(),
    shared.Component.DHCP: _generate_dhcp_leases(),
  }
