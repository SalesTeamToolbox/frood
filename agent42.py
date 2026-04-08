"""agent42.py -- deprecated entry point. Use frood.py instead."""

import sys

from frood import Frood, main

# Backward-compat alias for tests that import Agent42
Agent42 = Frood

if __name__ == "__main__":
    print("[frood] agent42.py is deprecated -- use frood.py", file=sys.stderr)
    main()
