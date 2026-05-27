import json
import os
from datetime import datetime, timezone

HUB_PATH = "/root/.openclaw/dashboard/agent_hub.json"

def load_hub_data():
    if not os.path.exists(HUB_PATH):
        return {"messages": [], "max_messages": 500}
    with open(HUB_PATH, "r") as f:
        return json.load(f)

def save_hub_data(data):
    with open(HUB_PATH, "w") as f:
        json.dump(data, f, indent=2)

def add_hub_message(agent, msg_type, message, tags=None):
    data = load_hub_data()
    new_msg = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "type": msg_type,
        "message": message,
        "tags": tags or []
    }
    data["messages"].append(new_msg)
    
    # Enforce max_messages limit
    if len(data["messages"]) > data["max_messages"]:
        data["messages"] = data["messages"][-data["max_messages"]:]
    
    save_hub_data(data)
    return new_msg

if __name__ == "__main__":
    # Example usage for testing
    test_msg = add_hub_message("test_agent", "info", "This is a test message.", ["test"])
    print(f"Added test message: {json.dumps(test_msg, indent=2)}")
    hub_data = load_hub_data()
    print(f"Current hub messages count: {len(hub_data["messages"])}")
