<p align="center"><img src="AudioDek_logo.png" alt="AudioDek logo" width="200"></p>

# AudioDek — LoxBerry multiroom setup

**Experimental / testers wanted. Current test release: v1.0.8, English / Spanish edition.**

AudioDek helps assign Squeezelite players to rooms supplied by Sonn and Loxone,
with guided diagnostics, pre-change backups and an illustrated setup guide.
Playback is handled by Sonn; everyday controls remain in the Loxone app.

## Documentation and community

- [AudioDek documentation on the LoxBerry Wiki](https://wiki.loxberry.de/plugins/audiodek/start)
- [AudioDek discussion, feedback and support on LoxForum](https://www.loxforum.com/forum/projektforen/loxberry/plugins/493296)

## Requirements

- LoxBerry 4.0, x86_64 and Python 3.
- Audioserver4Home running Sonn `4.0.0-beta.19`.
- Loxone integration configured in Sonn and Audio Player blocks deployed to the Miniserver.
- Squeezelite clients, for example Raspberry Pi devices running piCorePlayer.

Other Sonn versions and ARM installations are not validated. No automatic
installation of Sonn or piCorePlayer. Configuration changes restart Sonn.

## Install and test updates

Download the installable ZIP attached to the GitHub release. Do not use the
GitHub source-code archive as the validated installer. Upload the ZIP through
LoxBerry Plugin Management. Update an existing AudioDek installation without
uninstalling. AudioTek is a separate personal plugin and is not updated here.

This release enables LoxBerry's update support for the **pre-release channel**.
The stable feed is reserved at version 0.0.0, so it offers no stable update. To receive later test releases, enable
automatic updates and pre-release updates for AudioDek in LoxBerry's plugin
management. Installing v1.0.5 manually bootstraps this feature; older packages
do not contain the repository URL. No newer update is available until published.

**Recovery from v1.0.7:** install the v1.0.8 installer ZIP manually once, without uninstalling AudioDek. The 1.0.7 installer disabled update support because RELEASECFG was empty. After upgrading, select Pre- and Releases in LoxBerry. Existing room settings, backups and language preference are retained.

**Recuperación desde v1.0.7:** instala manualmente el ZIP de v1.0.8 una vez, sin desinstalar AudioDek; después selecciona Pre- y Releases. La configuración de habitaciones, los backups y el idioma se conservan.

## Language / Idioma

Choose **English** or **Español** at the top of AudioDek and save your preference.
On first use, AudioDek reads LoxBerry's language (English/Spanish); other languages
fall back to English. The preference belongs to this AudioDek installation.
The interface, diagnostics, messages and illustrated guide follow the selection.
Existing room/player names, settings and backups are not translated or modified.
Open forms keep their original language. Confirm with ASSIGN/REMOVE/RESTORE in
English or ASIGNAR/RETIRAR/RESTAURAR in Spanish.

Selecciona **Español** en **Language / Idioma** y pulsa **Guardar idioma**.
La preferencia se conserva al actualizar; las habitaciones y backups no cambian.
El manual está disponible en ambos idiomas.

## Backup scope and validation status

Each backup contains the complete configuration and Soloist data for only the
selected room. It is not a full backup of all rooms' data. Restoration can
revert later configuration changes in other rooms. Keep a Loxone project copy.

Room/configuration display has been tested in the existing installation. New
features have local simulated-service tests. Authenticated player discovery,
fresh installation and fresh-system testing remain pending. The user confirmed the 1.0.5 to 1.0.6 LoxBerry update and Spanish interface.

## Reporting issues

Include LoxBerry and Sonn versions, hardware, steps, expected/actual results and
the displayed error. Remove passwords, tokens and private identifiers from logs
and screenshots. Test configuration changes in a suitable test environment.

## Project foundations

- [LoxBerry](https://wiki.loxberry.de/)
- [Audioserver4Home](https://github.com/mschlenstedt/LoxBerry-Plugin-Audioserver4Home)
- [Sonn](https://github.com/sonn-audio/core)
- [piCorePlayer](https://docs.picoreplayer.org/)

## License / Licencia

Copyright (c) 2026 David Zapata. AudioDek's own source code, build scripts,
installation scripts and original guide text are licensed under **Simple Public
License 2.0 (SimPL-2.0)**. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
The source archive includes the editable files and a standalone packaging script.
When redistributing modifications, retain notices, identify your changes and
provide the corresponding source under SimPL or substantially similar terms.

El código propio y el texto original del manual de AudioDek se publican bajo
**SimPL-2.0**. Consulta LICENSE y NOTICE.md. Se permite usar, modificar y
redistribuir respetando las condiciones de la licencia.

External software, trademarks and third-party screenshot elements retain their
own rights. They are not relicensed by AudioDek. This repository contains no
credentials or live room data.
