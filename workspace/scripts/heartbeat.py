#!/usr/bin/env python3
"""
Huncho Heartbeat Scheduler
Runs every 8 hours, uses Gemini Flash
"""

import subprocess
import json
import os
from datetime import datetime

WORKSPACE = "/root/.openclaw/workspace"
LOG_FILE = os.path.join(WORKSPACE, ".openclaw", "heartbeat.log")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def log(msg):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

try:
    log("Heartbeat check initiated")
    
    # Spawn a heartbeat sub-agent using sessions_spawn equivalent
    # This writes a marker that the main session can detect and act on
    marker_file = os.path.join(WORKSPACE, ".openclaw", "heartbeat-trigger.txt")
    with open(marker_file, "w") as f:
        f.write(datetime.utcnow().isoformat())
    
    log("Heartbeat marker written - main session will process on next interaction")
    
except Exception as e:
    log(f"ERROR: {str(e)}")
    exit(1)
