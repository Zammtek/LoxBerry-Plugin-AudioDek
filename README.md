<p align="center"><img src="AudioDek_logo.png" alt="AudioDek logo" width="200"></p>

# AudioDek — LoxBerry multiroom setup

**Experimental / testers wanted. Current test release: v1.0.5, English edition.**

AudioDek helps assign Squeezelite players to rooms supplied by Sonn and Loxone,
with guided diagnostics, pre-change backups and an illustrated setup guide.
Playback is handled by Sonn; everyday controls remain in the Loxone app.

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
The stable update channel is disabled. To receive later test releases, enable
automatic updates and pre-release updates for AudioDek in LoxBerry's plugin
management. Installing v1.0.5 manually bootstraps this feature; older packages
do not contain the repository URL. No newer update is available until published.

The installed edition remains English. A selectable-language edition is a
future improvement. User-defined room/player names, settings and backup paths
are unchanged. Confirm changes with ASSIGN, REMOVE and RESTORE.

## Backup scope and validation status

Each backup contains the complete configuration and Soloist data for only the
selected room. It is not a full backup of all rooms' data. Restoration can
revert later configuration changes in other rooms. Keep a Loxone project copy.

Room/configuration display has been tested in the existing installation. New
features have local simulated-service tests. Authenticated player discovery,
fresh installation and the actual LoxBerry auto-update flow are still pending.

## Reporting issues

Include LoxBerry and Sonn versions, hardware, steps, expected/actual results and
the displayed error. Remove passwords, tokens and private identifiers from logs
and screenshots. Test configuration changes in a suitable test environment.

## Project foundations

- [LoxBerry](https://wiki.loxberry.de/)
- [Audioserver4Home](https://github.com/mschlenstedt/LoxBerry-Plugin-Audioserver4Home)
- [Sonn](https://github.com/sonn-audio/core)
- [piCorePlayer](https://docs.picoreplayer.org/)

No project license has been selected yet; publication alone does not grant an
open-source license. This repository contains no credentials or live room data.
