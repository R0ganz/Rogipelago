import asyncio
import websockets
import json
from flask import Flask, jsonify, send_from_directory
import threading
from flask_cors import CORS

# Variables to configure
ARCHIPELAGO_URI = "ws://localhost:38281"
SLOT_NAME = "Roganz"
GAME_NAME = "Terraria"
PASSWORD = None

# Data Storage
overlay_data = {
    "players": {},
    "recent_items": [],
    "recent_events": [],
    "max_events": 20
}

slot_to_name = {}
slot_to_game = {}

app = Flask(__name__)
CORS(app)

# Website setup for JSON data
@app.route("/")
def index():
    return send_from_directory(".", "Rogipelago_Website.html")

@app.route("/data")
def data():
    return jsonify(overlay_data)

# Archipelago Websocket Integration
def add_event(text):
    overlay_data["recent_events"].append(text)

    if len(overlay_data["recent_events"]) > overlay_data["max_events"]:
        overlay_data["recent_events"].pop(0)

async def listen():
    async with websockets.connect(ARCHIPELAGO_URI) as ws:
        print("Connected to Archipelago server")

        await ws.recv()  # RoomInfo

        # Connect
        await ws.send(json.dumps([{
            "cmd": "Connect",
            "name": SLOT_NAME,
            "password": PASSWORD,
            "game": GAME_NAME,
            "uuid": SLOT_NAME,
            "items_handling": 0,
            "version": {
                "major": 0,
                "minor": 6,
                "build": 6,
                "class": "Version"
            },
            "tags": ["Tracker", "DeathLink"]
        }]))
# Connection response parser
        while True:
            raw = await ws.recv()
            print(raw)
            messages = json.loads(raw)

            for msg in messages:
                cmd = msg.get("cmd")

                if cmd == "Bounced" and "DeathLink" in msg.get("tags", []):
                    data = msg.get("data", {})
                    player = data.get("source", "Unknown")
                    cause = data.get("cause", "Died mysteriously.")

                    event_text = f"💀 {player} died: {cause}"
                    add_event(event_text)

                    print("DeathLink detected:", event_text)    

                if cmd == "Connected":
                    print("Connected as slot")

                    slot_info = msg.get("slot_info", {})

                    for player in msg["players"]:
                        slot = player["slot"]
                        name = player["name"]

                        game = slot_info.get(str(slot), {}).get("game", "Unknown")

                        slot_to_name[slot] = name
                        slot_to_game[slot] = game

                        overlay_data["players"][name] = {
                            "game": game,
                            "checks_done": 0,
                            "total_checks": 0,
                            "percent": 0
                        }

                    await ws.send(json.dumps([{
                        "cmd": "Say",
                        "text": "!status"
                    }]))
# Status response parser
                elif cmd == "PrintJSON":
                    msg_type = msg.get("type")

                    for entry in msg.get("data", []):
                        text = entry.get("text", "")
                        lines = text.split("\n")

                        for line in lines:
                            if " has " in line and "(" in line and "/" in line:
                                try:
                                    name = line.split(" has ")[0].strip()
                                    numbers = line.split("(")[1].split(")")[0]
                                    done, total = numbers.split("/")

                                    done = int(done)
                                    total = int(total)

                                    if name not in overlay_data["players"]:
                                        overlay_data["players"][name] = {
                                            "game": "Unknown",
                                            "checks_done": 0,
                                            "total_checks": 0,
                                            "percent": 0
                                        }

                                    overlay_data["players"][name]["checks_done"] = done
                                    overlay_data["players"][name]["total_checks"] = total
                                    overlay_data["players"][name]["percent"] = round((done / total) * 100, 1)

                                except Exception:
                                    pass

                        if msg_type in ["ItemSend", "ItemReceive"]:
                            add_event(text)

                        elif "found" in text.lower():
                            add_event(text)

                        if msg_type == "DeathLink":
                            add_event(f"💀 DeathLink: {text}")

# Run Flask and Websocket listener
def run_flask():
    app.run(port=5000)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(listen())