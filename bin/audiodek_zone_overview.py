# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
from html import escape

STRINGS = {
    'de': ('Zonen mit laufender Wiedergabe', 'DLNA-Zonen', 'Squeezelite-Zonen',
           'Andere Zonen und Zonen ohne Ausgang', 'Raum', 'Ausgang', 'Player',
           'IP / Host', 'Wiedergabestatus', 'Soloist', 'Wiedergabe läuft',
           'Pausiert', 'Gestoppt', 'Nicht verfügbar', 'Aktiv', 'Nicht erkannt',
           'Kein Ausgang', 'Keine Zonen in diesem Abschnitt.',
           'Der Wiedergabestatus konnte nicht von Sonn abgerufen werden.',
           'Sonn-Status beim Aktualisieren. Ein aktiver Soloist-Prozess bestätigt keinen hörbaren Ton.'),

    'es': ('Zonas en reproducción', 'Zonas DLNA', 'Zonas Squeezelite',
           'Otras zonas y zonas sin salida', 'Habitación', 'Salida',
           'Reproductor', 'IP / Host', 'Estado de reproducción', 'Soloist',
           'Reproduciendo', 'En pausa', 'Detenida', 'No disponible',
           'Activo', 'No detectado', 'Sin salida', 'No hay zonas en este apartado.',
           'No se ha podido consultar la reproducción en Sonn.',
           'Estado indicado por Sonn al actualizar la página. Soloist activo no confirma que haya sonido.'),
    'en': ('Playing zones', 'DLNA zones', 'Squeezelite zones',
           'Other zones and zones without an output', 'Room', 'Output',
           'Player', 'IP / Host', 'Playback state', 'Soloist',
           'Playing', 'Paused', 'Stopped', 'Unavailable',
           'Active', 'Not observed', 'No output', 'No zones in this section.',
           'Could not read playback state from Sonn.',
           'Status reported by Sonn when the page is refreshed. An active Soloist process does not confirm audible sound.'),
}

def live_states(discovery):
    try:
        payload = discovery.request('/api/v1/zones')
        if not isinstance(payload, dict) or not isinstance(payload.get('zones'), list):
            return None
        return {str(z['id']): z['state'] for z in payload['zones']
                if isinstance(z, dict) and 'id' in z
                and z.get('state') in ('playing', 'paused', 'stopped')}
    except discovery.DiscoveryError:
        return None

def partition(zones, states):
    groups = {'dlna': [], 'squeezelite': [], 'other': [], 'playing': []}
    for z in zones:
        protocol = z['output_id'].strip().lower()
        groups[protocol if protocol in ('dlna', 'squeezelite') else 'other'].append(z)
        if (states or {}).get(str(z['id'])) == 'playing':
            groups['playing'].append(z)
    return groups

def render(groups, states, solo, lang):
    l = STRINGS[lang]
    labels = dict(playing=l[10], paused=l[11], stopped=l[12])
    e = lambda value: escape(str(value if value is not None else ''))
    for index, key in enumerate(('playing', 'dlna', 'squeezelite', 'other')):
        rows = groups[key]
        if key == 'other' and not rows:
            continue
        count = ' — '+str(len(rows)) if key != 'playing' or states is not None else ''
        print('<section class="at-box" id="audiodek-zones-'+key+'"><h2>'+l[index]+count+'</h2>')
        if key == 'playing':
            print('<p>'+l[19]+'</p>')
            if states is None:
                print('<p class="at-wa">'+l[18]+'</p></section>')
                continue
        if not rows:
            print('<p>'+l[17]+'</p></section>')
            continue
        print('<div style="overflow-x:auto"><table class="at-table"><thead><tr>'+''.join('<th scope="col">'+v+'</th>' for v in l[4:10])+'</tr></thead><tbody>')
        for z in rows:
            zid = str(z['id'])
            protocol = z['output_id'].lower()
            output = {'dlna':'DLNA', 'squeezelite':'Squeezelite'}.get(protocol, z['output_id'] or l[16])
            state = (states or {}).get(zid)
            process = l[14] if zid in solo else l[15]
            cells = ('#'+zid+' '+z['name'], output, z['playerName'] or '—',
                     z['host'] or '—', labels.get(state,l[13]), process)
            print('<tr>'+''.join('<td>'+e(v)+'</td>' for v in cells)+'</tr>')
        print('</tbody></table></div></section>')
