#!/usr/bin/env python3
import os
import subprocess
from datetime import datetime, timezone

# Configuration
CRISP_AGENT_ID = "crisp"
CRISP_MODEL = "anthropic/claude-3-5-sonnet-20241022"
LOG_FILE = "/root/.openclaw/workspace/agents/crisp/.openclaw/crisp_stop_summary.log"
WORKSPACE = "/root/.openclaw/workspace"

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def log_message(message):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    log_entry = f"[{timestamp}] [stop_script] {message}"
    print(log_entry)
    with open(LOG_FILE, "a") as f:
        f.write(log_entry + "\n")

def main():
    log_message("Crisp stop trading and summary script started.")

    try:
        # First, kill any running Crisp sessions to ensure no further trading
        log_message("Attempting to kill any active Crisp sub-agent sessions.")
        kill_command = [
            "openclaw", "subagents", "kill",
            "--target", CRISP_AGENT_ID
        ]
        kill_result = subprocess.run(kill_command, capture_output=True, text=True, cwd=WORKSPACE)
        log_message(f"Subagent kill command output: {kill_result.stdout.strip()} {kill_result.stderr.strip()}")
        
        # Now, spawn Crisp for a final run to generate the summary
        summary_task = "Generate a full performance summary including P&L, trades made, and win rate from all trading activity so far. Format it for Huncho to relay to Jase."
        summary_command = [
            "openclaw", "sessions", "spawn",
            "--agentId", CRISP_AGENT_ID,
            "--task", summary_task,
            "--mode", "run",
            "--model", CRISP_MODEL,
            "--runTimeoutSeconds", "300", # Give Crisp 5 minutes to compile summary
            "--thread",
            "--label", "crisp-summary-report"
        ]
        log_message(f"Executing summary command: {' '.join(summary_command)}")
        summary_result = subprocess.run(summary_command, capture_output=True, text=True, cwd=WORKSPACE, check=True)
        log_message(f"Crisp summary spawn successfully: {summary_result.stdout.strip()}")

    except subprocess.CalledProcessError as e:
        log_message(f"Error during stop/summary process: {e.stderr.strip()}")
    except Exception as e:
        log_message(f"An unexpected error occurred: {e}")

    log_message("Crisp stop trading and summary script finished.")

if __name__ == "__main__":
    main()
