import asyncio
import websockets
import json
from flask import Flask, jsonify, send_from_directory
import threading
import time
from flask_cors import CORS

# =============================
# CONFIG
# =============================

ARCHIPELAGO_URI = "ws://localhost:38281"
SLOT_NAME = "Roganz"
GAME_NAME = "Terraria"
PASSWORD = None

# =============================
# DATA STORAGE
# =============================

overlay_data = {
    "players": {},
    "recent_items": []
}

slot_to_name = {}
slot_to_game = {}

app = Flask(__name__)
CORS(app)

# =============================
# Website setup for JSON data
# =============================

@app.route("/")
def index():
    return send_from_directory(".", "overlay.html")

@app.route("/data")
def data():
    return jsonify(overlay_data)

# =============================
# Archipelago Websocket Integration
# =============================

async def listen():
    last_status_time = 0

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
            "tags": ["Tracker"]
        }]))

        while True:
            raw = await ws.recv()
            messages = json.loads(raw)

            for msg in messages:
                cmd = msg.get("cmd")

                # =============================
                # CONNECTED
                # =============================
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

                    # Immediately request status
                    await ws.send(json.dumps([{
                        "cmd": "Say",
                        "text": "!status"
                    }]))

                    last_status_time = time.time()

                # =============================
                # STATUS PARSER
                # =============================
                elif cmd == "PrintJSON":
                    for entry in msg.get("data", []):
                        text = entry.get("text", "")

                        # Split into lines (important!)
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

            # Refresh status every 30 seconds
            if time.time() - last_status_time > 30:
                await ws.send(json.dumps([{
                    "cmd": "Say",
                    "text": "!status"
                }]))
                last_status_time = time.time()

# =============================
# RUN SERVER + CLIENT
# =============================

def run_flask():
    app.run(port=5000)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(listen())