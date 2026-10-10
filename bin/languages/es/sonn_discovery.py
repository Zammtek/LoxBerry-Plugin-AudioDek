# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-10: license notices and update metadata; existing behavior retained.
"""Authenticated, local-only Sonn inventory; never edits audio configuration."""
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
            raise DiscoveryError('La respuesta de Sonn es demasiado grande.')
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise DiscoveryError('Acceso a Sonn pendiente o caducado. Conecta con una cuenta administradora de Sonn.') from None
        raise DiscoveryError('Sonn no permite esta consulta (HTTP %s). Comprueba su versión y acceso.' % exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DiscoveryError('No se puede consultar Sonn en el puerto local 7090. Comprueba Audioserver4Home y que Sonn esté en marcha.') from None
    except (ValueError, UnicodeError):
        raise DiscoveryError('Sonn devolvió una respuesta no válida.') from None

def session_path(folder):
    return os.path.join(folder, '.sonn-inventory-session')

def read_token(folder):
    try:
        with open(session_path(folder), encoding='utf-8') as f:
            token = f.read(513)
        return token if re.fullmatch(r'[A-Za-z0-9_-]{16,512}', token) else ''
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
        raise DiscoveryError('Introduce el usuario y la contraseña de administración de Sonn.')
    result = request('/auth/login', body={'username': username.strip(), 'password': password})
    token = result.get('token', '') if isinstance(result, dict) else ''
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,512}', token):
        raise DiscoveryError('Sonn no entregó una sesión válida.')
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
        raise DiscoveryError('El inventario de Sonn no tiene el formato esperado.')
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
        if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', pid):
            continue
        if pid in seen:
            raise DiscoveryError('Sonn informa de un playerId repetido. Revisa la identidad de los reproductores.')
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
        raise DiscoveryError('El reproductor seleccionado ya no está conectado. Actualiza y selecciónalo otra vez.')
    if not client['valid_ip']:
        raise DiscoveryError('Este reproductor no anuncia una IP IPv4 válida para la asignación actual.')
    if any(owner != str(zid) for owner in client['owners']):
        raise DiscoveryError('Este reproductor ya está asignado a otra habitación.')
    return {k: client[k] for k in ('name', 'host', 'player_id')}

def diagnose(zones, active, clients, error, config_ok, running, writable):
    checks = []
    def add(status, title, action):
        checks.append((status, title, action))
    add('ok' if config_ok else 'warning', 'Configuración de Sonn',
        'Configuración legible.' if config_ok else 'Comprueba la instalación de Audioserver4Home y su configuración.')
    add('ok' if running else 'warning', 'Servicio Sonn',
        'Sonn está en marcha.' if running else 'Abre Audioserver4Home y comprueba el servicio antes de asignar reproductores.')
    add('ok' if writable else 'warning', 'Permisos para aplicar cambios',
        'La carpeta de configuración permite guardar cambios.' if writable else 'Revisa los permisos de la carpeta de configuración; AudioDek no puede aplicar cambios.')
    add('warning' if error else 'ok', 'Consulta de reproductores', error or
        ('Sonn informa de %s reproductores conectados.' % sum(p['connected'] for p in clients)))
    if not zones:
        add('warning', 'Habitaciones', 'Crea el bloque de audio en Loxone Config, envía al Miniserver y pulsa Actualizar.')
    connected = {p['player_id'] for p in clients if p['connected']}
    for z in zones:
        output = z.get('output') or {}
        title = '#%s %s' % (z.get('id'), z.get('name', ''))
        if not output:
            add('pending', title, 'Pendiente de reproductor. Cuando tengas el equipo, instala piCorePlayer, conéctalo a Sonn y selecciónalo aquí.')
        elif isinstance(output, dict) and output.get('id') == 'squeezelite':
            if str(z['id']) not in active:
                add('warning', title, 'No se observa el proceso Soloist. Comprueba el servicio y sus registros en Audioserver4Home.')
            elif error:
                add('pending', title, 'Salida configurada y Soloist activo; falta comprobar la conexión del reproductor con Sonn.')
            elif str(output.get('playerId', '')).lower() not in connected:
                add('warning', title, 'Configurado pero no conectado a Sonn. Comprueba alimentación, red y servidor configurado en piCorePlayer.')
            else:
                add('ok', title, 'Reproductor conectado a Sonn y Soloist activo. Esto no verifica que los altavoces estén sonando.')
        else:
            add('pending', title, 'Salida de otro tipo. Consulta su configuración en Sonn.')
    return checks
