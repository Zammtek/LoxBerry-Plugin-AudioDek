# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-12: regression check for LoxBerry installer update eligibility.
from pathlib import Path
import configparser, zipfile
root=Path(__file__).resolve().parent
cfg=configparser.ConfigParser()
cfg.read(root/'plugin.cfg')
assert cfg['PLUGIN']['VERSION']=='1.0.8'
updates=cfg['AUTOUPDATE']
assert updates.getboolean('AUTOMATIC_UPDATES')
# plugininstall.pl disables ALL update support when RELEASECFG is empty.
assert updates['RELEASECFG'].strip().startswith('https://')
assert updates['PRERELEASECFG'].strip().startswith('https://')
stable=configparser.ConfigParser()
stable.read(root/'release.cfg')
assert stable['AUTOUPDATE']['VERSION']=='0.0.0'
archive=root.parent/'AudioDek_LoxBerry4_v1.0.8_EN_ES_x86_64.zip'
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert z.read('plugin.cfg')==(root/'plugin.cfg').read_bytes()
    assert z.read('release.cfg')==(root/'release.cfg').read_bytes()
    assert 'LICENSE' in z.namelist()
    for name in ('install.sh','bin/dashboard.py','webfrontend/htmlauth/index.cgi'):
        assert (z.getinfo(name).external_attr>>16)&0o111
print('PASS: updater metadata, reserved stable feed, ZIP integrity and executable modes')
