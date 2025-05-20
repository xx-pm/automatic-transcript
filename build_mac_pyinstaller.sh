#!/usr/bin/env bash
python -m pip install --upgrade pyinstaller
pyinstaller \
  --onefile \
  --windowed \
  --name "Storyboard" \
  --add-data "core:core" \
  main.py