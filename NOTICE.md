# AudioDek notices and provenance

Copyright (c) 2026 David Zapata.
SPDX-License-Identifier: SimPL-2.0

2026-10-10: AudioDek 1.0.7 adopts SimPL-2.0 for its own source code, build and
installation scripts and original documentation. This release also replaces
the invalid literal RELEASECFG=false with an empty stable-channel endpoint.
Player assignment, discovery, restoration and language behavior are retained.

The AudioDek implementation derives from this project's earlier AudioTek work.
No vendored Sonn, LoxBerry, Audioserver4Home, Squeezelite or piCorePlayer source
is included in the plugin installer. Those programs are external dependencies
and retain their respective copyright and license terms. API and filesystem
integration does not grant ownership of those projects.

The guide includes anonymized and edited Loxone Config illustrations based on
screenshots supplied by the project owner. Loxone interface elements and names
remain third-party material and are not relicensed under AudioDek's license.
AudioDek's logo and edited illustrations were prepared with AI assistance;
no exclusive copyright or third-party trademark rights are asserted for them.
All referenced product names and trademarks belong to their respective owners.

License text source: https://spdx.org/licenses/SimPL-2.0.html
LoxWiki publication rules:
https://loxwiki.atlassian.net/wiki/spaces/LOX/pages/1516077056

The license grant covers only rights the project owner can grant. It does not
constitute clearance or relicensing of third-party screenshots or trademarks.

2026-10-12: AudioDek 1.0.8 corrects the empty RELEASECFG introduced in 1.0.7.
A valid reserved stable feed keeps pre-release update support enabled.
