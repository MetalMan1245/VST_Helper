#!/usr/bin/env python3
"""Entry point for `python -m vst_helper`."""

import sys
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
