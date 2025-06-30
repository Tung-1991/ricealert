#!/bin/bash
source /home/tungn/ricealert/venv/bin/activate
cd /home/tungn/ricealert

# 1. Train
python trainer.py

# 2. Git update
TODAY=$(date +"%Y-%m-%d")
git pull origin main
git add data/
git commit -m "data update on $TODAY"
git push -u origin main
