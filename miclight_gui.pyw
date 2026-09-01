"""QuadcastLight entry point.

Kept at this path and name because things outside the repo point at it: the
Startup-folder launcher, miclight-gui.cmd, and the Arkanoid supervisor's
process spec. The application itself lives in quadcastlight/ui.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quadcastlight.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
