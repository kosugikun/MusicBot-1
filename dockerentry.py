#!/usr/bin/env python3
#このファイルは、実行前に依存関係を更新しようとする新しいdockerエントリポイントを提供します

import os
import subprocess
import sys

update = False
for arg in sys.argv[1:]:
    if arg == "-update":
        update = True

if update:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-U', '-r', 'requirements.txt'])

subprocess.run([sys.executable, 'run.py'])
