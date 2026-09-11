"""One setup command from a clean clone: python setup.py"""
import os
import subprocess
import sys
import venv
from pathlib import Path

root=Path(__file__).resolve().parent
if sys.version_info<(3,10):
    raise SystemExit('Install Python 3.10 or newer.')
venv.create(root/'.venv',with_pip=True)
python=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
subprocess.run([str(python),'-m','pip','install','-r',str(root/'requirements.txt')],check=True)
subprocess.run([str(python),'-m','src.run','--check'],cwd=root,check=True)
print('Setup complete. Next: read START_HERE.md.')
