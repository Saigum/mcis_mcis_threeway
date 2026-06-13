#!/usr/bin/env python3
"""Low-degree BFS sampled SymSplit MCS entrypoint."""

from __future__ import annotations

import sys

from run_symsplit_biased_sampled_mcs import main


if "--sampling-strategy" not in sys.argv:
    sys.argv[1:1] = ["--sampling-strategy", "low_degree_bfs"]

raise SystemExit(main())

