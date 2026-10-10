# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-10: license notices and update metadata; existing behavior retained.
'Authenticated, local-only Sonn inventory; never edits audio configuration.'
import json
import os
import re
import ipaddress
import tempfile
import urllib.request
import urllib.error

BASE = 'http://127.0.0.1:7090/admin/api'

class DiscoveryError(Exception):
    pass

def request(path, token='', body=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    # Ignore environment proxies and refuse redirects (credentials stay local).
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=3) as response:
            raw = response.read(1048577)
        if len(raw) > 1048576:
            raise DiscoveryError("Sonn's response is too large.")
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise DiscoveryError('Sonn access is required or has expired. Connect with a Sonn administrator account.') from None
        raise DiscoveryError('Sonn refused this query (HTTP %s). Check its version and access settings.' % exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DiscoveryError('Cannot query Sonn on local port 7090. Check Audioserver4Home and that Sonn is running.') from None
    except (ValueError, UnicodeError):
        raise DiscoveryError('Sonn returned an invalid response.') from None

def session_path(folder):
    return os.path.join(folder, '.sonn-inventory-session')

def read_token(folder):
    try:
        with open(session_path(folder), encoding='utf-8') as f:
            token = f.read(513)
        return token if re.fullmatch('[A-Za-z0-9_-]{16,512}', token) else ''
    except OSError:
        return ''

def disconnect(folder):
    token = read_token(folder)
    try:
        if token:
            request('/auth/logout', token, {})
    except DiscoveryError:
        pass
    try:
        os.unlink(session_path(folder))
    except FileNotFoundError:
        pass

def connect(folder, username, password):
    if not username.strip() or not password or len(username) > 256 or len(password) > 256:
        raise DiscoveryError('Enter your Sonn administrator username and password.')
    result = request('/auth/login', body={'username': username.strip(), 'password': password})
    token = result.get('token', '') if isinstance(result, dict) else ''
    if not isinstance(token, str) or not re.fullmatch('[A-Za-z0-9_-]{16,512}', token):
        raise DiscoveryError('Sonn did not return a valid session.')
    os.makedirs(folder, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.sonn-session-', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(token)
        os.replace(temp, session_path(folder))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def normalize(payload, zones):
    if not isinstance(payload, dict) or not isinstance(payload.get('clients'), list):
        raise DiscoveryError("Sonn's inventory has an unexpected format.")
    owners = {}
    for zone in zones:
        output = zone.get('output') or {}
        if isinstance(output, dict) and output.get('id') == 'squeezelite':
            owners.setdefault(str(output.get('playerId', '')).lower(), []).append(str(zone['id']))
    result = []
    seen = set()
    for client in payload['clients']:
        if not isinstance(client, dict):
            continue
        pid = str(client.get('playerId') or client.get('id') or '').lower()
        if not re.fullmatch('[0-9a-f]{2}(?::[0-9a-f]{2}){5}', pid):
            continue
        if pid in seen:
            raise DiscoveryError('Sonn reports a duplicate playerId. Check player identities.')
        seen.add(pid)
        host = str(client.get('address') or '')
        if host.startswith('::ffff:'):
            host = host[7:]
        try:
            ipaddress.IPv4Address(host)
            valid_ip = True
        except ValueError:
            valid_ip = False
        name = str(client.get('name') or pid)[:100]
        result.append({'player_id': pid, 'name': name, 'host': host,
                       'connected': client.get('connected') is True,
                       'valid_ip': valid_ip, 'owners': owners.get(pid, [])})
    return result

def inventory(folder, zones):
    try:
        clients = normalize(request('/transports/squeezelite/clients', read_token(folder)), zones)
        return clients, ''
    except DiscoveryError as exc:
        return [], str(exc)

def select(clients, pid, zid):
    client = next((p for p in clients if p['player_id'] == pid), None)
    if not client or not client['connected']:
        raise DiscoveryError('The selected player is no longer connected. Refresh and select it again.')
    if not client['valid_ip']:
        raise DiscoveryError('This player does not report a valid IPv4 address for assignment.')
    if any(owner != str(zid) for owner in client['owners']):
        raise DiscoveryError('This player is already assigned to another room.')
    return {k: client[k] for k in ('name', 'host', 'player_id')}

def diagnose(zones, active, clients, error, config_ok, running, writable):
    checks = []
    def add(status, title, action):
        checks.append((status, title, action))
    add('ok' if config_ok else 'warning', 'Sonn configuration',
        'Configuration is readable.' if config_ok else 'Check the Audioserver4Home installation and configuration.')
    add('ok' if running else 'warning', 'Sonn service',
        'Sonn is running.' if running else 'Open Audioserver4Home and check the service before assigning players.')
    add('ok' if writable else 'warning', 'Permission to apply changes',
        'The configuration directory allows changes to be saved.' if writable else 'Check configuration directory permissions; AudioDek cannot apply changes.')
    add('warning' if error else 'ok', 'Player query', error or
        ('Sonn reports %s connected players.' % sum(p['connected'] for p in clients)))
    if not zones:
        add('warning', 'Rooms', 'Create the audio block in Loxone Config, deploy to the Miniserver and click Refresh.')
    connected = {p['player_id'] for p in clients if p['connected']}
    for z in zones:
        output = z.get('output') or {}
        title = '#%s %s' % (z.get('id'), z.get('name', ''))
        if not output:
            add('pending', title, 'Waiting for a player. Set up piCorePlayer, connect it to Sonn and select it here when your device is ready.')
        elif isinstance(output, dict) and output.get('id') == 'squeezelite':
            if str(z['id']) not in active:
                add('warning', title, 'No Soloist process was observed. Check the service and its logs in Audioserver4Home.')
            elif error:
                add('pending', title, "Output configured and Soloist active; the player's connection to Sonn still needs checking.")
            elif str(output.get('playerId', '')).lower() not in connected:
                add('warning', title, "Configured but not connected to Sonn. Check power, network and piCorePlayer's server setting.")
            else:
                add('ok', title, 'Player connected to Sonn and Soloist active. This does not verify sound at the speakers.')
        else:
            add('pending', title, 'Another output type. Check its configuration in Sonn.')
    return checks
