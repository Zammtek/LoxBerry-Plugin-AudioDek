# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-10: license notices and update metadata; existing behavior retained.
"""UI preference only. Never reads or writes Sonn configuration."""
import configparser
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile

FOLDER = Path('/opt/loxberry/config/plugins/audiodek')
SYSTEM = Path('/opt/loxberry/config/system')

def normalize(value):
    code = str(value or '').strip().lower().replace('_', '-').split('-')[0]
    return code if code in ('en', 'es') else 'en'

def default_language():
    try:
        data = json.loads((SYSTEM / 'general.json').read_text(encoding='utf-8'))
        base = data.get('BASE', data.get('base', {}))
        value = base.get('LANG', base.get('lang'))
        if value:
            return normalize(value)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    try:
        cfg = configparser.ConfigParser(interpolation=None, strict=False)
        cfg.read(SYSTEM / 'general.cfg', encoding='utf-8')
        return normalize(cfg.get('BASE', 'LANG', fallback='en'))
    except (OSError, configparser.Error):
        return 'en'

def current_language():
    try:
        data = json.loads((FOLDER / 'language.json').read_text(encoding='utf-8'))
        if data.get('language') in ('en', 'es'):
            return data['language']
    except (OSError, ValueError, AttributeError):
        pass
    return default_language()

def token():
    FOLDER.mkdir(parents=True, exist_ok=True)
    keyfile = FOLDER / '.language-key'
    try:
        fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(secrets.token_bytes(32))
    return hmac.new(keyfile.read_bytes(), b'audiodek-language-v1', hashlib.sha256).hexdigest()

def save_language(language, supplied_token):
    if language not in ('en', 'es') or not hmac.compare_digest(token(), str(supplied_token)):
        raise ValueError('Invalid language request / Solicitud de idioma no válida.')
    fd, temporary = tempfile.mkstemp(prefix='.language-', dir=FOLDER)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'language': language}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, FOLDER / 'language.json')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
