import os
import sys

# Ensure backend directory is in sys.path so app imports resolve universally across runners and IDEs
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
