#!/usr/bin/env python3
"""Parallel degree-band BFS sampled SymSplit MCS entrypoint."""

from __future__ import annotations

import os
import sys

from run_symsplit_biased_sampled_mcs import main


if "--jobs" not in sys.argv:
    sys.argv[1:1] = ["--jobs", os.environ.get("JOBS", "2")]
if "--sampling-strategy" not in sys.argv:
    sys.argv[1:1] = ["--sampling-strategy", "degree_band_bfs"]

raise SystemExit(main())

