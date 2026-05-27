#!/usr/bin/env python3
import os
import subprocess
from datetime import datetime, time, timezone

# Configuration
CRISP_AGENT_ID = "crisp"
CRISP_MODEL = "anthropic/claude-3-5-sonnet-20241022"
LOG_FILE = "/root/.openclaw/workspace/agents/crisp/.openclaw/crisp_trading_cycle.log"
WORKSPACE = "/root/.openclaw/workspace"

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def log_message(message):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    log_entry = f"[{timestamp}] [start_script] {message}"
    print(log_entry)
    with open(LOG_FILE, "a") as f:
        f.write(log_entry + "\n")

def is_ny_session_active(current_utc_dt):
    # New York session: 9:30 AM EST to 5:00 PM EST
    # EST is UTC-5
    # 9:30 AM EST = 14:30 UTC
    # 5:00 PM EST = 22:00 UTC
    
    ny_start_time_utc = time(14, 30)
    ny_end_time_utc = time(22, 0) # End of session for trading
    
    current_utc_time = current_utc_dt.time()
    
    return ny_start_time_utc <= current_utc_time < ny_end_time_utc

def main():
    log_message("Crisp trading cycle script started.")
    current_utc_dt = datetime.now(timezone.utc)

    if not is_ny_session_active(current_utc_dt):
        log_message("Outside New York trading session. Skipping Crisp spawn.")
        return

    log_message("Inside New York trading session. Attempting to spawn Crisp for a trading cycle.")

    # Task for Crisp to perform
    crisp_task = "Execute one trading cycle (market scan, setup, and trade if conditions met) according to STRATEGY.md."

    try:
        # Construct the OpenClaw sessions_spawn command
        command = [
            "openclaw", "sessions", "spawn",
            "--agentId", CRISP_AGENT_ID,
            "--task", crisp_task,
            "--mode", "run",
            "--model", CRISP_MODEL,
            "--runTimeoutSeconds", "120", # Give Crisp 2 minutes to complete its cycle
            "--thread", # Spawn in a thread to keep main session clear
            "--label", f"crisp-trading-cycle-{current_utc_dt.strftime('%H%M%S')}"
        ]
        
        # Using subprocess.run to execute the openclaw command
        log_message(f"Executing: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, cwd=WORKSPACE, check=True)
        log_message(f"Crisp spawned successfully: {result.stdout.strip()}")

    except subprocess.CalledProcessError as e:
        log_message(f"Error spawning Crisp: {e.stderr.strip()}")
    except Exception as e:
        log_message(f"An unexpected error occurred: {e}")

    log_message("Crisp trading cycle script finished.")

if __name__ == "__main__":
    main()
