# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-10: license notices and update metadata; existing behavior retained.
"""Room output transactions for Sonn 4.0.0-beta.19; no Loxone zone edits."""
import contextlib
import base64
import copy
import hashlib
import hmac
import ipaddress
import json
import os
import re
import stat
import subprocess
import tempfile
import tarfile
import datetime
import uuid
import time


def ticket_key(folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, '.room-output-key')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'wb') as f:
            f.write(os.urandom(32))
    with open(path, 'rb') as f:
        key = f.read()
    if len(key) != 32:
        raise RuntimeError('No se pudo leer la clave de confirmación.')
    return key


def issue_ticket(folder, data):
    payload = dict(data, expires=int(time.time()) + 900)
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
    signature = hmac.new(ticket_key(folder), body.encode(), hashlib.sha256).hexdigest()
    return body + '.' + signature


def verify_ticket(folder, token):
    try:
        body, signature = token.split('.')
        expected = hmac.new(ticket_key(folder), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(body))
        if data['expires'] < time.time():
            raise ValueError()
        return data
    except Exception:
        raise ValueError('La confirmación caducó o no es válida. Revisa de nuevo la operación.')


def read_config(path):
    with open(path, 'rb') as f:
        raw = f.read()
    cfg = json.loads(raw)
    if not isinstance(cfg, dict) or not isinstance(cfg.get('zones'), list):
        raise ValueError('La configuración no contiene una lista de zonas válida.')
    ids = [str(z.get('id')) for z in cfg['zones'] if isinstance(z, dict)]
    if len(ids) != len(cfg['zones']) or len(ids) != len(set(ids)):
        raise ValueError('Hay zonas inválidas o identificadores duplicados.')
    return cfg, hashlib.sha256(raw).hexdigest(), raw


def plan(cfg, zid, operation, name='', host='', player_id=''):
    result = copy.deepcopy(cfg)
    target = next((z for z in result['zones'] if str(z['id']) == str(zid)), None)
    if not target:
        raise ValueError('Selecciona una habitación existente.')
    current = target.get('output')
    if current is not None and (not isinstance(current, dict) or current.get('id') != 'squeezelite'):
        raise ValueError('Esta operación solo admite salidas Squeezelite o zonas sin salida.')
    if 'transports' in target:
        raise ValueError('La zona usa un formato antiguo de salidas; no se puede modificar aquí.')
    if operation == 'detach':
        if current is None:
            raise ValueError('La habitación ya está sin reproductor.')
        target['output'] = None
    elif operation == 'assign':
        name, host, player_id = name.strip(), host.strip(), player_id.strip().lower()
        if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
            raise ValueError('Introduce un nombre de reproductor válido (hasta 100 caracteres).')
        try:
            addr = ipaddress.IPv4Address(host)
            if addr.is_unspecified or addr.is_multicast or addr.is_loopback or int(addr) == 0xffffffff:
                raise ValueError()
        except ValueError:
            raise ValueError('Introduce una IP IPv4 válida para el reproductor.')
        if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', player_id):
            raise ValueError('Introduce una MAC válida.')
        mac = bytes.fromhex(player_id.replace(':', ''))
        if mac == bytes(6) or mac[0] & 1:
            raise ValueError('La MAC debe identificar un dispositivo individual.')
        for z in cfg['zones']:
            if str(z['id']) == str(zid):
                continue
            output = z.get('output') or {}
            if str(output.get('playerId', '')).lower() == player_id:
                raise ValueError('Esa MAC ya está asignada a otra habitación.')
            if host in (output.get('host'), output.get('address')):
                raise ValueError('Esa IP ya está asignada a otra habitación.')
        output = copy.deepcopy(current or {})
        output.update(id='squeezelite', playerId=player_id, playerName=name, host=host, address=host)
        target['output'] = output
        if target['output'] == current:
            raise ValueError('El reproductor ya tiene esos mismos datos.')
    else:
        raise ValueError('Operación desconocida.')
    return result, target


@contextlib.contextmanager
def operation_lock(folder):
    import fcntl
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, '.audiodek-operation.lock'), 'a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Hay otra operación de AudioDek en curso. Espera a que termine.')
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def atomic_write(path, raw):
    meta = os.stat(path)
    fd, temp = tempfile.mkstemp(prefix='.audiodek-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), stat.S_IMODE(meta.st_mode))
            if hasattr(os, 'fchown') and (meta.st_uid != os.getuid() or meta.st_gid != os.getgid()):
                # Sonn may save a root-owned 0644 file in a loxberry-owned folder.
                # A regular user can replace it, but cannot give the new file to root.
                # Keep the original owner where allowed; otherwise use the creator.
                try:
                    os.fchown(f.fileno(), meta.st_uid, meta.st_gid)
                except PermissionError:
                    pass
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def zone_signature(cfg):
    return {str(z['id']): {k: z.get(k) for k in ('name', 'sourceMac', 'sourceSerial', 'output')}
            for z in cfg['zones']}


def make_output_backup(path, folder, zone, operation, legacy_backup, run=subprocess.run):
    """Use the validated backup for existing data, or record verified absence."""
    zid = str(zone['id'])
    if not re.fullmatch(r'[1-9][0-9]*', zid):
        raise ValueError('El identificador de habitación no es válido.')
    # Probe only for an unassigned room; never replace existing Soloist data
    # with an empty backup merely because tar failed.
    data_path = '/app/data/soloist/zone-' + zid + '/data'
    probe = run(['sudo', 'docker', 'exec', 'sonn-core', 'sh', '-lc',
                 "if test -d '" + data_path + "'; then printf present; "
                 "elif test -e '" + data_path + "'; then exit 2; else printf absent; fi"],
                check=True, capture_output=True, text=True, timeout=10)
    state = probe.stdout.strip()
    if state == 'present':
        return legacy_backup(zone, operation)
    if state != 'absent':
        raise RuntimeError('No se pudo comprobar el estado de los datos Soloist. No se aplicó el cambio.')
    os.makedirs(folder, exist_ok=True)
    name = datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-zone-' + zid + '-' + operation + '-' + uuid.uuid4().hex[:8]
    dest = os.path.join(folder, name)
    os.mkdir(dest)
    _, _, raw = read_config(path)
    with open(os.path.join(dest, 'config.json'), 'wb') as f:
        f.write(raw)
    # A real empty tar.gz passes the existing tar preflight and records that
    # the room had no Soloist data. It is not a zero-byte failed archive.
    with tarfile.open(os.path.join(dest, 'soloist-data.tar.gz'), 'w:gz'):
        pass
    manifest = {'created':datetime.datetime.now().isoformat(timespec='seconds'),
                'operation':operation, 'zoneId':zid, 'room':zone.get('name', ''),
                'playerName':zone.get('playerName', ''), 'ip':zone.get('host', ''),
                'playerId':zone.get('playerId', ''), 'status':'backup_only',
                'soloistDataState':'absent', 'backupSchema':1}
    # Write manifest last so incomplete backups are not offered in the history.
    with open(os.path.join(dest, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return name


def apply(path, backup_folder, fingerprint, zid, operation, fields, services,
          run=subprocess.run, sleep=time.sleep, clock=time.monotonic, lock=operation_lock,
          write=atomic_write):
    with lock(backup_folder):
        cfg, actual_hash, raw = read_config(path)
        if actual_hash != fingerprint:
            raise RuntimeError('La configuración cambió. Revisa de nuevo la operación antes de confirmar.')
        updated, target = plan(cfg, zid, operation, **fields)
        image = run(['sudo', 'docker', 'inspect', 'sonn-core', '--format', '{{.Config.Image}}'],
                    check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        if image != 'ghcr.io/sonn-audio/core:4.0.0-beta.19':
            raise RuntimeError('Esta función está validada para Sonn 4.0.0-beta.19. No se ha cambiado nada.')
        if not services['docker_ok']():
            raise RuntimeError('Sonn debe estar en marcha antes de cambiar un reproductor.')
        if not os.access(os.path.dirname(path), os.W_OK | os.X_OK):
            raise RuntimeError('AudioDek no tiene permiso para reemplazar la configuración en su carpeta.')
        active_before = services['active']()
        parsed = next(z for z in services['parse'](cfg) if z['id'] == str(zid))
        original_zone = next(z for z in cfg['zones'] if str(z['id']) == str(zid))
        if operation == 'assign' and original_zone.get('output') is None:
            backup = make_output_backup(path, backup_folder, parsed, 'pre-output-assign', services['backup'], run)
        else:
            backup = services['backup'](parsed, 'pre-output-' + operation)
        _, backup_errors = services['validate'](backup)
        if backup_errors:
            raise RuntimeError('El backup previo no es válido; no se aplicó el cambio: ' + '; '.join(backup_errors))
        backup_cfg = os.path.join(backup_folder, backup, 'config.json')
        if read_config(backup_cfg)[1] != actual_hash or read_config(path)[1] != actual_hash:
            raise RuntimeError('La configuración cambió durante el backup. Revisa de nuevo la operación.')
        attempted_write = False
        error = None
        steps = ['Backup previo: ' + backup]

        def docker(command):
            args = ['sudo', 'docker', command]
            if command == 'stop':
                args += ['-t', '20']
            run(args + ['sonn-core'], check=True, capture_output=True, text=True, timeout=35)

        def verify(expected, active):
            if not services['wait'](45):
                raise RuntimeError('Sonn no quedó en marcha.')
            deadline = clock() + 60
            while True:
                current = read_config(path)[0]
                if zone_signature(current) == zone_signature(expected) and active.issubset(services['active']()):
                    return
                if clock() >= deadline:
                    raise RuntimeError('La configuración o los Soloist no superaron la verificación.')
                sleep(3)

        try:
            docker('stop')
            if read_config(path)[1] != actual_hash:
                raise RuntimeError('La configuración cambió antes de aplicar. Revisa de nuevo la operación.')
            attempted_write = True
            write(path, (json.dumps(updated, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            docker('start')
            expected_active = active_before - {str(zid)}
            if operation == 'assign':
                expected_active.add(str(zid))
            verify(updated, expected_active)
            steps.append('Salida verificada; habitaciones conservadas y Sonn en marcha')
        except Exception as exc:
            error = str(exc)
            if attempted_write:
                try:
                    docker('stop')
                    write(path, raw)
                    docker('start')
                    verify(cfg, active_before)
                    error += ' | Configuración anterior recuperada y verificada'
                except Exception as rollback:
                    error += ' | FALLO DE RECUPERACIÓN: ' + str(rollback)
        finally:
            ok, detail = services['ensure'](60)
            if not ok:
                error = (error + ' | ' if error else '') + 'Sonn no pudo recuperarse: ' + detail
        if error:
            raise RuntimeError(error + ' | Backup previo: ' + backup)
        return backup, steps
