"""
Fincept Quant Studio - local app over the quant_evidence engine and the
FinceptTerminal source code.

Usage:
    python quant_studio.py [--port 8765] [--host 127.0.0.1] [--no-browser] [--no-scan]

Opens http://127.0.0.1:8765/ with the decision evaluator running on the Python
engine, a code explorer for the whole repository and a console for the
Analytics CLIs. Stdlib only.
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from quant_evidence.app.server import main  # noqa: E402

if __name__ == '__main__':
    main()
