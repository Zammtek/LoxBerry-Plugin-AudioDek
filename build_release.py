# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-10: standalone packaging of this editable source tree.
from pathlib import Path
import configparser, hashlib, zipfile
base=Path(__file__).resolve().parent
cfg=configparser.ConfigParser();cfg.read(base/'plugin.cfg')
version=cfg['PLUGIN']['VERSION']
target=base.parent/('AudioDek_LoxBerry4_v'+version+'_EN_ES_x86_64.zip')
excluded={'SHA256SUMS','build_release.py'}
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for path in sorted(base.rglob('*')):
        if not path.is_file():continue
        name=path.relative_to(base).as_posix()
        if name in excluded or '.git' in path.parts or '__pycache__' in path.parts or '.github' in path.parts:continue
        if name.endswith('.zip') or name in ('settings.json','language.json','.language-key','.room-output-key','.sonn-inventory-session'):continue
        info=zipfile.ZipInfo(name);info.create_system=3
        mode=0o100755 if name in ('bin/dashboard.py','install.sh','webfrontend/htmlauth/index.cgi') else 0o100644
        info.external_attr=mode<<16;info.compress_type=zipfile.ZIP_DEFLATED
        z.writestr(info,path.read_bytes())
digest=hashlib.sha256(target.read_bytes()).hexdigest()
(base/'SHA256SUMS').write_text(digest+'  '+target.name+'\n',encoding='utf-8')
print(target)
