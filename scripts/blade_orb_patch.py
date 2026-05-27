# -*- coding: utf-8 -*-
import json
import os
import re

def apply_patch():
    blade_bot_path = "/root/.openclaw/agents/blade/bot/blade_bot.py"

    # Read the current content of blade_bot.py
    with open(blade_bot_path, 'r') as f:
        content = f.readlines()

    # --- Step 1: Insert get_opening_candle and check_1m_breakout functions ---
    # Find the insertion point: after get_price, before place_paper_order
    insertion_point = -1
    for i, line in enumerate(content):
        if "def get_price(instrument):" in line:
            insertion_point = i + 7 # Insert after get_price block
            break
    
    if insertion_point == -1:
        print("Error: Could not find insertion point for ORB functions.")
        return

    orb_functions = [
        "\n",
        "def get_opening_candle(instrument, granularity='M15'):\n",
        "    print(f" Recording opening {granularity} candle for {instrument}...")\n",
        "    candles = get_candles(instrument, granularity, 2)\n",
        "    if not candles: return None, None\n",
        "    opening_candle = candles[-2]['mid'] # OANDA returns dict for mid/ask/bid\n",
        "    high = float(opening_candle['h'])\n",
        "    low = float(opening_candle['l'])\n",
        "    print(f"   {instrument} {granularity} ORB: High={high}, Low={low}")\n",
        "    return high, low\n",
        "\n",
        "def check_1m_breakout(instrument, orb_high, orb_low):\n",
        "    candles = get_candles(instrument, 'M1', 3)\n",
        "    if not candles: return None\n",
        "    last_closed = candles[-2]['mid'] # OANDA returns dict for mid/ask/bid\n",
        "    close = float(last_closed['c'])\n",
        "    open_price = float(last_closed['o'])\n",
        "    print(f"   {instrument} 1m Check: Open={open_price}, Close={close}")\n",
        "    if close > orb_high and open_price > orb_high: return 'long'\n",
        "    elif close < orb_low and open_price < orb_low: return 'short'\n",
        "    return None\n",
        "\n"
    ]
    content.insert(insertion_point, "".join(orb_functions))

    # --- Step 2: Modify run_orb_session to integrate ORB logic ---
    # Find run_orb_session start
    run_orb_session_start = -1
    for i, line in enumerate(content):
        if "def run_orb_session(session_name):" in line:
            run_orb_session_start = i
            break
    
    if run_orb_session_start == -1:
        print("Error: Could not find run_orb_session function.")
        return

    # Extract existing run_orb_session content
    run_orb_session_end = -1
    for i in range(run_orb_session_start + 1, len(content)):
        if content[i].strip() and not (content[i].startswith(" ") or content[i].startswith("\t")):
            run_orb_session_end = i
            break
    if run_orb_session_end == -1:
        run_orb_session_end = len(content)

    original_run_orb_session_lines = content[run_orb_session_start+1:run_orb_session_end]

    # New run_orb_session content
    new_run_orb_session_logic = [
        "    logging.info(f"Starting Blade {session_name} session...")\n",
        "    print(f"Starting Blade {session_name} session...")\n",
        "\n",
        "    # Step 1: Wait for session open (placeholder - actual implementation in parent script)\n",
        "    # For OANDA, session open is continuous, but ORB is specific to a candle period.\n",
        "    # We'll assume the parent cron job runs at appropriate times for London/NY opens.\n",
        "    print("Waiting for ORB candle to form...")\n",
        "    time.sleep(10) # Simulate wait for first candle\n",
        "\n",
        "    orb_ranges = {}\n",
        "    for instrument in INSTRUMENTS:\n",
        "        high, low = get_opening_candle(instrument, 'M15')\n",
        "        if high and low:\n",
        "            orb_ranges[instrument] = {'high': high, 'low': low}\n",
        "        else:\n",
        "            print(f" Failed to get ORB for {instrument}, skipping.")\n",
        "\n",
        "    if not orb_ranges:\n",
        "        print(" No valid ORB ranges found, aborting session.")\n",
        "        write_session_trades_to_json() # Write placeholder no_trade records\n",
        "        send_telegram_report(session_name)\n",
        "        return\n",
        "\n",
        "    end_time = time.time() + (4 * 3600) # Monitor for 4 hours\n",
        "    traded = set()\n",
        "    print("\n Monitoring 1m chart for breakouts...")\n",
        "\n",
        "    while time.time() < end_time:\n",
        "        for instrument in INSTRUMENTS:\n",
        "            if instrument in traded or instrument not in orb_ranges: continue\n",
        "            direction = check_1m_breakout(instrument, orb_ranges[instrument]['high'], orb_ranges[instrument]['low'])\n",
        "            if direction:\n",
        "                print(f" BREAKOUT: {instrument} {direction.upper()}")\n",
        "                if place_paper_order(instrument, direction, orb_ranges[instrument]['high'], orb_ranges[instrument]['low'], session_name):\n",
        "                    traded.add(instrument)\n",
        "\n",
        "        if open_positions:\n",
        "            manage_positions()\n",
        "\n",
        "        print(f" Monitoring... Open: {list(open_positions.keys())}")\n",
        "        time.sleep(30)\n",
        "\n",
        "    # End of session market close\n",
        "    print("\n End of session. Closing any open positions.")\n",
        "    for instrument in list(open_positions.keys()):\n",
        "        pos = open_positions[instrument]\n",
        "        price = get_price(instrument)\n",
        "        pnl = (price - pos['entry']) * pos['units'] if pos['direction'] == 'long' else (pos['entry'] - price) * pos['units']\n",
        "        result = f"TP{pos['highest_tp_hit']}" if pos['highest_tp_hit'] > 0 else "BE" if pos['breakeven_moved'] else "Time Stop"\n",
        "        update_trade_log(pos['trade_id'], result, pnl, "Closed at end of session.")\n",
        "        msg = f" TIME STOP: {instrument} | PnL: ${pnl:.2f}"\n",
        "        print(msg); logging.info(msg)\n",
        "\n",
        "    open_positions.clear()\n",
        "    print(f"\n{'='*50}\n{session_name} session complete")\n",
        "    \n",
        "    # Final reporting steps\n",
        "    write_session_trades_to_json()\n",
        "    os.system("python3 /root/.openclaw/scripts/sync_agent_pnl.py") # Update totals\n",
        "    send_telegram_report(session_name)\n",
        "\n",
        "    print(f"Blade {session_name} session finished.\n{'='*50}")\n",
        "\n"
    ]
    
    content[run_orb_session_start+1:run_orb_session_end] = [line + "\n" for line in new_run_orb_session_logic]

    # --- Step 3: Ensure INSTRUMENTS list is defined ---
    # Assuming INSTRUMENTS is defined at a higher level, but double check.
    # If not found, add it around line 28 or similar.
    # For now, we assume it's there based on previous grep.

    # --- Step 4: Ensure global open_positions, session_trades are accessible (usually already global) ---
    # Add global declarations if needed, similar to Crisp fix approach, but test first.
    # We will add them only if there are UnboundLocalErrors.

    # Write the modified content back to blade_bot.py
    with open(blade_bot_path, 'w') as f:
        f.writelines(content)

    print("Blade ORB patch applied successfully.")

if __name__ == "__main__":
    apply_patch()
