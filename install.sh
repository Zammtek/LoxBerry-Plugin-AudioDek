#!/bin/bash
# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-10: license notices and update metadata; existing behavior retained.
mkdir -p /opt/loxberry/config/plugins/audiodek /opt/loxberry/data/plugins/audiodek/backups
chmod 755 /opt/loxberry/webfrontend/htmlauth/plugins/audiodek/index.cgi 2>/dev/null || true
chmod 755 /opt/loxberry/bin/plugins/audiodek/dashboard.py 2>/dev/null || true
exit 0
