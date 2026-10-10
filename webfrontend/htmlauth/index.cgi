#!/usr/bin/perl
# SPDX-License-Identifier: SimPL-2.0
# Copyright (c) 2026 David Zapata
# Changed 2026-10-10: license notices and update metadata; existing behavior retained.
use strict;
use warnings;
use LoxBerry::System;
use LoxBerry::Web;
use IPC::Open2;

my $helper = "/opt/loxberry/bin/plugins/audiodek/dashboard.py";
my $body = "";

if (($ENV{'REQUEST_METHOD'} || '') eq 'POST') {
    my $len = int($ENV{'CONTENT_LENGTH'} || 0);
    read(STDIN, $body, $len) if $len > 0;
}

LoxBerry::Web::lbheader("AudioDek", "v1.0.7", "", "");

my ($child_out, $child_in);
my $pid = open2($child_out, $child_in, $helper);
if (($ENV{'REQUEST_METHOD'} || '') eq 'POST' && length($body)) {
    print $child_in $body;
}
close($child_in);

while (my $line = <$child_out>) {
    print $line;
}
close($child_out);
waitpid($pid, 0);

if ($? != 0) {
    print "<div style=\"padding:20px\"><h2>AudioDek</h2><p>Error running the internal dashboard / Error ejecutando el panel interno.</p></div>";
}

LoxBerry::Web::lbfooter();
