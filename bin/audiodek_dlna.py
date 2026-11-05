# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
"""Use Sonn's local admin discovery, never a browser-supplied address."""
from urllib.parse import urlsplit
import ipaddress

def candidates(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('devices'), list):
        raise ValueError('Invalid DLNA inventory / Inventario DLNA no válido.')
    found = {}
    for row in payload['devices']:
        if not isinstance(row, dict):
            continue
        try:
            ip = ipaddress.IPv4Address(row.get('address') or row.get('host') or '')
            if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local or int(ip) == 0xffffffff:
                continue
            url = urlsplit(row.get('controlUrl') or '')
            if url.scheme != 'http' or url.hostname != str(ip) or url.username or url.password or url.fragment:
                continue
            if not url.port or url.port == 7090:
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        identifier = row.get('id')
        if not isinstance(identifier, str) or not 0 < len(identifier) <= 256:
            continue
        name = str(row.get('name') or ip).strip()[:100] or str(ip)
        found[identifier] = {'name':name, 'host':str(ip), 'player_id':identifier}
    return found

def scan(discovery, folder):
    token = discovery.read_token(folder)
    if not token:
        raise ValueError('Connect to Sonn first / Conecta primero con Sonn.')
    return candidates(discovery.request('/transports/dlna/devices', token, timeout=25))
