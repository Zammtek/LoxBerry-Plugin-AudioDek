#!/usr/bin/env python3
# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-10: license notices and update metadata; existing behavior retained.
import json,os,re,html,subprocess,shutil,datetime,ipaddress
from urllib.parse import parse_qs
import room_outputs
import sonn_discovery
import audiodek_dlna
import audiodek_zone_overview

SONN='/opt/loxberry/data/plugins/audioserver4home/data/config.json'
SET='/opt/loxberry/config/plugins/audiodek/settings.json'
BACK='/opt/loxberry/data/plugins/audiodek/backups'

def load(p,d):
 try:
  with open(p,encoding='utf-8') as f:return json.load(f)
 except:return d

def E(x): return html.escape(str(x if x is not None else ''))

def backup_root():
 p='/opt/loxberry/data/plugins/audiodek/backups'
 os.makedirs(p,exist_ok=True)
 return p

def list_backups():
 out=[]
 for n in sorted(os.listdir(backup_root()), reverse=True):
  d=os.path.join(backup_root(),n); mf=os.path.join(d,'manifest.json')
  if os.path.isdir(d) and os.path.isfile(mf):
   m=load(mf,{})
   m['_name']=n
   out.append(m)
 return out

def make_zone_backup(z, operation):
 ts=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
 name=ts+'-zone-'+str(z['id'])+'-'+operation
 d=os.path.join(backup_root(),name)
 os.makedirs(d,exist_ok=False)
 shutil.copy2(SONN,os.path.join(d,'config.json'))
 src='/app/data/soloist/zone-%s/data'%z['id']
 archive=os.path.join(d,'soloist-data.tar.gz')
 cmd="test -d '%s' && tar -C '%s' -czf - . || true"%(src,src)
 with open(archive,'wb') as f:
  proc=subprocess.Popen(['sudo','docker','exec','sonn-core','sh','-lc',cmd],
                        stdout=f,stderr=subprocess.PIPE)
  _,err=proc.communicate(timeout=30)
  if proc.returncode!=0:
   raise RuntimeError('Could not copy Soloist data: '+err.decode(errors='ignore'))
 manifest={'created':datetime.datetime.now().isoformat(timespec='seconds'),
  'operation':operation,'zoneId':z['id'],'room':z['name'],
  'playerName':z['playerName'],'ip':z['host'],'playerId':z['playerId'],
  'status':'backup_only'}
 with open(os.path.join(d,'manifest.json'),'w',encoding='utf-8') as f:
  json.dump(manifest,f,indent=2,ensure_ascii=False)
 return name


def validate_backup(name):
 root=os.path.realpath(backup_root())
 d=os.path.realpath(os.path.join(root,name))
 if not d.startswith(root+os.sep) or not os.path.isdir(d):
  return None,['Invalid backup.']
 mf=os.path.join(d,'manifest.json'); cf=os.path.join(d,'config.json'); sf=os.path.join(d,'soloist-data.tar.gz')
 errors=[]
 m=load(mf,{})
 if not m: errors.append('manifest.json is missing or invalid.')
 try:
  cfg=load(cf,None)
  if not isinstance(cfg,dict): errors.append('Invalid config.json.')
 except: errors.append('Invalid config.json.')
 if not os.path.isfile(sf) or os.path.getsize(sf)==0: errors.append('soloist-data.tar.gz is missing or empty.')
 else:
  try:
   r=subprocess.run(['tar','-tzf',sf],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=10)
   if r.returncode: errors.append('soloist-data.tar.gz is damaged.')
  except Exception: errors.append('Could not verify soloist-data.tar.gz.')
 return (m,d),errors

def docker_ok():
 try:
  r=subprocess.run(['sudo','docker','inspect','-f','{{.State.Running}}','sonn-core'],capture_output=True,text=True,timeout=10)
  return r.returncode==0 and r.stdout.strip()=='true'
 except: return False

def wait_container(timeout=45):
 import time
 end=time.time()+timeout
 while time.time()<end:
  if docker_ok(): return True
  time.sleep(2)
 return False

def ensure_sonn_running(timeout=60):
 'Final safety net: never return from a restore leaving sonn-core stopped.'
 import time
 if docker_ok(): return True,'Sonn was already running'
 last=''
 for attempt in range(3):
  try:
   r=subprocess.run(['sudo','docker','start','sonn-core'],capture_output=True,text=True,timeout=35)
   last=(r.stdout+' '+r.stderr).strip()
  except Exception as e:
   last=str(e)
  end=time.time()+timeout
  while time.time()<end:
   if docker_ok(): return True,'Sonn recovered (attempt %d)'%(attempt+1)
   time.sleep(2)
 return False,last or 'Could not start sonn-core'

def active_soloist_zones():
 try:
  r=subprocess.run(['sudo','docker','exec','sonn-core','sh','-lc',
   "ps aux | grep '[s]oloist' | grep -v crashpad"],capture_output=True,text=True,timeout=10)
  return set(re.findall('/soloist/zone-(\\d+)/',r.stdout))
 except: return set()

def _restore_backup_core(name):
 info,errs=validate_backup(name)
 if errs: raise RuntimeError('; '.join(errs))
 m,d=info; zid=str(m.get('zoneId',''))
 z=next((x for x in zones if str(x['id'])==zid),None)
 if not z: raise RuntimeError('Current zone #'+zid+' does not exist; restore cancelled.')
 expected={str(x['id']) for x in zones if x.get('soloist')}
 steps=[]
 emergency=make_zone_backup(z,'pre-restore-emergency'); steps.append('✓ Emergency backup')
 current_cfg=SONN; backup_cfg=os.path.join(d,'config.json'); archive=os.path.join(d,'soloist-data.tar.gz')
 def restore_files(folder):
  shutil.copy2(os.path.join(folder,'config.json'),current_cfg)
  hd='/opt/loxberry/data/plugins/audioserver4home/data/soloist/zone-'+zid+'/data'
  shutil.rmtree(hd,ignore_errors=True); os.makedirs(hd,exist_ok=True)
  with open(os.path.join(folder,'soloist-data.tar.gz'),'rb') as f:
   q=subprocess.run(['tar','-xzf','-','-C',hd],stdin=f,capture_output=True,timeout=30)
   if q.returncode: raise RuntimeError('Error extracting Soloist data.')
 try:
  subprocess.run(['sudo','docker','stop','-t','20','sonn-core'],check=True,timeout=35,capture_output=True,text=True)
  steps.append('✓ Sonn stopped')
  restore_files(d); steps+=['✓ config.json restored','✓ Soloist zone-'+zid+'/data restored']
  subprocess.run(['sudo','docker','start','sonn-core'],check=True,timeout=35,capture_output=True,text=True)
  if not wait_container(45): raise RuntimeError('sonn-core did not remain running.')
  steps.append('✓ Sonn started')
  import time; time.sleep(12)
  cfg=load(SONN,{})
  actual={str(x.get('id')) for x in cfg.get('zones',[])}
  missing={str(x['id']) for x in zones}-actual
  if missing: raise RuntimeError('Missing zones after startup: '+','.join(sorted(missing)))
  steps.append('✓ %d zones detected'%len(zones))
  # Soloist can take time; require every zone that was active before restore.
  deadline=time.time()+45; active=set()
  while time.time()<deadline:
   active=active_soloist_zones()
   if expected.issubset(active): break
   time.sleep(3)
  absent=expected-active
  if absent: raise RuntimeError('Soloist not started in zone(s): '+','.join(sorted(absent)))
  steps.append('✓ Active Soloist processes: '+','.join(sorted(expected)))
  return emergency,steps
 except Exception as original:
  steps.append('✗ '+str(original)); steps.append('→ ROLLBACK')
  try:
   subprocess.run(['sudo','docker','stop','-t','20','sonn-core'],timeout=35,capture_output=True)
   ed=os.path.join(backup_root(),emergency); restore_files(ed)
   subprocess.run(['sudo','docker','start','sonn-core'],check=True,timeout=35,capture_output=True)
   if not wait_container(45): raise RuntimeError('Sonn did not start during rollback.')
   steps.append('✓ Rollback applied and Sonn started')
  except Exception as rb:
   steps.append('✗ ROLLBACK FAILED: '+str(rb))
  raise RuntimeError(' | '.join(steps))


def restore_backup_real(name):
 result=None; error=None
 try:
  result=_restore_backup_core(name)
 except Exception as e:
  error=e
 # Absolute final guard, independent from restore/rollback exceptions.
 ok,detail=ensure_sonn_running(60)
 if not ok:
  raise RuntimeError(('Restore/rollback: '+str(error)+' | ' if error else '')+
                     'CRITICAL FAILURE: sonn-core remained stopped and could not be recovered: '+detail)
 if error:
  raise RuntimeError(str(error)+' | ✓ Final safeguard: sonn-core running')
 emergency,steps=result
 steps.append('✓ Final safeguard: sonn-core running')
 return emergency,steps


def soloist_runtime():
 try:
  s=subprocess.check_output(
   ['sudo','docker','exec','sonn-core','sh','-lc',"ps aux | grep '[s]oloist'"],
   text=True,stderr=subprocess.STDOUT,timeout=5)
 except: s=''
 out={}
 for line in s.splitlines():
  z=re.search('/soloist/zone-(\\d+)/data',line)
  n=re.search('/soloist/soloist\\s+-n\\s+(.+?)\\s+-k\\s+',line)
  if z: out[z.group(1)] = n.group(1).strip() if n else 'Soloist'
 return out

def parse_zones(c):
 out=[]
 zones=c.get('zones',[]) if isinstance(c,dict) else []
 if not isinstance(zones,list): return out
 for z in zones:
  if not isinstance(z,dict): continue
  o=z.get('output') if isinstance(z.get('output'),dict) else {}
  out.append({
   'id':str(z.get('id','')),
   'name':str(z.get('name','')),
   'output_id':str(o.get('id','')),
   'playerId':str(o.get('playerId','')),
   'playerName':str(o.get('deviceName') or o.get('playerName','')),
   'host':str(o.get('host') or o.get('address') or ''),
   'sourceMac':str(z.get('sourceMac','')),
   'sourceSerial':str(z.get('sourceSerial',''))
  })
 return out

method=os.environ.get('REQUEST_METHOD','GET').upper()
raw=''
if method=='POST':
 try: raw=os.sys.stdin.read(int(os.environ.get('CONTENT_LENGTH','0') or 0))
 except: raw=''
else: raw=os.environ.get('QUERY_STRING','')
q=parse_qs(raw,keep_blank_values=True)
def G(k,d=''):
 v=q.get(k); return v[0] if v else d

c=load(SONN,{})
zones=parse_zones(c)
players=[z for z in zones if z['output_id'].lower()=='squeezelite']
solo=soloist_runtime()
msg=''
if method != 'POST' and G('action') in ('restore_confirm', 'zone_backup', 'backup', 'save'):
 msg='Verwende das Formular für diesen Vorgang.'
 q.pop('action',None)
settings=load(SET,{'miniservers':[{'name':'Primary Miniserver','host':'','user':''},{'name':'Miniserver 2','host':'','user':''}]})

preview=None
form_room=G('room_name')
form_zone=G('zone_id')
form_player=G('player_name')
form_ip=G('player_ip')
form_pid=G('player_id')
if G('action')=='clear_room':
 form_room=form_zone=form_player=form_ip=form_pid=''
elif G('action')=='preview_room':
 room=form_room.strip()
 player=form_player.strip()
 ip=form_ip.strip()
 pid=form_pid.strip().lower()
 zoneid=form_zone.strip()
 errors=[]
 if not room: errors.append('The room name is missing.')
 if not player: errors.append('The player name is missing.')
 try:
  ipaddress.IPv4Address(ip)
 except ValueError:
  errors.append('The IP is not a valid IPv4 address.')
 if not re.match('^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$',pid): errors.append('The playerId/MAC format is invalid.')
 if not zoneid.isdigit(): errors.append('Zone ID must be numeric.')
 if any(z['id']==zoneid for z in zones): errors.append('Zone ID #%s already exists in Sonn.'%zoneid)
 if any(z['playerId'].lower()==pid for z in zones if z['playerId']): errors.append('That playerId is already assigned.')
 if any(z['host']==ip for z in zones if z['host']): errors.append('That IP is already assigned to a player.')
 preview={'room':room,'player':player,'ip':ip,'pid':pid,'zoneid':zoneid,'errors':errors}


restore_result=None
if G('action')=='restore_confirm':
 bn=G('restore_backup')
 confirm=G('confirm_text').strip().upper()
 if confirm!='RESTORE':
  msg='FEHLER: Gib zur Bestätigung RESTORE ein.'
 else:
  try:
   with room_outputs.operation_lock(backup_root()):
    emergency,restore_steps=restore_backup_real(bn)
   msg='✓ Wiederherstellung geprüft und abgeschlossen. Notfallsicherung: '+emergency+' | '+' | '.join(restore_steps)
   restore_result=True
  except Exception as e:
   msg='Fehler bei der Wiederherstellung. Rückkehr zum vorherigen Zustand wurde versucht: '+str(e)
   restore_result=False

restore_preview=None
if G('action')=='restore_preview':
 bn=G('restore_backup')
 info,errs=validate_backup(bn)
 restore_preview={'name':bn,'info':info,'errors':errs}
 if errs: msg='FEHLER: Die ausgewählte Sicherung konnte nicht bestätigt werden.'
 else: msg='✓ Sicherung geprüft. Es wurde nichts wiederhergestellt.'

if G('action')=='zone_backup':
 zid=G('backup_zone')
 z=next((x for x in zones if x['id']==zid),None)
 if not z:
  msg='FEHLER: Wähle eine gültige Zone.'
 else:
  try:
   msg='✓ Sicherung erstellt: '+make_zone_backup(z,'manual')
  except Exception as e:
   msg='Fehler beim Erstellen der Sicherung: '+str(e)
elif G('action')=='backup':
 try:
  os.makedirs(BACK,exist_ok=True)
  dst=BACK+'/config-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.json'
  shutil.copy2(SONN,dst); msg='Backup created: '+dst
 except Exception as e: msg='FEHLER: '+str(e)
elif G('action')=='save':
 ms=[]
 for i in (1,2):
  ms.append({'name':G('name%d'%i,'Miniserver %d'%i),
             'host':G('host%d'%i,'').strip(),
             'user':G('user%d'%i,'')})
 os.makedirs(os.path.dirname(SET),exist_ok=True)
 with open(SET,'w') as f: json.dump({'miniservers':ms},f,indent=2)
 settings={'miniservers':ms}; msg='Daten lokal gespeichert. Loxone wurde nicht geändert.'

discovery_folder = os.path.dirname(SET)
if G('action') in ('sonn_connect', 'sonn_disconnect'):
 try:
  if method != 'POST': raise ValueError('Verwende das Formular für die Anmeldung bei Sonn.')
  if G('action') == 'sonn_connect':
   sonn_discovery.connect(discovery_folder, G('sonn_user'), G('sonn_password'))
   msg = '✓ Mit Sonn verbunden. AudioDek speichert das Passwort nicht.'
  else:
   sonn_discovery.disconnect(discovery_folder)
   msg = 'Sonn-Sitzung getrennt.'
 except Exception as e:
  msg = 'FEHLER: ' + str(e)
detected, discovery_error = sonn_discovery.inventory(discovery_folder, c.get('zones', []) if isinstance(c, dict) else [])

dlna_devices = {}
if method == 'POST' and G('action') == 'dlna_scan':
 try:
  dlna_devices = audiodek_dlna.scan(sonn_discovery, discovery_folder)
 except Exception as e:
  msg = 'FEHLER: ' + str(e)

output_preview = None
if G('action') in ('output_preview', 'output_confirm'):
 try:
  if method != 'POST': raise ValueError('Verwende das Formular für diesen Vorgang.')
  if G('action') == 'output_preview':
   current, fingerprint, _ = room_outputs.read_config(SONN)
   fields = {'name':G('output_name'), 'host':G('output_ip'), 'player_id':G('output_mac')}
   if G('output_operation') == 'assign' and G('detected_player'):
    if discovery_error: raise ValueError(discovery_error)
    # Resolve on the server; the browser supplies only the player identity.
    fresh, err = sonn_discovery.inventory(discovery_folder, current['zones'])
    if err: raise ValueError(err)
    fields = sonn_discovery.select(fresh, G('detected_player'), G('output_zone'))
   if G('output_operation') == 'assign_dlna':
    fields = audiodek_dlna.scan(sonn_discovery, discovery_folder).get(G('dlna_device'))
    if not fields:
     raise ValueError('Starte die DLNA-Suche erneut.')
   _, output_target = room_outputs.plan(current, G('output_zone'), G('output_operation'), **fields)
   data = {'fingerprint':fingerprint, 'zid':G('output_zone'), 'operation':G('output_operation'), 'fields':fields}
   token = room_outputs.issue_ticket(os.path.dirname(SET), data)
   output_preview = {'target':output_target, 'data':data, 'token':token}
  else:
   data = room_outputs.verify_ticket(os.path.dirname(SET), G('output_ticket'))
   word = 'REMOVE' if data['operation'] == 'detach' else 'ASSIGN'
   if G('output_confirm_word').strip().upper() != word:
    raise ValueError('Eingeben: ' + word + ' to confirm. Review the operation again.')
   services = {'docker_ok':docker_ok, 'active':active_soloist_zones, 'parse':parse_zones,
               'backup':make_zone_backup, 'validate':validate_backup, 'wait':wait_container, 'ensure':ensure_sonn_running}
   backup, steps = room_outputs.apply(SONN, backup_root(), data['fingerprint'], data['zid'],
                                     data['operation'], data['fields'], services)
   msg = '✓ Player-Änderung abgeschlossen. ' + ' | '.join(steps)
   c = load(SONN, {}); zones = parse_zones(c)
   players = [z for z in zones if z['output_id'].lower() == 'squeezelite']
   solo = soloist_runtime()
 except Exception as e:
  msg = 'FEHLER: ' + str(e)

if G('action') == 'output_confirm' and msg.startswith('✓'):
 detected, discovery_error = sonn_discovery.inventory(discovery_folder, c.get('zones', []))

print('<style>\n.at-wrap{max-width:1180px;margin:0 auto}.at-hero{background:#101828;color:#fff;padding:22px;border-radius:12px;margin-bottom:14px}\n.at-brand{display:flex;align-items:center;gap:20px;flex-wrap:wrap}.at-logo{background:#f8fafc;border-radius:18px;padding:8px;box-sizing:border-box;width:128px;height:128px;object-fit:contain;flex:none}.at-brand-copy{flex:1;min-width:200px}.at-brand-copy h1{margin:0 0 8px}.at-brand-copy .at-tag{margin-top:12px}\n.at-tag{background:#d1fadf;color:#05603a;padding:6px 10px;border-radius:18px;display:inline-block}\n.at-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}.at-card,.at-box{background:#fff;border:1px solid #ddd;border-radius:10px;padding:16px}\n.at-box{margin:12px 0}.at-ok{color:#087443;font-weight:bold}.at-wa{color:#b54708;font-weight:bold}\n.at-table{width:100%;border-collapse:collapse}.at-table th,.at-table td{text-align:left;padding:9px;border-bottom:1px solid #ddd}\n.at-btn{width:100%;padding:10px;font-weight:bold}.at-input{padding:8px;width:90%;box-sizing:border-box}\n@media(max-width:800px){.at-grid{grid-template-columns:1fr 1fr}}\n</style><div class="at-wrap"><div class="at-hero at-brand"><img class="at-logo" src="/system/images/icons/audiodek/icon_512.png" alt="Logo AudioDek" width="128" height="128"><div class="at-brand-copy"><h1>AudioDek</h1><b>Multiroom Manager for Loxone · v1.0.11</b><br><span class="at-tag">PLAYER MANAGEMENT WITH BACKUPS</span></div></div>')
print('<div class="at-box" id="audiodek-guide"><h2>Praktische Installationsanleitung</h2><p><a href="guide-de.html" data-ajax="false">Deutsche Anleitung mit Bildern öffnen</a></p></div>')
if msg: print('<div class="at-box" id="audiodek-result" role="status"><h2>Ergebnis</h2>'+E(msg)+'</div>')
print('<div class="at-grid"><div class="at-card"><b>Sonn-Konfiguration</b><br><span class="at-ok">✓ '+('Erkannt' if os.path.exists(SONN) else 'Nein')+'</span></div><div class="at-card"><b>Zonen mit Ausgang</b><br><b>'+str(sum(bool(z['output_id']) for z in zones))+'</b></div><div class="at-card"><b>Erkannte Zonen</b><br><b>'+str(len(zones))+'</b></div><div class="at-card"><b>Aktive Soloist-Prozesse</b><br><b>'+str(len(solo))+'</b></div></div>')
print('<form action="index.cgi" data-ajax="false" method="get"><button type="submit" class="at-btn">↻ Refresh / Rediscover</button></form>')

live = audiodek_zone_overview.live_states(sonn_discovery)
grouped = audiodek_zone_overview.partition(zones, live)
audiodek_zone_overview.render(grouped, live, set(solo), 'de')

print('<div class="at-box" id="audiodek-diagnostics"><h2>Geführte Diagnose</h2><p>Prüft die Konfiguration, den Dienst und die von Sonn gemeldete Verbindung. Ein aktiver Soloist-Prozess bestätigt keine Verbindung zum Player.</p><table class="at-table"><tr><th>Prüfung</th><th>Ergebnis / nächster Schritt</th></tr>')
try:
 diagnostic_cfg, _, _ = room_outputs.read_config(SONN)
 config_ok = True
except Exception:
 diagnostic_cfg = {'zones': []}; config_ok = False
checks = sonn_discovery.diagnose(diagnostic_cfg['zones'], set(solo), detected, discovery_error, config_ok, docker_ok(), os.access(os.path.dirname(SONN), os.W_OK | os.X_OK))
for state, title, advice in checks:
 print('<tr><td>'+E({'ok':'✓ ', 'warning':'⚠ ', 'pending':'○ '}[state]+title)+'</td><td>'+E(advice)+'</td></tr>')
print('</table></div>')
print('<div class="at-box"><h2>Von Sonn erkannte Squeezelite-Player</h2><p>Die Liste stammt von Sonn. Das Gerät muss eingeschaltet und sein Squeezelite-Client mit diesem Server verbunden sein.</p>')
if discovery_error:
 print('<p class="at-wa">'+E(discovery_error)+'</p>')
else:
 print('<table class="at-table"><tr><th>Name</th><th>IP</th><th>playerId</th><th>Verbindung</th><th>Zuordnung</th></tr>')
 for p in detected:
  print('<tr><td>'+E(p['name'])+'</td><td>'+E(p['host'])+'</td><td>'+E(p['player_id'])+'</td><td>'+('Verbunden' if p['connected'] else 'Getrennt')+'</td><td>'+E(', '.join('#'+i for i in p['owners']) or 'Verfügbar')+'</td></tr>')
 if not detected: print('<tr><td colspan="5">Sonn meldet keine Player. Verbinde Squeezelite in piCorePlayer mit Sonn und aktualisiere die Ansicht.</td></tr>')
 print('</table>')
print('<details><summary>Sonn-Zugang</summary><p>Verwende ein Sonn-Administratorkonto. AudioDek fragt den lokalen Server auf Port 7090 ab und speichert nur die Sitzung in einer privaten Datei. Das Passwort wird nicht gespeichert. Die Miniserver-Notizen stellen keine Verbindung her.</p><form method="post" action="index.cgi" data-ajax="false"><input type="hidden" name="_ui_language" value="de"><input type="hidden" name="action" value="sonn_connect"><label>Sonn-Benutzername<input class="at-input" name="sonn_user" autocomplete="username" maxlength="256"></label><label>Sonn-Passwort<input class="at-input" type="password" name="sonn_password" autocomplete="current-password" maxlength="256"></label><button class="at-btn" type="submit">Verbinden und Player abfragen</button></form><form method="post" action="index.cgi" data-ajax="false"><input type="hidden" name="_ui_language" value="de"><input type="hidden" name="action" value="sonn_disconnect"><button class="at-btn" type="submit">Sitzung trennen</button></form></details></div>')

ms=settings.get('miniservers',[])
while len(ms)<2: ms.append({'name':'Miniserver '+str(len(ms)+1),'host':'','user':''})
print('<div class="at-box"><h2>Lokale Miniserver-Daten</h2><p>Diese Angaben dienen als lokale Notizen. Richte die Verbindung zum Miniserver in Sonn ein.</p><form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="de"><input type="hidden" name="action" value="save"><table class="at-table"><tr><th>Name</th><th>IP / Host</th><th>Benutzername</th></tr>')
for i,m in enumerate(ms[:2],1):
 print('<tr><td><input class="at-input" name="name%d" value="%s"></td><td><input class="at-input" name="host%d" value="%s"></td><td><input class="at-input" name="user%d" value="%s"></td></tr>'%(i,E(m.get('name')),i,E(m.get('host')),i,E(m.get('user'))))
print('</table><button type="submit" class="at-btn">Lokale Daten speichern</button></form></div>')
print('<div class="at-box" id="audiodek-new-room"><h2>Raum hinzufügen</h2><ol><li>Lege die Audiozone in Loxone Config an und übertrage die Konfiguration an den Miniserver.</li><li>Sobald Sonn die Zone übernommen hat, aktualisiere die Ansicht.</li><li>Wähle einen Raum ohne Ausgang und dann einen erkannten Player, oder gib seine Daten manuell ein.</li></ol><p>AudioDek behält die Loxone-Kennungen bei. Sind noch keine Soloist-Daten vorhanden, hält die Sicherung dies vor der Zuweisung fest.</p>')
unassigned = [z for z in zones if not z['output_id']]
if unassigned:
 print('<h3>Räume ohne zugewiesenen Player</h3><ul>')
 for z in unassigned:
  print('<li><a data-ajax="false" href="index.cgi?focus_zone='+E(z['id'])+'#audiodek-player">#'+E(z['id'])+' — '+E(z['name'])+'</a></li>')
 print('</ul>')
else:
 print('<p>Alle erkannten Räume haben einen Ausgang. Neue Räume erscheinen hier, sobald Sonn sie von Loxone erhält.</p>')
print('</div>')


print('<div class="at-box"><h2>DLNA-Player</h2><p>Suche mit Sonn nach DLNA-Renderern und weise einen einem Raum ohne Ausgang zu. Die Synchronisation mit Squeezelite muss mit den jeweiligen Geräten getestet werden.</p><form action="index.cgi" method="post" data-ajax="false"><input type="hidden" name="_ui_language" value="de"><input type="hidden" name="action" value="dlna_scan"><button class="at-btn">DLNA-Player suchen</button></form>')
if dlna_devices:
 print('<form action="index.cgi" method="post" data-ajax="false"><input type="hidden" name="_ui_language" value="de"><input type="hidden" name="action" value="output_preview"><input type="hidden" name="output_operation" value="assign_dlna"><select name="output_zone" required><option value="">Raum ohne Ausgang auswählen</option>')
 for room in c.get('zones', []):
  if room.get('output') is None and 'transports' not in room:
   print('<option value="'+E(room['id'])+'">'+E(room.get('name',''))+'</option>')
 print('</select><select name="dlna_device" required>')
 for key, device in dlna_devices.items():
  print('<option value="'+E(key)+'">'+E(device['name']+' — '+device['host'])+'</option>')
 print('</select><button class="at-btn">DLNA-Zuweisung prüfen</button></form>')
elif G('action') == 'dlna_scan' and not msg:
 print('<p>Keine kompatiblen Player gefunden. Prüfe, ob das Gerät eingeschaltet und im selben Netzwerk ist.</p>')
print('</div>')

print('<div class="at-box" id="audiodek-player"><h2>Player eines Raums verwalten</h2>')
print('<p>Weise einen Squeezelite-Player zu oder entferne ihn. Der Loxone-Raum bleibt erhalten. AudioDek erstellt zuerst eine Sicherung. Sonn wird neu gestartet und die Wiedergabe unterbrochen.</p>')
print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="de"><input type="hidden" name="action" value="output_preview"><label>Raum<select name="output_zone" class="at-input" style="width:100%;margin:8px 0"><option value="">Raum auswählen …</option>')
for z in zones:
 print('<option value="'+E(z['id'])+'"'+(' selected' if (G('output_zone') or G('focus_zone'))==z['id'] else '')+'>#'+E(z['id'])+' — '+E(z['name'])+' — '+E(z['playerName'] or 'Kein Player')+'</option>')
print('</select></label><label>Vorgang<select name="output_operation" class="at-input" style="width:100%;margin:8px 0"><option value="assign">Player zuweisen / ersetzen</option><option value="detach"'+(' selected' if G('output_operation')=='detach' else '')+'>Player entfernen</option></select></label>')
print('<label>Erkannter Player<select name="detected_player" class="at-input" style="width:100%;margin:8px 0"><option value="">Daten manuell eingeben …</option>')
selected_room = G('output_zone') or G('focus_zone')
for p in detected:
 unavailable = not p['connected'] or not p['valid_ip'] or any(i != selected_room for i in p['owners'])
 suffix = ' — zugewiesen an '+','.join('#'+i for i in p['owners']) if p['owners'] else ' — verfügbar'
 if not p['connected']: suffix += ' — getrennt'
 if not p['valid_ip']: suffix += ' — nicht unterstützte IP-Adresse'
 print('<option value="'+E(p['player_id'])+'"'+(' disabled' if unavailable else '')+(' selected' if G('detected_player') == p['player_id'] and not unavailable else '')+'>'+E(p['name']+' — '+p['host']+suffix)+'</option>')
print('</select></label><p>Wähle einen verfügbaren Player. AudioDek übernimmt Name, IP-Adresse und Player-ID aus Sonn. Die Felder darunter gelten nur bei manueller Eingabe. Zum Entfernen wähle den Raum und den entsprechenden Vorgang.</p>')
for label, key, placeholder in [('Player-Name','output_name','z. B. Küche'),('IP-Adresse des Players','output_ip','192.168.1.xxx'),('MAC / playerId','output_mac','aa:bb:cc:dd:ee:ff')]:
 print('<label>'+E(label)+'<input class="at-input" style="width:100%;margin:8px 0" name="'+key+'" value="'+E(G(key))+'" placeholder="'+E(placeholder)+'"></label>')
print('<button type="submit" class="at-btn">Player-Änderung prüfen</button></form>')
if output_preview:
 t = output_preview['target']; d = output_preview['data']; o = t.get('output') or {}
 print('<h3>Änderung vor dem Anwenden prüfen</h3><table class="at-table">')
 for label, value in [('Raum','#'+str(t['id'])+' '+str(t.get('name',''))),('Vorgang','Player entfernen' if d['operation']=='detach' else 'Player zuweisen / ersetzen'),('Neuer Player',o.get('deviceName') or o.get('playerName','Kein Player')),('IP',o.get('host','—')),('MAC',o.get('playerId','—'))]:
  print('<tr><td>'+E(label)+'</td><td>'+E(value)+'</td></tr>')
 word = 'REMOVE' if d['operation']=='detach' else 'ASSIGN'
 print('</table><p>Der Raum und seine Loxone-Kennungen bleiben erhalten. Die Vorschau gilt 15 Minuten. Prüfe den Vorgang erneut, wenn sich die Konfiguration ändert.</p>')
 print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="de"><input type="hidden" name="action" value="output_confirm"><input type="hidden" name="output_ticket" value="'+E(output_preview['token'])+'"><label>Eingeben: '+word+'<input name="output_confirm_word" class="at-input" style="width:100%;margin:8px 0" autocomplete="off"></label><button type="submit" class="at-btn">Änderung bestätigen</button></form>')
print('<h3>Räume anlegen und benennen</h3><p>Lege den Raum in Loxone Config an oder benenne ihn dort um. Sobald Sonn die Änderung übernommen hat, aktualisiere diese Ansicht und weise den Player zu.</p>')
print('<p>Um eine frühere Konfiguration wiederherzustellen, verwende <a href="#audiodek-restore">Sicherung wiederherstellen</a>. Prüfe spätere Änderungen: Die Wiederherstellung übernimmt die gesamte Konfiguration und die Soloist-Daten des ausgewählten Raums.</p></div>')

print('<div class="at-box"><h2>Sicherung vor Änderungen</h2><p>Sichert <code>config.json</code> und nur <code>zone-X/data</code>. Soloist-Caches werden nicht kopiert.</p><form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="de"><input type="hidden" name="action" value="zone_backup"><select name="backup_zone" class="at-input" style="width:100%;margin-bottom:8px"><option value="">Raum auswählen …</option>')
for z in zones:
 print('<option value="'+E(z['id'])+'">#'+E(z['id'])+' — '+E(z['name'])+' — '+E(z['playerName'])+'</option>')
print('</select><button type="submit" class="at-btn">Raumsicherung erstellen</button></form></div>')
backs=list_backups()
print('<div class="at-box"><h2>Sicherungsverlauf</h2>')
if not backs:
 print('<p>Noch keine Sicherungen vorhanden.</p>')
else:
 print('<table class="at-table"><tr><th>Datum</th><th>Zone</th><th>Raum</th><th>Vorgang</th><th>Status</th></tr>')
 for b in backs[:20]:
  print('<tr><td>'+E(b.get('created'))+'</td><td>#'+E(b.get('zoneId'))+'</td><td>'+E(b.get('room'))+'</td><td>'+E(b.get('operation'))+'</td><td class="at-ok">✓ '+E(b.get('status','backup'))+'</td></tr>')
 print('</table>')
print('</div>')
print('<div class="at-box" id="audiodek-restore"><h2>Sicherung wiederherstellen</h2><p>Die Sicherung wird vor der Wiederherstellung geprüft.</p>')
if backs:
 print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="de"><input type="hidden" name="action" value="restore_preview"><select name="restore_backup" class="at-input" style="width:100%;margin-bottom:8px">')
 for b in backs:
  print('<option value="'+E(b.get('_name'))+'">'+E(b.get('created'))+' — #'+E(b.get('zoneId'))+' — '+E(b.get('room'))+'</option>')
 print('</select><button type="submit" class="at-btn">Sicherung prüfen / Vorschau anzeigen</button></form>')
else:
 print('<p>Keine Sicherungen verfügbar.</p>')
if restore_preview:
 if restore_preview['errors']:
  print('<div class="at-wa"><h3>Ungültige Sicherung</h3><ul>')
  for e in restore_preview['errors']: print('<li>'+E(e)+'</li>')
  print('</ul></div>')
 else:
  m,d=restore_preview['info']
  cf=os.path.join(d,'config.json'); sf=os.path.join(d,'soloist-data.tar.gz')
  print('<div class="at-ok"><h3>✓ Sicherung erfolgreich geprüft</h3></div><table class="at-table">')
  for a,b in [('Sicherung',restore_preview['name']),('Zone','#'+str(m.get('zoneId',''))+' '+str(m.get('room',''))),
              ('Player',m.get('playerName','')),('IP',m.get('ip','')),('playerId',m.get('playerId','')),
              ('config.json',str(os.path.getsize(cf))+' bytes'),('Soloist-Daten',str(os.path.getsize(sf))+' bytes'),
              ('Wiederherstellung','Nach Bestätigung verfügbar; startet Sonn neu')]:
   print('<tr><td>'+E(a)+'</td><td>'+E(b)+'</td></tr>')
  print('</table><p><b>Es wurden keine Dateien geändert.</b></p>')
  print('<div class="at-wa"><h3>Wiederherstellung</h3><p>AudioDek erstellt zuerst eine Notfallsicherung, stoppt Sonn, stellt die Daten wieder her und prüft die Zone nach dem Neustart. Bei einem Fehler versucht AudioDek, den vorherigen Zustand wiederherzustellen. Abschließend wird Sonn erneut geprüft.</p></div>')
  print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="de"><input type="hidden" name="action" value="restore_confirm"><input type="hidden" name="restore_backup" value="'+E(restore_preview['name'])+'"><input class="at-input" style="width:100%;margin-bottom:8px" name="confirm_text" placeholder="RESTORE eingeben"><button type="submit" class="at-btn">Wiederherstellung bestätigen</button></form>')
print('</div></div>')
