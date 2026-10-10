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
   raise RuntimeError('No se pudo copiar Soloist data: '+err.decode(errors='ignore'))
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
  return None,['Backup no válido.']
 mf=os.path.join(d,'manifest.json'); cf=os.path.join(d,'config.json'); sf=os.path.join(d,'soloist-data.tar.gz')
 errors=[]
 m=load(mf,{})
 if not m: errors.append('manifest.json ausente o inválido.')
 try:
  cfg=load(cf,None)
  if not isinstance(cfg,dict): errors.append('config.json inválido.')
 except: errors.append('config.json inválido.')
 if not os.path.isfile(sf) or os.path.getsize(sf)==0: errors.append('soloist-data.tar.gz ausente o vacío.')
 else:
  try:
   r=subprocess.run(['tar','-tzf',sf],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=10)
   if r.returncode: errors.append('soloist-data.tar.gz está dañado.')
  except Exception: errors.append('No se pudo verificar soloist-data.tar.gz.')
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
 if docker_ok(): return True,'Sonn ya estaba Running'
 last=''
 for attempt in range(3):
  try:
   r=subprocess.run(['sudo','docker','start','sonn-core'],capture_output=True,text=True,timeout=35)
   last=(r.stdout+' '+r.stderr).strip()
  except Exception as e:
   last=str(e)
  end=time.time()+timeout
  while time.time()<end:
   if docker_ok(): return True,'Sonn recuperado (intento %d)'%(attempt+1)
   time.sleep(2)
 return False,last or 'No fue posible arrancar sonn-core'

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
 if not z: raise RuntimeError('La zona actual #'+zid+' no existe; restauración cancelada.')
 expected={str(x['id']) for x in zones if x.get('soloist')}
 steps=[]
 emergency=make_zone_backup(z,'pre-restore-emergency'); steps.append('✓ Backup de emergencia')
 current_cfg=SONN; backup_cfg=os.path.join(d,'config.json'); archive=os.path.join(d,'soloist-data.tar.gz')
 def restore_files(folder):
  shutil.copy2(os.path.join(folder,'config.json'),current_cfg)
  hd='/opt/loxberry/data/plugins/audioserver4home/data/soloist/zone-'+zid+'/data'
  shutil.rmtree(hd,ignore_errors=True); os.makedirs(hd,exist_ok=True)
  with open(os.path.join(folder,'soloist-data.tar.gz'),'rb') as f:
   q=subprocess.run(['tar','-xzf','-','-C',hd],stdin=f,capture_output=True,timeout=30)
   if q.returncode: raise RuntimeError('Error extrayendo Soloist data.')
 try:
  subprocess.run(['sudo','docker','stop','-t','20','sonn-core'],check=True,timeout=35,capture_output=True,text=True)
  steps.append('✓ Sonn detenido')
  restore_files(d); steps+=['✓ config.json restaurado','✓ Soloist zone-'+zid+'/data restaurado']
  subprocess.run(['sudo','docker','start','sonn-core'],check=True,timeout=35,capture_output=True,text=True)
  if not wait_container(45): raise RuntimeError('sonn-core no quedó Running.')
  steps.append('✓ Sonn iniciado')
  import time; time.sleep(12)
  cfg=load(SONN,{})
  actual={str(x.get('id')) for x in cfg.get('zones',[])}
  missing={str(x['id']) for x in zones}-actual
  if missing: raise RuntimeError('Faltan zonas tras arranque: '+','.join(sorted(missing)))
  steps.append('✓ %d zonas detectadas'%len(zones))
  # Soloist can take time; require every zone that was active before restore.
  deadline=time.time()+45; active=set()
  while time.time()<deadline:
   active=active_soloist_zones()
   if expected.issubset(active): break
   time.sleep(3)
  absent=expected-active
  if absent: raise RuntimeError('Soloist no iniciado en zona(s): '+','.join(sorted(absent)))
  steps.append('✓ Soloist activos: '+','.join(sorted(expected)))
  return emergency,steps
 except Exception as original:
  steps.append('✗ '+str(original)); steps.append('→ ROLLBACK')
  try:
   subprocess.run(['sudo','docker','stop','-t','20','sonn-core'],timeout=35,capture_output=True)
   ed=os.path.join(backup_root(),emergency); restore_files(ed)
   subprocess.run(['sudo','docker','start','sonn-core'],check=True,timeout=35,capture_output=True)
   if not wait_container(45): raise RuntimeError('Sonn no arrancó durante rollback.')
   steps.append('✓ Rollback aplicado y Sonn iniciado')
  except Exception as rb:
   steps.append('✗ FALLO DE ROLLBACK: '+str(rb))
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
  raise RuntimeError(('Restauración/rollback: '+str(error)+' | ' if error else '')+
                     'FALLO CRÍTICO: sonn-core quedó detenido y no pudo recuperarse: '+detail)
 if error:
  raise RuntimeError(str(error)+' | ✓ Protección final: sonn-core Running')
 emergency,steps=result
 steps.append('✓ Protección final: sonn-core Running')
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
settings=load(SET,{'miniservers':[{'name':'Miniserver Principal','host':'','user':''},{'name':'Miniserver 2','host':'','user':''}]})

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
 if not room: errors.append('Falta el nombre de la habitación.')
 if not player: errors.append('Falta el nombre del reproductor.')
 try:
  ipaddress.IPv4Address(ip)
 except ValueError:
  errors.append('La IP no tiene un formato IPv4 válido.')
 if not re.match('^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$',pid): errors.append('El playerId/MAC no tiene un formato válido.')
 if not zoneid.isdigit(): errors.append('El Zone ID debe ser numérico.')
 if any(z['id']==zoneid for z in zones): errors.append('El Zone ID #%s ya existe en Sonn.'%zoneid)
 if any(z['playerId'].lower()==pid for z in zones if z['playerId']): errors.append('Ese playerId ya está asignado.')
 if any(z['host']==ip for z in zones if z['host']): errors.append('Esa IP ya está asignada a un reproductor.')
 preview={'room':room,'player':player,'ip':ip,'pid':pid,'zoneid':zoneid,'errors':errors}


restore_result=None
if G('action')=='restore_confirm':
 bn=G('restore_backup')
 confirm=G('confirm_text').strip().upper()
 if confirm!='RESTAURAR':
  msg='ERROR: escribe RESTAURAR para confirmar.'
 else:
  try:
   with room_outputs.operation_lock(backup_root()):
    emergency,restore_steps=restore_backup_real(bn)
   msg='✓ Restauración completada y verificada. Backup de emergencia: '+emergency+' | '+' | '.join(restore_steps)
   restore_result=True
  except Exception as e:
   msg='ERROR durante restauración. Se intentó rollback automático: '+str(e)
   restore_result=False

restore_preview=None
if G('action')=='restore_preview':
 bn=G('restore_backup')
 info,errs=validate_backup(bn)
 restore_preview={'name':bn,'info':info,'errors':errs}
 if errs: msg='ERROR: el backup seleccionado no supera la verificación.'
 else: msg='✓ Backup verificado. Restauración todavía NO ejecutada.'

if G('action')=='zone_backup':
 zid=G('backup_zone')
 z=next((x for x in zones if x['id']==zid),None)
 if not z:
  msg='ERROR: selecciona una zona válida.'
 else:
  try:
   msg='✓ Backup transaccional creado: '+make_zone_backup(z,'manual')
  except Exception as e:
   msg='ERROR creando backup: '+str(e)
elif G('action')=='backup':
 try:
  os.makedirs(BACK,exist_ok=True)
  dst=BACK+'/config-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.json'
  shutil.copy2(SONN,dst); msg='Backup creado: '+dst
 except Exception as e: msg='ERROR: '+str(e)
elif G('action')=='save':
 ms=[]
 for i in (1,2):
  ms.append({'name':G('name%d'%i,'Miniserver %d'%i),
             'host':G('host%d'%i,'').strip(),
             'user':G('user%d'%i,'')})
 os.makedirs(os.path.dirname(SET),exist_ok=True)
 with open(SET,'w') as f: json.dump({'miniservers':ms},f,indent=2)
 settings={'miniservers':ms}; msg='Datos guardados localmente. Loxone no ha sido modificado.'

discovery_folder = os.path.dirname(SET)
if G('action') in ('sonn_connect', 'sonn_disconnect'):
 try:
  if method != 'POST': raise ValueError('Usa el formulario para conectar con Sonn.')
  if G('action') == 'sonn_connect':
   sonn_discovery.connect(discovery_folder, G('sonn_user'), G('sonn_password'))
   msg = '✓ Conexión con Sonn preparada. La contraseña no se guarda en AudioDek.'
  else:
   sonn_discovery.disconnect(discovery_folder)
   msg = 'Sesión de consulta de Sonn desconectada.'
 except Exception as e:
  msg = 'ERROR: ' + str(e)
detected, discovery_error = sonn_discovery.inventory(discovery_folder, c.get('zones', []) if isinstance(c, dict) else [])

output_preview = None
if G('action') in ('output_preview', 'output_confirm'):
 try:
  if method != 'POST': raise ValueError('Usa el formulario para esta operación.')
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
   word = 'RETIRAR' if data['operation'] == 'detach' else 'ASIGNAR'
   if G('output_confirm_word').strip().upper() != word:
    raise ValueError('Escribe ' + word + ' para confirmar. Revisa de nuevo la operación.')
   services = {'docker_ok':docker_ok, 'active':active_soloist_zones, 'parse':parse_zones,
               'backup':make_zone_backup, 'validate':validate_backup, 'wait':wait_container, 'ensure':ensure_sonn_running}
   backup, steps = room_outputs.apply(SONN, backup_root(), data['fingerprint'], data['zid'],
                                     data['operation'], data['fields'], services)
   msg = '✓ Cambio de reproductor completado. ' + ' | '.join(steps)
   c = load(SONN, {}); zones = parse_zones(c)
   players = [z for z in zones if z['output_id'].lower() == 'squeezelite']
   solo = soloist_runtime()
 except Exception as e:
  msg = 'ERROR: ' + str(e)

if G('action') == 'output_confirm' and msg.startswith('✓'):
 detected, discovery_error = sonn_discovery.inventory(discovery_folder, c.get('zones', []))

print('<style>\n.at-wrap{max-width:1180px;margin:0 auto}.at-hero{background:#101828;color:#fff;padding:22px;border-radius:12px;margin-bottom:14px}\n.at-brand{display:flex;align-items:center;gap:20px;flex-wrap:wrap}.at-logo{background:#f8fafc;border-radius:18px;padding:8px;box-sizing:border-box;width:128px;height:128px;object-fit:contain;flex:none}.at-brand-copy{flex:1;min-width:200px}.at-brand-copy h1{margin:0 0 8px}.at-brand-copy .at-tag{margin-top:12px}\n.at-tag{background:#d1fadf;color:#05603a;padding:6px 10px;border-radius:18px;display:inline-block}\n.at-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}.at-card,.at-box{background:#fff;border:1px solid #ddd;border-radius:10px;padding:16px}\n.at-box{margin:12px 0}.at-ok{color:#087443;font-weight:bold}.at-wa{color:#b54708;font-weight:bold}\n.at-table{width:100%;border-collapse:collapse}.at-table th,.at-table td{text-align:left;padding:9px;border-bottom:1px solid #ddd}\n.at-btn{width:100%;padding:10px;font-weight:bold}.at-input{padding:8px;width:90%;box-sizing:border-box}\n@media(max-width:800px){.at-grid{grid-template-columns:1fr 1fr}}\n</style><div class="at-wrap"><div class="at-hero at-brand"><img class="at-logo" src="/system/images/icons/audiodek/icon_512.png" alt="Logo AudioDek" width="128" height="128"><div class="at-brand-copy"><h1>AudioDek</h1><b>Multiroom Manager for Loxone · v1.0.7</b><br><span class="at-tag">GESTIÓN DE REPRODUCTORES CON BACKUP</span></div></div>')
print('<div class="at-box" id="audiodek-guide"><h2>Guía práctica de instalación</h2><p>Preparación de LoxBerry, Sonn, Loxone Config y piCorePlayer. Incluye imágenes explicativas con nombres de ejemplo.</p><p><a href="guide-es.html" data-ajax="false">Abrir guía completa para leer o imprimir</a></p><details><summary>Leer la guía aquí</summary><section class="ad-guide" aria-labelledby="ad-guide-title">\n<h2 id="ad-guide-title">Guía práctica: tu primera habitación con AudioDek</h2>\n<p>Para una instalación nueva de <strong>LoxBerry 4.0 en x86_64</strong>. Sigue los pasos en orden y empieza con una sola habitación. AudioDek te ayuda a asignar reproductores y recuperar cambios; la reproducción la realiza Sonn y el control diario queda en la app Loxone.</p>\n<nav aria-label="Pasos de la guía"><a href="#ad-before">Requisitos</a> · <a href="#ad-server">Servidor</a> · <a href="#ad-loxone">Loxone</a> · <a href="#ad-player">Reproductor</a> · <a href="#ad-assign">Asignación</a> · <a href="#ad-test">Prueba</a> · <a href="#ad-backup">Backup</a> · <a href="#ad-help">Problemas frecuentes</a></nav>\n\n<h3 id="ad-before">1. Reúne lo necesario</h3>\n<ul><li>Un LoxBerry 4.0 en un PC o máquina virtual x86_64. Esta edición de AudioDek no es un paquete para instalar en un LoxBerry ARM.</li><li>Un Miniserver accesible y Loxone Config, con permiso para guardar su configuración.</li><li>Audioserver4Home y Sonn <strong>4.0.0-beta.19</strong>, la versión examinada para esta edición. No des por compatible otra versión sin comprobarla.</li><li>Para la primera habitación: una Raspberry Pi compatible con piCorePlayer, tarjeta microSD, alimentación, red y salida de audio adecuada (por ejemplo DAC USB), amplificador y altavoces según tu montaje.</li><li>Los equipos deben poder comunicarse en tu red. Para empezar, conecta por Ethernet.</li></ul>\n<p><strong>Anota tres direcciones diferentes:</strong> IP de LoxBerry/Sonn, IP del Miniserver e IP del reproductor. Cada equipo debe tener su propia dirección. Puedes consultarlas en la lista de dispositivos de tu router; una reserva DHCP ayuda a mantenerlas.</p>\n<p>AudioDek no instala Sonn, no graba tarjetas piCorePlayer ni crea bloques en Loxone Config. Su asistente te indica qué hacer en cada aplicación.</p>\n\n<h3 id="ad-server">2. Prepara Sonn e instala AudioDek</h3>\n<ol><li>En la gestión de plugins de LoxBerry, instala <strong>Audioserver4Home</strong> siguiendo su documentación. Comprueba que Sonn esté arrancado y revisa la versión que ejecuta. No actualices ni cambies de versión a ciegas si ya tienes un sistema funcionando.</li><li>Abre la administración de Sonn desde Audioserver4Home o entra en <code>http://IP_DE_LOXBERRY:7090</code>, sustituyendo el texto por tu dirección real.</li><li>Completa la preparación inicial y crea la cuenta administradora si Sonn te lo pide. Conserva sus credenciales.</li><li>Instala el ZIP de <strong>AudioDek</strong> desde Plugins de LoxBerry y abre su panel.</li><li>Pulsa <strong>Actualizar / Redetectar</strong>. En Diagnóstico guiado deben aparecer configuración legible y Sonn en marcha. En una instalación todavía sin zonas es normal que no aparezcan habitaciones.</li></ol>\n<p><strong>Antes de seguir:</strong> debes poder abrir Sonn y AudioDek. Si falta la configuración o Sonn está detenido, resuelve primero ese punto en Audioserver4Home.</p>\n<p>Documentación: <a href="https://github.com/mschlenstedt/LoxBerry-Plugin-Audioserver4Home">Audioserver4Home</a> y <a href="https://sonn-audio.github.io/docs/setup/">preparación inicial de Sonn</a>.</p>\n\n<h3 id="ad-loxone">3. Crea la primera habitación en Loxone Config</h3>\n<ol><li>Guarda una copia de tu proyecto de Loxone Config antes de modificarlo.</li><li>En Sonn, entra en <strong>Zones / Zonas</strong> y elige la integración con Loxone (<strong>Loxone integrated</strong>). Consulta allí el host y el número de serie que Sonn proporciona.</li><li>En Loxone Config, incorpora el Audioserver usando esos datos. La dirección es la del servidor Sonn; el número de serie es el que muestra Sonn.</li><li>Crea un bloque <strong>Reproductor Audio / Audio Player</strong>, dale un nombre claro (por ejemplo Cocina), asígnalo a su habitación y vincúlalo a una salida disponible del Audioserver.</li><li>Envía la configuración al Miniserver. Si el emparejamiento inicial requiere reiniciarlo, hazlo cuando puedas interrumpir su funcionamiento, siguiendo la documentación de Sonn.</li><li>Vuelve a AudioDek y pulsa <strong>Actualizar / Redetectar</strong>. La habitación debe aparecer. Puede estar sin reproductor: lo asignarás después.</li></ol>\n<p><strong>No copies un número de serie de otro montaje ni añadas otro Audioserver con la misma identidad para obtener más salidas.</strong> Si necesitas más capacidad, consulta la configuración de salidas y extensiones de Sonn antes de continuar. AudioDek no inventa números de zona ni modifica el proyecto de Loxone.</p>\n<p>Los campos <strong>Referencia local de Miniservers</strong> de AudioDek son solo anotaciones; guardarlos no conecta Sonn con el Miniserver.</p>\n<p>Referencia: <a href="https://sonn-audio.github.io/">integración Loxone de Sonn</a> y <a href="https://sonn-audio.github.io/docs/troubleshooting/">ayuda de emparejamiento</a>. Los nombres de los menús pueden variar según la versión y el idioma.</p>\n\n<div class="ad-loxone-photos">\n<h4>Vista general del Audioserver y sus habitaciones</h4>\n<figure><img src="guide-images/es/audioserver-layout.png" width="1728" height="910" alt="Ejemplo anonimizado: salidas directas de Audioserver y una zona adicional bajo Tree Turbo y Stereo Extension" style="max-width:100%;width:700px;height:auto"><figcaption>Captura editada para eliminar los nombres y números de la instalación original. Las etiquetas Habitacion A a E son ejemplos. Se mantiene la jerarquía del montaje.</figcaption></figure>\n<p><strong>Cómo leer el árbol:</strong> las habitaciones A a D cuelgan de las salidas directas del Audioserver. La habitación E aparece bajo <strong>Tree Turbo → Stereo Extension → salida derecha → Reproductor Audio</strong>. Izquierda y Derecha son canales de Loxone; no identifican la IP ni la MAC del reproductor. El otro Audioserver que aparece arriba pertenece al ejemplo y no es necesario para empezar.</p>\n<p>La Stereo Extension de este ejemplo se usa con la emulación de Sonn. Si tienes una salida disponible, no necesitas añadir una extensión para la primera habitación. Para ampliar, comprueba el soporte y los identificadores que requiere tu versión de Sonn; no copies identidades de otro montaje ni dupliques un Audioserver con el mismo host y número de serie.</p>\n<h4>Conexión del bloque Reproductor Audio</h4>\n<figure><img src="guide-images/es/audio-player-block.png" width="2170" height="725" alt="Ejemplo anonimizado: bloque Reproductor Audio conectado desde Stereo LR a una salida de audio" style="max-width:100%;width:700px;height:auto"><figcaption>El bloque de la habitación se conecta desde <strong>Stereo LR</strong> al objeto <strong>Salida de audio</strong>. Los nombres originales han sido sustituidos por etiquetas genéricas. El símbolo rojo refleja el estado del enlace al tomar la captura; no es una confirmación de instalación terminada.</figcaption></figure>\n<p>Después de guardar y enviar al Miniserver, comprueba el emparejamiento en Loxone y que la zona aparezca en AudioDek. Loxone Config define el bloque y la salida; Sonn recibe la zona; AudioDek la asocia con el reproductor Squeezelite. Su IP y playerId son distintos del número de serie del Audioserver o de la extensión.</p>\n</div>\n<h3 id="ad-player">4. Prepara piCorePlayer para esa habitación</h3>\n<ol><li>Obtén piCorePlayer desde su sitio oficial y graba su imagen en una tarjeta microSD siguiendo su guía. Selecciona con cuidado la tarjeta que vas a grabar.</li><li>Introduce la tarjeta en la Raspberry Pi, conecta Ethernet, el equipo de audio y la alimentación.</li><li>Busca su IP en el router o en la pantalla de arranque y abre <code>http://IP_DEL_REPRODUCTOR</code>.</li><li>Completa la preparación inicial de piCorePlayer. En <strong>Squeezelite Settings</strong>, configura la salida que realmente utilizas (USB, DAC u otra) y un nombre identificable, como Cocina. Guarda y reinicia Squeezelite o el equipo cuando lo solicite.</li><li>Configura Squeezelite para conectarse a la <strong>IP de Sonn/LoxBerry</strong>. En piCorePlayer el campo puede llamarse servidor o LMS. Aquí Sonn hace de servidor para Squeezelite; no pongas la IP del Miniserver ni la de la propia Raspberry Pi. No necesitas instalar otro LMS para este recorrido.</li><li>Comprueba que Squeezelite esté arrancado y vuelve a actualizar AudioDek.</li></ol>\n<p>La <strong>IP del reproductor</strong> identifica la Raspberry Pi. El <strong>playerId</strong> identifica su instancia Squeezelite y suele tener formato MAC. No uses como playerId el número de serie del Audioserver o de una Stereo Extension. Si eliges un equipo detectado, AudioDek obtiene ambos datos de Sonn.</p>\n<p>Guía del fabricante del software: <a href="https://docs.picoreplayer.org/getting-started/">primeros pasos con piCorePlayer</a>. Sus ejemplos usan LMS; en este montaje dirige el cliente Squeezelite a Sonn.</p>\n\n<h3 id="ad-assign">5. Selecciona el reproductor en AudioDek</h3>\n<ol><li>Mira <strong>Reproductores detectados por Sonn</strong>. Si aparece un aviso de acceso pendiente, despliega <strong>Acceso a Sonn</strong> e introduce una cuenta administradora de Sonn. Pulsa <strong>Conectar para consultar reproductores</strong>. AudioDek no guarda la contraseña; conserva la sesión de consulta.</li><li>Comprueba nombre, IP y estado del equipo. La lista muestra clientes conocidos por Sonn, no todos los dispositivos de la red. Si aparece vacío, revisa el paso anterior.</li><li>En <strong>Gestionar reproductor de una habitación</strong>, elige la habitación y la operación <strong>Asignar / cambiar reproductor</strong>.</li><li>En <strong>Reproductor detectado</strong>, elige un equipo conectado y libre. Deja los campos manuales sin rellenar: AudioDek toma los datos de Sonn.</li><li>Pulsa <strong>Revisar cambio de reproductor</strong> y verifica habitación, nombre, IP y playerId.</li><li>Cuando todo sea correcto, escribe <strong>ASIGNAR</strong> y pulsa <strong>Confirmar cambio real</strong>. Se crea un backup previo y se reinicia Sonn; durante el cambio se interrumpe la reproducción.</li><li>Comprueba el resultado mostrado y vuelve a actualizar el panel.</li></ol>\n<p><strong>Alternativa manual:</strong> elige Introducir datos manualmente y completa nombre, IP IPv4 y playerId reales del reproductor. Cada reproductor debe tener una identidad única. AudioDek rechaza datos duplicados; no reutilices el de otra habitación.</p>\n<p><strong>Si todavía no tienes reproductor:</strong> deja la habitación pendiente. No introduzcas una IP o MAC ficticias.</p>\n\n<h3 id="ad-test">6. Comprueba el sonido y añade las siguientes habitaciones</h3>\n<ol><li>En Sonn, prepara una fuente de música que puedas reproducir, como una emisora o tu biblioteca.</li><li>Abre la app Loxone, entra en la habitación y reproduce esa fuente con un volumen moderado.</li><li>Comprueba en los altavoces reproducción, pausa y volumen. Un estado Soloist activo o un reproductor conectado no garantiza por sí solo que la salida de audio y el amplificador funcionen.</li><li>Si funciona, prepara la siguiente habitación repitiendo los pasos 3 a 6 con su propio reproductor.</li></ol>\n<p><strong>Resultado esperado:</strong> la habitación existe en Loxone, AudioDek muestra su salida Squeezelite, Sonn ve el reproductor conectado y escuchas música en esa habitación.</p>\n\n<h3 id="ad-backup">7. Guarda un backup y conoce su alcance</h3>\n<p>En <strong>Backup transaccional</strong>, selecciona la habitación y pulsa <strong>Crear backup seguro de la habitación</strong>. Comprueba su entrada en el historial y usa <strong>Verificar / Previsualizar restauración</strong> para revisar la copia sin restaurar.</p>\n<p><strong>Esta copia guarda la configuración de todas las zonas, pero los datos Soloist solo de la habitación seleccionada.</strong> No es un backup completo de todos los datos de audio ni del proyecto del Miniserver. Conserva también tu copia de Loxone Config y una copia del sistema por los medios de LoxBerry.</p>\n<p>Para restaurar de verdad hay que escribir <strong>RESTAURAR</strong> y confirmar. Se reinicia Sonn. La restauración recupera la configuración completa del momento del backup y puede revertir cambios posteriores en otras habitaciones. No la uses para comprobar que la lista se muestra bien.</p>\n\n<h3 id="ad-help">Si algo no sale como esperabas</h3>\n<div class="ad-scroll"><table class="at-table"><thead><tr><th>Lo que ves</th><th>Qué comprobar</th></tr></thead><tbody>\n<tr><td>No hay habitaciones</td><td>Integración Loxone activa en Sonn, identidad correcta del Audioserver, bloque vinculado a una salida y configuración enviada al Miniserver. Después actualiza AudioDek.</td></tr>\n<tr><td>Acceso a Sonn pendiente o caducado</td><td>Conecta desde Acceso a Sonn con una cuenta administradora válida de Sonn. Los datos guardados como referencia local del Miniserver no sirven como sesión de consulta.</td></tr>\n<tr><td>No se detecta el reproductor</td><td>Alimentación, red, Squeezelite arrancado y dirigido a Sonn. Si funciona con otro servidor, cambia el servidor del cliente al que corresponde a este montaje.</td></tr>\n<tr><td>El reproductor ya está asignado</td><td>Revisa qué habitación lo utiliza. Cada habitación necesita el reproductor que corresponda; no dupliques IP o playerId para evitar el aviso.</td></tr>\n<tr><td>Soloist activo, pero no suena</td><td>Conexión del reproductor con Sonn, fuente reproducible, salida de audio en piCorePlayer, DAC, cables, amplificador, altavoces y volumen.</td></tr>\n<tr><td>No hay permisos para aplicar</td><td>Revisa la instalación y los permisos con quien administra LoxBerry. No concedas permisos generales a todo el sistema ni cambies archivos a ciegas.</td></tr>\n<tr><td>No se puede consultar Sonn en 7090</td><td>Sonn en marcha y administración accesible. Esta edición consulta Sonn en el mismo LoxBerry y puerto local 7090; otro servidor o puerto requiere adaptar la configuración del plugin.</td></tr>\n</tbody></table></div>\n<p>Esta guía acompaña AudioDek v1.0.7. La lectura y la consulta no aplican cambios de audio; asignar, retirar o restaurar sí los aplica. La detección autenticada sigue pendiente de validación real en nuestro montaje. No se ha completado todavía una prueba de instalación desde cero.</p>\n</section>\n</details></div>')
if msg: print('<div class="at-box" id="audiodek-result" role="status"><h2>Resultado de la operación</h2>'+E(msg)+'</div>')
print('<div class="at-grid"><div class="at-card"><b>Sonn config</b><br><span class="at-ok">✓ '+('Detectado' if os.path.exists(SONN) else 'No')+'</span></div><div class="at-card"><b>Reproductores asignados</b><br><b>'+str(len(players))+'</b></div><div class="at-card"><b>Zonas dinámicas</b><br><b>'+str(len(zones))+'</b></div><div class="at-card"><b>Soloist activos</b><br><b>'+str(len(solo))+'</b></div></div>')
print('<form action="index.cgi" data-ajax="false" method="get"><button type="submit" class="at-btn">↻ Actualizar / Redetectar</button></form>')

print('<div class="at-box" id="audiodek-diagnostics"><h2>Diagnóstico guiado</h2><p>Comprueba la configuración, el servicio y la conexión anunciada por Sonn. Un proceso Soloist activo por sí solo no confirma que el reproductor esté conectado.</p><table class="at-table"><tr><th>Comprobación</th><th>Resultado / siguiente paso</th></tr>')
try:
 diagnostic_cfg, _, _ = room_outputs.read_config(SONN)
 config_ok = True
except Exception:
 diagnostic_cfg = {'zones': []}; config_ok = False
checks = sonn_discovery.diagnose(diagnostic_cfg['zones'], set(solo), detected, discovery_error, config_ok, docker_ok(), os.access(os.path.dirname(SONN), os.W_OK | os.X_OK))
for state, title, advice in checks:
 print('<tr><td>'+E({'ok':'✓ ', 'warning':'⚠ ', 'pending':'○ '}[state]+title)+'</td><td>'+E(advice)+'</td></tr>')
print('</table></div>')
print('<div class="at-box"><h2>Reproductores detectados por Sonn</h2><p>La lista procede de Sonn; no es un escaneo de toda la red. El equipo debe estar encendido y su Squeezelite conectado a este servidor.</p>')
if discovery_error:
 print('<p class="at-wa">'+E(discovery_error)+'</p>')
else:
 print('<table class="at-table"><tr><th>Nombre</th><th>IP</th><th>playerId</th><th>Conexión</th><th>Asignación</th></tr>')
 for p in detected:
  print('<tr><td>'+E(p['name'])+'</td><td>'+E(p['host'])+'</td><td>'+E(p['player_id'])+'</td><td>'+('Conectado' if p['connected'] else 'Desconectado')+'</td><td>'+E(', '.join('#'+i for i in p['owners']) or 'Libre')+'</td></tr>')
 if not detected: print('<tr><td colspan="5">Sonn no informa de reproductores. En piCorePlayer, configura Squeezelite para conectarse al servidor Sonn; después actualiza.</td></tr>')
 print('</table>')
print('<details><summary>Acceso a Sonn</summary><p>Usa una cuenta administradora de Sonn. AudioDek consulta el servidor local en el puerto 7090 y conserva únicamente su sesión en un archivo privado. No guarda la contraseña. Los datos locales del Miniserver no establecen esta conexión.</p><form method="post" action="index.cgi" data-ajax="false"><input type="hidden" name="_ui_language" value="es"><input type="hidden" name="action" value="sonn_connect"><label>Usuario de Sonn<input class="at-input" name="sonn_user" autocomplete="username" maxlength="256"></label><label>Contraseña de Sonn<input class="at-input" type="password" name="sonn_password" autocomplete="current-password" maxlength="256"></label><button class="at-btn" type="submit">Conectar para consultar reproductores</button></form><form method="post" action="index.cgi" data-ajax="false"><input type="hidden" name="_ui_language" value="es"><input type="hidden" name="action" value="sonn_disconnect"><button class="at-btn" type="submit">Desconectar consulta</button></form></details></div>')

print('<div class="at-box"><h2>Zonas y reproductores detectados dinámicamente</h2><table class="at-table"><tr><th>Zona</th><th>Nombre</th><th>Salida</th><th>Reproductor</th><th>IP</th><th>playerId</th><th>Soloist</th></tr>')
for z in zones:
 st='<span class="at-ok">● Activo</span>' if z['id'] in solo else ('<span>Sin salida asignada</span>' if not z['output_id'] else '<span class="at-wa">○ No visto</span>')
 print('<tr><td>#'+E(z['id'])+'</td><td>'+E(z['name'])+'</td><td>'+E(z['output_id'])+'</td><td>'+E(z['playerName'])+'</td><td>'+E(z['host'])+'</td><td>'+E(z['playerId'])+'</td><td>'+st+'</td></tr>')
if not zones: print('<tr><td colspan="7">No se encontraron zonas en config.json</td></tr>')
print('</table></div>')

print('<div class="at-box"><h2>Reproductores Squeezelite</h2><table class="at-table"><tr><th>Zona</th><th>Nombre</th><th>IP</th><th>playerId</th><th>Estado</th></tr>')
for z in players:
 print('<tr><td>#'+E(z['id'])+' '+E(z['name'])+'</td><td>'+E(z['playerName'])+'</td><td>'+E(z['host'])+'</td><td>'+E(z['playerId'])+'</td><td class="at-ok">✓ Configurado</td></tr>')
if not players: print('<tr><td colspan="5">No detectados</td></tr>')
print('</table></div>')

ms=settings.get('miniservers',[])
while len(ms)<2: ms.append({'name':'Miniserver '+str(len(ms)+1),'host':'','user':''})
print('<div class="at-box"><h2>Referencia local de Miniservers</h2><p>Estos datos son una referencia local. Configura la conexión real al Miniserver en Sonn; guardar aquí no establece esa conexión.</p><form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="es"><input type="hidden" name="action" value="save"><table class="at-table"><tr><th>Nombre</th><th>IP / Host</th><th>Usuario</th></tr>')
for i,m in enumerate(ms[:2],1):
 print('<tr><td><input class="at-input" name="name%d" value="%s"></td><td><input class="at-input" name="host%d" value="%s"></td><td><input class="at-input" name="user%d" value="%s"></td></tr>'%(i,E(m.get('name')),i,E(m.get('host')),i,E(m.get('user'))))
print('</table><button type="submit" class="at-btn">Guardar datos locales</button></form></div>')
print('<div class="at-box" id="audiodek-new-room"><h2>Añadir una habitación</h2><ol><li>Crea la zona de audio en Loxone Config y envía la configuración al Miniserver.</li><li>Cuando Sonn reciba la zona, pulsa Actualizar / Redetectar.</li><li>Selecciona la habitación sin salida y elige un reproductor detectado por Sonn o introduce sus datos manualmente.</li></ol><p>AudioDek conserva los identificadores de Loxone. Si la habitación aún no tiene datos Soloist, crea un backup compatible que registra esa ausencia antes de asignar el reproductor.</p>')
unassigned = [z for z in zones if not z['output_id']]
if unassigned:
 print('<h3>Habitaciones pendientes de asignación</h3><ul>')
 for z in unassigned:
  print('<li><a data-ajax="false" href="index.cgi?focus_zone='+E(z['id'])+'#audiodek-player">#'+E(z['id'])+' — '+E(z['name'])+'</a></li>')
 print('</ul>')
else:
 print('<p>Todas las habitaciones detectadas tienen una salida asignada. Las nuevas aparecerán aquí cuando lleguen de Loxone.</p>')
print('</div>')

print('<div class="at-box" id="audiodek-player"><h2>Gestionar reproductor de una habitación</h2>')
print('<p>Asigna o retira un reproductor Squeezelite conservando la habitación de Loxone. Se creará un backup antes de aplicar. Sonn se reiniciará y la reproducción se interrumpirá durante el cambio.</p>')
print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="es"><input type="hidden" name="action" value="output_preview"><label>Habitación<select name="output_zone" class="at-input" style="width:100%;margin:8px 0"><option value="">Selecciona una habitación...</option>')
for z in zones:
 print('<option value="'+E(z['id'])+'"'+(' selected' if (G('output_zone') or G('focus_zone'))==z['id'] else '')+'>#'+E(z['id'])+' — '+E(z['name'])+' — '+E(z['playerName'] or 'Sin reproductor')+'</option>')
print('</select></label><label>Operación<select name="output_operation" class="at-input" style="width:100%;margin:8px 0"><option value="assign">Asignar / cambiar reproductor</option><option value="detach"'+(' selected' if G('output_operation')=='detach' else '')+'>Retirar reproductor</option></select></label>')
print('<label>Reproductor detectado<select name="detected_player" class="at-input" style="width:100%;margin:8px 0"><option value="">Introducir datos manualmente...</option>')
selected_room = G('output_zone') or G('focus_zone')
for p in detected:
 unavailable = not p['connected'] or not p['valid_ip'] or any(i != selected_room for i in p['owners'])
 suffix = ' — asignado a '+','.join('#'+i for i in p['owners']) if p['owners'] else ' — libre'
 if not p['connected']: suffix += ' — desconectado'
 if not p['valid_ip']: suffix += ' — IP no compatible'
 print('<option value="'+E(p['player_id'])+'"'+(' disabled' if unavailable else '')+(' selected' if G('detected_player') == p['player_id'] and not unavailable else '')+'>'+E(p['name']+' — '+p['host']+suffix)+'</option>')
print('</select></label><p>Selecciona un reproductor libre: AudioDek toma su nombre, IP y playerId desde Sonn. Los campos manuales de abajo solo se usan si eliges introducir datos manualmente. Para retirar basta con seleccionar la habitación y la operación.</p>')
for label, key, placeholder in [('Nombre del reproductor','output_name','Ej. Cocina'),('IP del reproductor','output_ip','192.168.1.xxx'),('MAC / playerId','output_mac','aa:bb:cc:dd:ee:ff')]:
 print('<label>'+E(label)+'<input class="at-input" style="width:100%;margin:8px 0" name="'+key+'" value="'+E(G(key))+'" placeholder="'+E(placeholder)+'"></label>')
print('<button type="submit" class="at-btn">Revisar cambio de reproductor</button></form>')
if output_preview:
 t = output_preview['target']; d = output_preview['data']; o = t.get('output') or {}
 print('<h3>Revisar antes de aplicar</h3><table class="at-table">')
 for label, value in [('Habitación','#'+str(t['id'])+' '+str(t.get('name',''))),('Acción','Retirar reproductor' if d['operation']=='detach' else 'Asignar / cambiar reproductor'),('Nuevo reproductor',o.get('playerName','Sin reproductor')),('IP',o.get('host','—')),('MAC',o.get('playerId','—'))]:
  print('<tr><td>'+E(label)+'</td><td>'+E(value)+'</td></tr>')
 word = 'RETIRAR' if d['operation']=='detach' else 'ASIGNAR'
 print('</table><p>La habitación y sus identificadores de Loxone se conservarán. La revisión caduca en 15 minutos; si la configuración cambia habrá que revisarla otra vez.</p>')
 print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="es"><input type="hidden" name="action" value="output_confirm"><input type="hidden" name="output_ticket" value="'+E(output_preview['token'])+'"><label>Escribe '+word+'<input name="output_confirm_word" class="at-input" style="width:100%;margin:8px 0" autocomplete="off"></label><button type="submit" class="at-btn">Confirmar cambio real</button></form>')
print('<h3>Nombre y creación de habitaciones</h3><p>Con Loxone integrado, crea o renombra la habitación en Loxone Config y sincroniza con Sonn. Después pulsa Actualizar y asigna aquí su reproductor.</p>')
print('<p>Para recuperar una configuración anterior, usa <a href="#audiodek-restore">Restaurar backup</a>. Comprueba los cambios posteriores al backup: la restauración recupera la configuración completa y los datos Soloist de la habitación elegida.</p></div>')

print('<div class="at-box"><h2>Backup transaccional</h2><p>Guarda <code>config.json</code> y solo <code>zone-X/data</code>; no copia las cachés de Soloist.</p><form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="es"><input type="hidden" name="action" value="zone_backup"><select name="backup_zone" class="at-input" style="width:100%;margin-bottom:8px"><option value="">Selecciona una habitación...</option>')
for z in zones:
 print('<option value="'+E(z['id'])+'">#'+E(z['id'])+' — '+E(z['name'])+' — '+E(z['playerName'])+'</option>')
print('</select><button type="submit" class="at-btn">Crear backup seguro de la habitación</button></form></div>')
backs=list_backups()
print('<div class="at-box"><h2>Historial de backups</h2>')
if not backs:
 print('<p>Todavía no hay backups transaccionales.</p>')
else:
 print('<table class="at-table"><tr><th>Fecha</th><th>Zona</th><th>Habitación</th><th>Operación</th><th>Estado</th></tr>')
 for b in backs[:20]:
  print('<tr><td>'+E(b.get('created'))+'</td><td>#'+E(b.get('zoneId'))+'</td><td>'+E(b.get('room'))+'</td><td>'+E(b.get('operation'))+'</td><td class="at-ok">✓ '+E(b.get('status','backup'))+'</td></tr>')
 print('</table>')
print('</div>')
print('<div class="at-box" id="audiodek-restore"><h2>Restaurar backup</h2><p>Fase de seguridad: verifica íntegramente el backup antes de permitir una restauración real.</p>')
if backs:
 print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="es"><input type="hidden" name="action" value="restore_preview"><select name="restore_backup" class="at-input" style="width:100%;margin-bottom:8px">')
 for b in backs:
  print('<option value="'+E(b.get('_name'))+'">'+E(b.get('created'))+' — #'+E(b.get('zoneId'))+' — '+E(b.get('room'))+'</option>')
 print('</select><button type="submit" class="at-btn">Verificar / Previsualizar restauración</button></form>')
else:
 print('<p>No hay backups disponibles.</p>')
if restore_preview:
 if restore_preview['errors']:
  print('<div class="at-wa"><h3>Backup no válido</h3><ul>')
  for e in restore_preview['errors']: print('<li>'+E(e)+'</li>')
  print('</ul></div>')
 else:
  m,d=restore_preview['info']
  cf=os.path.join(d,'config.json'); sf=os.path.join(d,'soloist-data.tar.gz')
  print('<div class="at-ok"><h3>✓ Backup verificado correctamente</h3></div><table class="at-table">')
  for a,b in [('Backup',restore_preview['name']),('Zona','#'+str(m.get('zoneId',''))+' '+str(m.get('room',''))),
              ('Reproductor',m.get('playerName','')),('IP',m.get('ip','')),('playerId',m.get('playerId','')),
              ('config.json',str(os.path.getsize(cf))+' bytes'),('Soloist data',str(os.path.getsize(sf))+' bytes'),
              ('Restauración real','Disponible tras confirmación; reinicia Sonn')]:
   print('<tr><td>'+E(a)+'</td><td>'+E(b)+'</td></tr>')
  print('</table><p><b>No se ha modificado ningún archivo.</b></p>')
  print('<div class="at-wa"><h3>Restauración real</h3><p>AudioDek creará primero un backup de emergencia, detendrá Sonn, restaurará los datos, arrancará Sonn y verificará la zona. Si falla, intentará rollback automático. La v1.0.7 añade una protección final independiente que comprueba y recupera sonn-core antes de terminar.</p></div>')
  print('<form action="index.cgi" data-ajax="false" method="post"><input type="hidden" name="_ui_language" value="es"><input type="hidden" name="action" value="restore_confirm"><input type="hidden" name="restore_backup" value="'+E(restore_preview['name'])+'"><input class="at-input" style="width:100%;margin-bottom:8px" name="confirm_text" placeholder="Escribe RESTAURAR"><button type="submit" class="at-btn">Confirmar restauración real</button></form>')
print('</div></div>')
