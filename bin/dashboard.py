#!/usr/bin/env python3
# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-10: license notices and update metadata; existing behavior retained.
"""Dispatch an existing dashboard in the selected language."""
import html
import io
import os
from pathlib import Path
import runpy
import sys
from urllib.parse import parse_qs
import audiodek_language as language

def main():
    method = os.environ.get('REQUEST_METHOD', 'GET').upper()
    raw = ''
    if method == 'POST':
        raw = sys.stdin.read(int(os.environ.get('CONTENT_LENGTH', '0') or 0))
    query = parse_qs(raw if method == 'POST' else os.environ.get('QUERY_STRING', ''), keep_blank_values=True)
    get = lambda key: query.get(key, [''])[0]
    selected = language.current_language()
    message = ''
    if method == 'POST' and get('action') == 'change_language':
        try:
            language.save_language(get('language'), get('language_token'))
            selected = get('language')
            message = 'Idioma guardado.' if selected == 'es' else 'Language saved.'
        except (OSError, ValueError) as error:
            message = html.escape(str(error))
        # A language request must never dispatch a configuration action.
        raw = ''
        os.environ['REQUEST_METHOD'] = 'GET'
        os.environ['QUERY_STRING'] = ''
        os.environ['CONTENT_LENGTH'] = '0'
    elif method == 'POST' and get('_ui_language') in ('en', 'es'):
        selected = get('_ui_language')
    sys.stdin = io.StringIO(raw)
    esc = html.escape
    label = 'Guardar idioma' if selected == 'es' else 'Save language'
    hint = ('Cambiar el idioma no modifica las habitaciones ni los backups.' if selected == 'es'
            else 'Changing language does not modify rooms or backups.')
    try:
        preference_token = language.token()
    except OSError:
        preference_token = ''
        message = ('No se puede guardar el idioma: comprueba los permisos de AudioDek.' if selected == 'es'
                   else 'Cannot save language: check AudioDek permissions.')
    print('<div style="max-width:1180px;margin:12px auto;padding:12px;border:1px solid #ddd;border-radius:10px">')
    print('<form action="index.cgi" method="post" data-ajax="false"><input type="hidden" name="action" value="change_language">')
    print('<input type="hidden" name="language_token" value="'+esc(preference_token)+'"><label>Language / Idioma<select name="language">')
    for code, name in [('en', 'English'), ('es', 'Español')]:
        print('<option value="'+code+'"'+(' selected' if code == selected else '')+'>'+name+'</option>')
    print('</select></label><button type="submit">'+label+'</button></form><p>'+hint+'</p>')
    if message:
        print('<p role="status">'+message+'</p>')
    print('</div>')
    folder = Path(__file__).resolve().parent / 'languages' / selected
    sys.path.insert(0, str(folder))
    runpy.run_path(str(folder / 'dashboard.py'), run_name='__main__')

if __name__ == '__main__':
    main()
