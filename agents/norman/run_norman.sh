#!/bin/bash
source /root/.bashrc
cd /root/.openclaw/agents/norman
python3 norman_brain.py --weekly >> /root/.openclaw/logs/norman.log 2>&1
