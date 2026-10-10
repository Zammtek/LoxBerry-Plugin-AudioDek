#!/usr/bin/env python3
# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-10: license notices and update metadata; existing behavior retained.
import json,os,re,html,subprocess,shutil,datetime,ipaddress
from urllib.parse import parse_qs
import room_outputs
import sonn_discovery

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
   'playerName':str(o.get('playerName','')),
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
  msg='ERROR: type RESTORE to confirm.'
 else:
  try:
   with room_outputs.operation_lock(backup_root()):
    emergency,restore_steps=restore_backup_real(bn)
   msg='✓ Restore completed and verified. Emergency backup: '+emergency+' | '+' | '.join(restore_steps)
   restore_result=True
  except Exception as e:
   msg='ERROR during restore. Automatic rollback was attempted: '+str(e)
   restore_result=False

restore_preview=None
if G('action')=='restore_preview':
 bn=G('restore_backup')
 info,errs=validate_backup(bn)
 restore_preview={'name':bn,'info':info,'errors':errs}
 if errs: msg='ERROR: the selected backup failed verification.'
 else: msg='✓ Backup verified. Restore has NOT been performed.'

if G('action')=='zone_backup':
 zid=G('backup_zone')
 z=next((x for x in zones if x['id']==zid),None)
 if not z:
  msg='ERROR: select a valid zone.'
 else:
  try:
   msg='✓ Transactional backup created: '+make_zone_backup(z,'manual')
  except Exception as e:
   msg='ERROR creating backup: '+str(e)
elif G('action')=='backup':
 try:
  os.makedirs(BACK,exist_ok=True)
  dst=BACK+'/config-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.json'
  shutil.copy2(SONN,dst); msg='Backup created: '+dst
 except Exception as e: msg='ERROR: '+str(e)
elif G('action')=='save':
 ms=[]
 for i in (1,2):
  ms.append({'name':G('name%d'%i,'Miniserver %d'%i),
             'host':G('host%d'%i,'').strip(),
             'user':G('user%d'%i,'')})
 os.makedirs(os.path.dirname(SET),exist_ok=True)
 with open(SET,'w') as f: json.dump({'miniservers':ms},f,indent=2)
 settings={'miniservers':ms}; msg='Details saved locally. Loxone has not been changed.'

discovery_folder = os.path.dirname(SET)
if G('action') in ('sonn_connect', 'sonn_disconnect'):
 try:
  if method != 'POST': raise ValueError('Use the form to connect to Sonn.')
  if G('action') == 'sonn_connect':
   sonn_discovery.connect(discovery_folder, G('sonn_user'), G('sonn_password'))
   msg = '✓ Sonn connection prepared. AudioDek does not store the password.'
  else:
   sonn_discovery.disconnect(discovery_folder)
   msg = 'Sonn query session disconnected.'
 except Exception as e:
  msg = 'ERROR: ' + str(e)
detected, discovery_error = sonn_discovery.inventory(discovery_folder, c.get('zones', []) if isinstance(c, dict) else [])

output_preview = None
if G('action') in ('output_preview', 'output_confirm'):
 try:
  if method != 'POST': raise ValueError('Use the form for this operation.')
  if G('action') == 'output_preview':
   current, fingerprint, _ = room_outputs.read_config(SONN)
   fields = {'name':G('output_name'), 'host':G('output_ip'), 'player_id':G('output_mac')}
   if G('output_operation') == 'assign' and G('detected_player'):
    if discovery_error: raise ValueError(discovery_error)
    # Resolve on the server; the browser supplies only the player identity.
    fresh, err = sonn_discovery.inventory(discovery_folder, current['zones'])
    if err: raise ValueError(err)
    fields = sonn_discovery.select(fresh, G('detected_player'), G('output_zone'))
   _, output_target = room_outputs.plan(current, G('output_zone'), G('output_operation'), **fields)
   data = {'fingerprint':fingerprint, 'zid':G('output_zone'), 'operation':G('output_operation'), 'fields':fields}
   token = room_outputs.issue_ticket(os.path.dirname(SET), data)
   output_preview = {'target':output_target, 'data':data, 'token':token}
  else:
   data = room_outputs.verify_ticket(os.path.dirname(SET), G('output_ticket'))
   word = 'REMOVE' if data['operation'] == 'detach' else 'ASSIGN'
   if G('output_confirm_word').strip().upper() != word:
    raise ValueError('Type ' + word + ' to confirm. Review the operation again.')
   services = {'docker_ok':docker_ok, 'active':active_soloist_zones, 'parse':parse_zones,
               'backup':make_zone_backup, 'validate':validate_backup, 'wait':wait_container, 'ensure':ensure_sonn_running}
   backup, steps = room_outputs.apply(SONN, backup_root(), data['fingerprint'], data['zid'],
                                     data['operation'], data['fields'], services)
   msg = '✓ Player change completed. ' + ' | '.join(steps)
   c = load(SONN, {}); zones = parse_zones(c)
   players = [z for z in zones if z['output_id'].lower() == 'squeezelite']
   solo = soloist_runtime()
 except Exception as e:
  msg = 'ERROR: ' + str(e)

if G('action') == 'output_confirm' and msg.startswith('✓'):
 detected, discovery_error = sonn_discovery.inventory(discovery_folder, c.get('zones', []))

print('<style>\n.at-wrap{max-width:1180px;margin:0 auto}.at-hero{background:#101828;color:#fff;padding:22px;border-radius:12px;margin-bottom:14px}\n.at-brand{display:flex;align-items:center;gap:20px;flex-wrap:wrap}.at-logo{background:#f8fafc;border-radius:18px;padding:8px;box-sizing:border-box;width:128px;height:128px;object-fit:contain;flex:none}.at-brand-copy{flex:1;min-width:200px}.at-brand-copy h1{margin:0 0 8px}.at-brand-copy .at-tag{margin-top:12px}\n.at-tag{background:#d1fadf;color:#05603a;padding:6px 10px;border-radius:18px;display:inline-block}\n.at-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}.at-card,.at-box{background:#fff;border:1px solid #ddd;border-radius:10px;padding:16px}\n.at-box{margin:12px 0}.at-ok{color:#087443;font-weight:bold}.at-wa{color:#b54708;font-weight:bold}\n.at-table{width:100%;border-collapse:collapse}.at-table th,.at-table td{text-align:left;padding:9px;border-bottom:1px solid #ddd}\n.at-btn{width:100%;padding:10px;font-weight:bold}.at-input{padding:8px;width:90%;box-sizing:border-box}\n@media(max-width:800px){.at-grid{grid-template-columns:1fr 1fr}}\n</style><div class="at-wrap"><div class="at-hero at-brand"><img class="at-logo" src="/system/images/icons/audiodek/icon_512.png" alt="Logo AudioDek" width="128" height="128"><div class="at-brand-copy"><h1>AudioDek</h1><b>Multiroom Manager for Loxone · v1.0.7</b><br><span class="at-tag">PLAYER MANAGEMENT WITH BACKUPS</span></div></div>')
print('<div class="at-box" id="audiodek-guide"><h2>Practical setup guide</h2><p>Prepare LoxBerry, Sonn, Loxone Config and piCorePlayer. Includes edited illustrations with generic English labels.</p><p><a href="guide-en.html" data-ajax="false">Open the full guide to read or print</a></p><details><summary>Read the guide here</summary><section class="ad-guide" aria-labelledby="ad-guide-title">\n<h2 id="ad-guide-title">Practical guide: your first room with AudioDek</h2>\n<p>For a fresh installation of <strong>LoxBerry 4.0 on x86_64</strong>. Follow the steps in order and start with one room. AudioDek helps you assign players and recover configuration changes. Sonn handles playback; everyday control remains in the Loxone app.</p>\n<nav aria-label="Guide steps"><a href="#ad-before">Requirements</a> · <a href="#ad-server">Server</a> · <a href="#ad-loxone">Loxone</a> · <a href="#ad-player">Player</a> · <a href="#ad-assign">Assignment</a> · <a href="#ad-test">Playback test</a> · <a href="#ad-backup">Backup</a> · <a href="#ad-help">Troubleshooting</a></nav>\n<h3 id="ad-before">1. Prepare what you need</h3>\n<ul><li>LoxBerry 4.0 on an x86_64 PC or virtual machine. This AudioDek package does not target LoxBerry on ARM.</li><li>An accessible Miniserver and its Loxone Config project, with permission to deploy changes.</li><li>Audioserver4Home running Sonn <strong>4.0.0-beta.19</strong>, the version examined for this edition. Compatibility with other versions needs verification.</li><li>For your first room: a Raspberry Pi supported by piCorePlayer, a microSD card, power supply, network connection and suitable audio output (such as a USB DAC), plus an amplifier and speakers as required.</li><li>Devices that can communicate on your local network. Start with wired Ethernet.</li></ul>\n<p><strong>Record three separate IP addresses:</strong> LoxBerry/Sonn, the Miniserver and the player. Each device needs its own address. Your router\'s device list can help; a DHCP reservation helps keep addresses consistent.</p>\n<p>AudioDek does not install Sonn, write piCorePlayer SD cards or create Loxone Config blocks. This guide explains the steps in each application.</p>\n<h3 id="ad-server">2. Prepare Sonn and install AudioDek</h3>\n<ol><li>Install <strong>Audioserver4Home</strong> through LoxBerry\'s plugin management, following its documentation. Check that Sonn is running and verify its version. Do not change a working system\'s version without checking compatibility.</li><li>Open Sonn administration from Audioserver4Home or visit <code>http://LOXBERRY_IP:7090</code>, replacing the placeholder with your actual address.</li><li>Complete initial setup and create an administrator account if prompted. Keep its credentials.</li><li>Install the <strong>AudioDek</strong> ZIP through LoxBerry Plugins and open its dashboard.</li><li>Click <strong>Refresh / Rediscover</strong>. Guided diagnostics should report a readable configuration and a running Sonn service. No rooms is normal before you have configured any zones.</li></ol>\n<p><strong>Before continuing:</strong> you should be able to open both Sonn and AudioDek. Resolve missing configuration or a stopped service in Audioserver4Home first.</p>\n<p>Documentation: <a href="https://github.com/mschlenstedt/LoxBerry-Plugin-Audioserver4Home">Audioserver4Home</a> and <a href="https://sonn-audio.github.io/docs/setup/">Sonn initial setup</a>.</p>\n<h3 id="ad-loxone">3. Create your first room in Loxone Config</h3>\n<ol><li>Save a copy of your Loxone Config project before editing it.</li><li>In Sonn, open <strong>Zones</strong> and select <strong>Loxone integrated</strong>. Note the host and serial number provided by Sonn.</li><li>Add the Audioserver in Loxone Config using those details. Use the Sonn server\'s address and the serial number shown by Sonn.</li><li>Create an <strong>Audio Player</strong> function block. Give it a clear name, such as Kitchen, assign its room and connect it to an available Audioserver output.</li><li>Deploy the configuration to the Miniserver. If initial pairing requires a Miniserver reboot, follow Sonn\'s instructions and choose a time when interrupting operation is acceptable.</li><li>Return to AudioDek and click <strong>Refresh / Rediscover</strong>. Your room should appear, possibly without a player assigned yet.</li></ol>\n<p><strong>Do not copy another installation\'s serial number or duplicate an Audioserver identity to obtain extra outputs.</strong> Check Sonn\'s output and extension support when expanding. AudioDek does not invent zone IDs or modify your Loxone project.</p>\n<p>AudioDek\'s <strong>Local Miniserver reference</strong> fields are notes only. Saving them does not connect Sonn to the Miniserver.</p>\n<p>References: <a href="https://sonn-audio.github.io/">Sonn\'s Loxone integration</a> and <a href="https://sonn-audio.github.io/docs/troubleshooting/">pairing troubleshooting</a>. Menu names may vary with version and language.</p>\n<h4>How the Audioserver and rooms are arranged</h4>\n<figure><img src="guide-images/en/audioserver-layout.png" alt="Anonymized illustrative Loxone Config tree showing direct Audioserver outputs and a room under Tree Turbo and Stereo Extension" style="max-width:100%;width:700px;height:auto"><figcaption>Edited illustrative screenshot. Original names and identifying numbers have been replaced with generic English labels. Rooms A to E are examples.</figcaption></figure>\n<p>Rooms A to D use direct Audioserver outputs. Room E appears under <strong>Tree Turbo → Stereo Extension → right output → Audio Player</strong>. Left and Right are Loxone channels, not a Raspberry Pi\'s IP address or MAC. The other Audioserver shown belongs to the example and is not required to get started.</p>\n<p>The extension in this example is used with Sonn\'s emulation. You do not need an extension for your first room if an output is available. Check your Sonn version\'s support and identity requirements before expanding.</p>\n<h4>Connecting the Audio Player block</h4>\n<figure><img src="guide-images/en/audio-player-block.png" alt="Anonymized illustrative Audio Player block with Stereo LR connected to an audio output" style="max-width:100%;width:700px;height:auto"><figcaption>The room\'s block connects from <strong>Stereo LR</strong> to the <strong>Audio output</strong> object. Original names have been replaced. The red link symbol reflects the state when the screenshot was taken; it does not confirm completed setup.</figcaption></figure>\n<p>After deploying to the Miniserver, check pairing in Loxone and confirm the zone appears in AudioDek. Loxone Config defines the block and output; Sonn receives the zone; AudioDek associates it with a Squeezelite player. The player\'s IP and playerId are separate from the Audioserver or extension serial number.</p>\n<h3 id="ad-player">4. Prepare piCorePlayer</h3>\n<ol><li>Download piCorePlayer from its official website and write its image to a microSD card following its guide. Carefully select the correct target card.</li><li>Insert the card into the Raspberry Pi and connect Ethernet, the audio equipment and power.</li><li>Find its IP address in your router or on the boot screen, then visit <code>http://PLAYER_IP</code>.</li><li>Complete initial setup. In <strong>Squeezelite Settings</strong>, select the audio output you actually use and a recognizable player name. Save and restart Squeezelite or the device when requested.</li><li>Configure Squeezelite to connect to the <strong>Sonn/LoxBerry IP address</strong>. piCorePlayer may label this field server or LMS. Sonn acts as the Squeezelite server here: do not use the Miniserver\'s IP or the player\'s own IP. A separate LMS installation is not required for this setup.</li><li>Check that Squeezelite is running, then refresh AudioDek.</li></ol>\n<p>The <strong>player IP address</strong> identifies the Raspberry Pi. The <strong>playerId</strong> identifies its Squeezelite instance and commonly looks like a MAC address. Do not use an Audioserver or Stereo Extension serial number. Selecting a detected player lets AudioDek retrieve its details from Sonn.</p>\n<p>See <a href="https://docs.picoreplayer.org/getting-started/">piCorePlayer getting started</a>. Its examples use LMS; for this installation, connect the Squeezelite client to Sonn.</p>\n<h3 id="ad-assign">5. Select and assign the player</h3>\n<ol><li>Check <strong>Players detected by Sonn</strong>. If access is required, expand <strong>Sonn access</strong>, enter a Sonn administrator account and click <strong>Connect to query players</strong>. AudioDek stores the session, not the password.</li><li>Check the player\'s name, IP and connection status. This is Sonn\'s client list, not a scan of every network device.</li><li>Under <strong>Manage a room\'s player</strong>, select the room and <strong>Assign / replace player</strong>.</li><li>Select a connected, available device under <strong>Detected player</strong>. Leave manual fields empty; AudioDek obtains the details from Sonn.</li><li>Click <strong>Review player change</strong> and verify the room, name, IP and playerId.</li><li>Type <strong>ASSIGN</strong> and click <strong>Confirm change</strong>. AudioDek creates a backup and restarts Sonn. Playback is interrupted during this operation.</li><li>Check the operation result and refresh the dashboard.</li></ol>\n<p><strong>Manual alternative:</strong> select Enter details manually and provide the actual name, IPv4 address and playerId. Every player needs a unique identity; AudioDek rejects duplicates. To detach a player, select the room and Remove player, review, then confirm with <strong>REMOVE</strong>.</p>\n<p><strong>No player yet?</strong> Leave the room pending. Do not enter an invented IP or MAC address.</p>\n<h3 id="ad-test">6. Check playback and add more rooms</h3>\n<ol><li>Prepare a playable source in Sonn, such as a radio station or music library.</li><li>Open the Loxone app, select the room and play the source at a moderate volume.</li><li>Check sound, pause and volume at the speakers. An active Soloist process or connected player does not by itself prove that the audio output and amplifier work.</li><li>Once it works, repeat steps 3 to 6 for another room with its own player.</li></ol>\n<p><strong>Expected result:</strong> the room exists in Loxone, AudioDek shows its Squeezelite output, Sonn reports a connected player and you hear music in the room.</p>\n<h3 id="ad-backup">7. Save a backup and understand its scope</h3>\n<p>Under <strong>Transactional backup</strong>, select the room and click <strong>Create room backup</strong>. Check Backup history and use <strong>Verify / Preview restore</strong> to inspect the backup without restoring it.</p>\n<p><strong>A backup contains the configuration of all zones, but Soloist data for only the selected room.</strong> It is not a full backup of all audio data or the Miniserver project. Keep a separate Loxone Config project copy and a system backup using LoxBerry\'s facilities.</p>\n<p>A real restore requires typing <strong>RESTORE</strong> and confirming. Sonn restarts. The complete configuration is restored to the backup\'s state, potentially reverting later changes in other rooms. Do not restore just to test the display.</p>\n<h3 id="ad-help">Troubleshooting</h3>\n<div class="ad-scroll"><table class="at-table"><thead><tr><th>What you see</th><th>What to check</th></tr></thead><tbody>\n<tr><td>No rooms</td><td>Loxone integration enabled in Sonn, correct Audioserver identity, Audio Player linked to an output and project deployed to the Miniserver. Then refresh AudioDek.</td></tr>\n<tr><td>Sonn access required or expired</td><td>Connect through Sonn access using a valid Sonn administrator account. Local Miniserver reference notes do not establish this session.</td></tr>\n<tr><td>Player not detected</td><td>Power, network, Squeezelite running and connected to this Sonn server. If it uses another server, correct the client\'s server setting.</td></tr>\n<tr><td>Player already assigned</td><td>Check which room uses it. Do not duplicate IP addresses or playerIds to bypass validation.</td></tr>\n<tr><td>Soloist active but no sound</td><td>Player connection, playable source, piCorePlayer audio output, DAC, cables, amplifier, speakers and volume.</td></tr>\n<tr><td>No permission to apply changes</td><td>Ask your LoxBerry administrator to check installation and directory permissions. Do not grant unrestricted permissions or edit unrelated files.</td></tr>\n<tr><td>Cannot query Sonn on port 7090</td><td>Sonn running and administration accessible. This edition queries Sonn on the same LoxBerry at local port 7090; a different server or port requires adapting the plugin.</td></tr>\n</tbody></table></div>\n<p>This guide accompanies AudioDek v1.0.7, English edition. Reading and refreshing do not apply audio changes. Assigning, removing and restoring do. Authenticated discovery and a complete fresh installation still require real-system validation.</p>\n</section>\n</details></div>')
if msg: print('<div class="at-box" id="audiodek-result" role="status"><h2>Operation result</h2>'+E(msg)+'</div>')
print('<div class="at-grid"><div class="at-card"><b>Sonn config</b><br><span class="at-ok">✓ '+('Detected' if os.path.exists(SONN) else 'No')+'</span></div><div class="at-card"><b>Assigned players</b><br><b>'+str(len(players))+'</b></div><div class="at-card"><b>Dynamic zones</b><br><b>'+str(len(zones))+'</b></div><div class="at-card"><b>Active Soloist processes</b><br><b>'+str(len(solo))+'</b></div></div>')
print('<form action="index.cgi" data-ajax="false" method="get"><button type="submit" class="at-btn">↻ Refresh / Rediscover</button></form>')

print('<div class="at-box" id="audiodek-diagnostics"><h2>Guided diagnostics</h2><p>Check configuration, service status and the connection reported by Sonn. An active Soloist process alone does not confirm that the player is connected.</p><table class="at-table"><tr><th>Check</th><th>Result / next step</th></tr>')
try:
 diagnostic_cfg, _, _ = room_outputs.read_config(SONN)
 config_ok = True
except Exception:
 diagnostic_cfg = {'zones': []}; config_ok = False
checks = sonn_discovery.diagnose(diagnostic_cfg['zones'], set(solo), detected, discovery_error, config_ok, docker_ok(), os.access(os.path.dirname(SONN), os.W_OK | os.X_OK))
for state, title, advice in checks:
 print('<tr><td>'+E({'ok':'✓ ', 'warning':'⚠ ', 'pending':'○ '}[state]+title)+'</td><td>'+E(advice)+'</td></tr>')
print('</table></div>')
print('<div class="at-box"><h2>Players detected by Sonn</h2><p>The list comes from Sonn, not a scan of the entire network. The device must be powered on and its Squeezelite connected to this server.</p>')
if discovery_error:
 print('<p class="at-wa">'+E(discovery_error)+'</p>')
else:
 print('<table class="at-table"><tr><th>Name</th><th>IP</th><th>playerId</th><th>Connection</th><th>Assignment</th></tr>')
 for p in detected:
  print('<tr><td>'+E(p['name'])+'</td><td>'+E(p['host'])+'</td><td>'+E(p['player_id'])+'</td><td>'+('Connected' if p['connected'] else 'Disconnected')+'</td><td>'+E(', '.join('#'+i for i in p['owners']) or 'Available')+'</td></tr>')
 if not detected: print('<tr><td colspan="5">Sonn reports no players. In piCorePlayer, configure Squeezelite to connect to Sonn, then refresh.</td></tr>')
 print('</table>')
print('<details><summary>Sonn access</summary><p>Use a Sonn administrator account. AudioDek queries the local server on port 7090 and stores only its session in a private file. It does not store the password. Local Miniserver notes do not establish this connection.</p><form method="post" action="index.cgi" data-ajax="false"><input type="hidden" name="_ui_language" value="en"><input type="hidden" name="action" value="sonn_connect"><label>Sonn username<input class="at-input" name="sonn_user" autocomplete="username" maxlength="256"></label><label>Sonn password<input class="at-input" type="password" name="sonn_password" autocomplete="current-password" maxlength="256"></label><button class="at-btn" type="submit">Connect to query players</button></form><form method="post" action="index.cgi" data-ajax="false"><input type="hidden" name="_ui_language" value="en"><input type="hidden" name="action" value="sonn_disconnect"><button class="at-btn" type="submit">Disconnect query session</button></form></details></div>')

print('<div class="at-box"><h2>Dynamically detected zones and players</h2><table class="at-table"><tr><th>Zone</th><th>Name</th><th>Output</th><th>Player</th><th>IP</th><th>playerId</th><th>Soloist</th></tr>')
for z in zones:
 st='<span class="at-ok">● Active</span>' if z['id'] in solo else ('<span>No output assigned</span>' if not z['output_id'] else '<span class="at-wa">○ Not observed</span>')
 print('<tr><td>#'+E(z['id'])+'</td><td>'+E(z['name'])+'</td><td>'+E(z['output_id'])+'</td><td>'+E(z['playerName'])+'</td><td>'+E(z['host'])+'</td><td>'+E(z['playerId'])+'</td><td>'+st+'</td></tr>')
if not zones: print('<tr><td colspan="7">No zones found in config.json</td></tr>')
print('</table></div>')

print('<div class="at-box"><h2>Squeezelite players</h2><table class="at-table"><tr><th>Zone</th><th>Name</th><th>IP</th><th>playerId</th><th>Status</th></tr>')
for z in players:
 print('<tr><td>#'+E(z['id'])+' '+E(z['name'])+'</td><td>'+E(z['playerName'])+'</td><td>'+E(z['host'])+'</td><td>'+E(z['playerId'])+'</td><td class="at-ok">✓ Configured</td></tr>')
if not players: print('<tr><td colspan="5">None detected</td></tr>')
print('</table></div>')

ms=settings.get('miniservers',[])
while len(ms)<2: ms.append({'name':'Miniserver '+str(len(ms)+1),'host':'','user':''})
print('<div class="at-box"><h2>Local Miniserver reference</h2><p>These details are local notes. Configure the actual Miniserver connection in Sonn; saving here does not establish that connection.</p><form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="en"><input type="hidden" name="action" value="save"><table class="at-table"><tr><th>Name</th><th>IP / Host</th><th>Username</th></tr>')
for i,m in enumerate(ms[:2],1):
 print('<tr><td><input class="at-input" name="name%d" value="%s"></td><td><input class="at-input" name="host%d" value="%s"></td><td><input class="at-input" name="user%d" value="%s"></td></tr>'%(i,E(m.get('name')),i,E(m.get('host')),i,E(m.get('user'))))
print('</table><button type="submit" class="at-btn">Save local details</button></form></div>')
print('<div class="at-box" id="audiodek-new-room"><h2>Add a room</h2><ol><li>Create the audio zone in Loxone Config and deploy the configuration to the Miniserver.</li><li>Once Sonn receives the zone, click Refresh / Rediscover.</li><li>Select the room without an output, then choose a player detected by Sonn or enter its details manually.</li></ol><p>AudioDek preserves Loxone identifiers. If the room has no Soloist data yet, it creates a compatible backup recording that absence before assigning the player.</p>')
unassigned = [z for z in zones if not z['output_id']]
if unassigned:
 print('<h3>Rooms awaiting assignment</h3><ul>')
 for z in unassigned:
  print('<li><a data-ajax="false" href="index.cgi?focus_zone='+E(z['id'])+'#audiodek-player">#'+E(z['id'])+' — '+E(z['name'])+'</a></li>')
 print('</ul>')
else:
 print('<p>All detected rooms have an output assigned. New rooms will appear here when received from Loxone.</p>')
print('</div>')

print('<div class="at-box" id="audiodek-player"><h2>Manage a room\'s player</h2>')
print('<p>Assign or remove a Squeezelite player while preserving the Loxone room. A backup is created before applying. Sonn restarts and playback is interrupted during the change.</p>')
print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="en"><input type="hidden" name="action" value="output_preview"><label>Room<select name="output_zone" class="at-input" style="width:100%;margin:8px 0"><option value="">Select a room...</option>')
for z in zones:
 print('<option value="'+E(z['id'])+'"'+(' selected' if (G('output_zone') or G('focus_zone'))==z['id'] else '')+'>#'+E(z['id'])+' — '+E(z['name'])+' — '+E(z['playerName'] or 'No player')+'</option>')
print('</select></label><label>Operation<select name="output_operation" class="at-input" style="width:100%;margin:8px 0"><option value="assign">Assign / replace player</option><option value="detach"'+(' selected' if G('output_operation')=='detach' else '')+'>Remove player</option></select></label>')
print('<label>Detected player<select name="detected_player" class="at-input" style="width:100%;margin:8px 0"><option value="">Enter details manually...</option>')
selected_room = G('output_zone') or G('focus_zone')
for p in detected:
 unavailable = not p['connected'] or not p['valid_ip'] or any(i != selected_room for i in p['owners'])
 suffix = ' — assigned to '+','.join('#'+i for i in p['owners']) if p['owners'] else ' — available'
 if not p['connected']: suffix += ' — disconnected'
 if not p['valid_ip']: suffix += ' — Unsupported IP'
 print('<option value="'+E(p['player_id'])+'"'+(' disabled' if unavailable else '')+(' selected' if G('detected_player') == p['player_id'] and not unavailable else '')+'>'+E(p['name']+' — '+p['host']+suffix)+'</option>')
print('</select></label><p>Select an available player: AudioDek retrieves its name, IP and playerId from Sonn. The manual fields below are used only when manual entry is selected. To remove a player, select the room and operation.</p>')
for label, key, placeholder in [('Player name','output_name','e.g. Kitchen'),('Player IP address','output_ip','192.168.1.xxx'),('MAC / playerId','output_mac','aa:bb:cc:dd:ee:ff')]:
 print('<label>'+E(label)+'<input class="at-input" style="width:100%;margin:8px 0" name="'+key+'" value="'+E(G(key))+'" placeholder="'+E(placeholder)+'"></label>')
print('<button type="submit" class="at-btn">Review player change</button></form>')
if output_preview:
 t = output_preview['target']; d = output_preview['data']; o = t.get('output') or {}
 print('<h3>Review before applying</h3><table class="at-table">')
 for label, value in [('Room','#'+str(t['id'])+' '+str(t.get('name',''))),('Action','Remove player' if d['operation']=='detach' else 'Assign / replace player'),('New player',o.get('playerName','No player')),('IP',o.get('host','—')),('MAC',o.get('playerId','—'))]:
  print('<tr><td>'+E(label)+'</td><td>'+E(value)+'</td></tr>')
 word = 'REMOVE' if d['operation']=='detach' else 'ASSIGN'
 print('</table><p>The room and its Loxone identifiers are preserved. The review expires after 15 minutes; if configuration changes, review it again.</p>')
 print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="en"><input type="hidden" name="action" value="output_confirm"><input type="hidden" name="output_ticket" value="'+E(output_preview['token'])+'"><label>Type '+word+'<input name="output_confirm_word" class="at-input" style="width:100%;margin:8px 0" autocomplete="off"></label><button type="submit" class="at-btn">Confirm change</button></form>')
print('<h3>Room names and creation</h3><p>With Loxone integration, create or rename the room in Loxone Config and synchronize with Sonn. Then refresh and assign its player here.</p>')
print('<p>To recover a previous configuration, use <a href="#audiodek-restore">Restore backup</a>. Check changes made since the backup: restoration recovers the complete configuration and the selected room\'s Soloist data.</p></div>')

print('<div class="at-box"><h2>Transactional backup</h2><p>Saves <code>config.json</code> and only <code>zone-X/data</code>; does not copy Soloist caches.</p><form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="en"><input type="hidden" name="action" value="zone_backup"><select name="backup_zone" class="at-input" style="width:100%;margin-bottom:8px"><option value="">Select a room...</option>')
for z in zones:
 print('<option value="'+E(z['id'])+'">#'+E(z['id'])+' — '+E(z['name'])+' — '+E(z['playerName'])+'</option>')
print('</select><button type="submit" class="at-btn">Create room backup</button></form></div>')
backs=list_backups()
print('<div class="at-box"><h2>Backup history</h2>')
if not backs:
 print('<p>No transactional backups yet.</p>')
else:
 print('<table class="at-table"><tr><th>Date</th><th>Zone</th><th>Room</th><th>Operation</th><th>Status</th></tr>')
 for b in backs[:20]:
  print('<tr><td>'+E(b.get('created'))+'</td><td>#'+E(b.get('zoneId'))+'</td><td>'+E(b.get('room'))+'</td><td>'+E(b.get('operation'))+'</td><td class="at-ok">✓ '+E(b.get('status','backup'))+'</td></tr>')
 print('</table>')
print('</div>')
print('<div class="at-box" id="audiodek-restore"><h2>Restore backup</h2><p>Safety step: verifies the backup before allowing an actual restore.</p>')
if backs:
 print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="en"><input type="hidden" name="action" value="restore_preview"><select name="restore_backup" class="at-input" style="width:100%;margin-bottom:8px">')
 for b in backs:
  print('<option value="'+E(b.get('_name'))+'">'+E(b.get('created'))+' — #'+E(b.get('zoneId'))+' — '+E(b.get('room'))+'</option>')
 print('</select><button type="submit" class="at-btn">Verify / Preview restore</button></form>')
else:
 print('<p>No backups available.</p>')
if restore_preview:
 if restore_preview['errors']:
  print('<div class="at-wa"><h3>Invalid backup</h3><ul>')
  for e in restore_preview['errors']: print('<li>'+E(e)+'</li>')
  print('</ul></div>')
 else:
  m,d=restore_preview['info']
  cf=os.path.join(d,'config.json'); sf=os.path.join(d,'soloist-data.tar.gz')
  print('<div class="at-ok"><h3>✓ Backup verified successfully</h3></div><table class="at-table">')
  for a,b in [('Backup',restore_preview['name']),('Zone','#'+str(m.get('zoneId',''))+' '+str(m.get('room',''))),
              ('Player',m.get('playerName','')),('IP',m.get('ip','')),('playerId',m.get('playerId','')),
              ('config.json',str(os.path.getsize(cf))+' bytes'),('Soloist data',str(os.path.getsize(sf))+' bytes'),
              ('Actual restore','Available after confirmation; restarts Sonn')]:
   print('<tr><td>'+E(a)+'</td><td>'+E(b)+'</td></tr>')
  print('</table><p><b>No files have been changed.</b></p>')
  print('<div class="at-wa"><h3>Actual restore</h3><p>AudioDek first creates an emergency backup, stops Sonn, restores data, starts Sonn and verifies the zone. On failure it attempts automatic rollback. An independent final safeguard checks and recovers sonn-core before finishing.</p></div>')
  print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="en"><input type="hidden" name="action" value="restore_confirm"><input type="hidden" name="restore_backup" value="'+E(restore_preview['name'])+'"><input class="at-input" style="width:100%;margin-bottom:8px" name="confirm_text" placeholder="Type RESTORE"><button type="submit" class="at-btn">Confirm restore</button></form>')
print('</div></div>')
