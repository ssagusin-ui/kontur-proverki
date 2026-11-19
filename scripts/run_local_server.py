"""Start Streamlit and identify the real server process, including under a Windows venv."""
from pathlib import Path
import os
import sys

from streamlit.web.cli import main


port, launch_id = sys.argv[1:]
Path(f"storage/launcher-{launch_id}.pid").write_text(str(os.getpid()), encoding="ascii")
sys.argv[1:] = [
    "run", "app.py", "--server.address", "127.0.0.1",
    "--server.port", port, "--server.headless", "true",
]
main()
