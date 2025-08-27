"""Run the project directly from a checkout without installing it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from echohub.__main__ import main

raise SystemExit(main())
