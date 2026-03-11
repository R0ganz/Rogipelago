import asyncio
import websockets
import json
from flask import Flask, jsonify, send_from_directory
import threading
from flask_cors import CORS
import sys

# Variables to configure
ARCHIPELAGO_URI = sys.argv[1] if len(sys.argv) > 1 else input("Enter the Archipelago server connection details (e.g. archipelago.gg:38281):")
SLOT_NAME = sys.argv[2] if len(sys.argv) > 2 else input("Enter a valid slot name:")
GAME_NAME = sys.argv[3] if len(sys.argv) > 3 else input("Enter the game that slot is playing: ")
PASSWORD = sys.argv[4] if len(sys.argv) > 4 else input ("Enter password for this slot, else leave blank: ") or None

if ARCHIPELAGO_URI.startswith("archipelago"):
    ARCHIPELAGO_URI = "wss://" + ARCHIPELAGO_URI
else:
    ARCHIPELAGO_URI = "ws://" + ARCHIPELAGO_URI

# Data Storage
overlay_data = {
    "players": {},
    "recent_items": [],
    "recent_events": [],
    "max_events": 20
}

slot_to_name = {}
slot_to_game = {}
item_id_to_name = {}
location_id_to_name = {}
seen_items = set()
websocket_connection = None
event_loop = None

app = Flask(__name__)
CORS(app)

# Website setup for JSON data
@app.route("/")
def index():
    return send_from_directory(".", "Rogipelago_Website.html")

@app.route("/data")
def data():
    return jsonify(overlay_data)

@app.route("/refresh")
def manual_refresh():
    if websocket_connection and event_loop:
        asyncio.run_coroutine_threadsafe(
            send_status_request(),
            event_loop
        )
    return {"status": "requested"}

# Archipelago Websocket Integration
def add_event(text):
    overlay_data["recent_events"].append(text)

    if len(overlay_data["recent_events"]) > overlay_data["max_events"]:
        overlay_data["recent_events"].pop(0)

async def periodic_status(ws):
    while True:
        await asyncio.sleep(300)  # 5 minutes
        print("Auto requesting status...")
        await ws.send(json.dumps([{
            "cmd": "Say",
            "text": "!status"
        }]))

async def send_status_request():
    if websocket_connection:
        await websocket_connection.send(json.dumps([{
            "cmd": "Say",
            "text": "!status"
        }]))

async def listen():
    global websocket_connection

    async with websockets.connect(ARCHIPELAGO_URI) as ws:
        print("Connected to Archipelago server")
        websocket_connection = ws
        asyncio.create_task(periodic_status(ws))
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
            # Remove the # below for debugging
            # print(raw)
            messages = json.loads(raw)

            for msg in messages:
                cmd = msg.get("cmd")

                if cmd == "Bounced" and "DeathLink" in msg.get("tagss", []):
                    data = msg.get("data", {})
                    player = data.get("source", "Unknown")
                    cause = data.get("cause", "Died mysteriously.")

                    event_text = f"💀 {player} died: {cause}"
                    add_event(event_text)

                    print("DeathLink detected:", event_text)    
                if cmd == "InvalidSlot":
                    print("Invalid slot name. Please retry your input.")
                    return
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
                    }]))# Status response parser
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

# This code reports items, but the numbers and locations are just numbers, not very helpful. Leaving here, but commenting out for now
#                        if msg.get("type") in ["ItemSend", "ItemReceive"]:
#                            item_info = msg.get("item", {})
#
#                            sending_slot = item_info.get("player")
#                            receiving_slot = msg.get("receiving")
#
#                            item_id = item_info.get("item")
#                            location_id = item_info.get("location")
#
#                            # Unique key per item transfer
#                            unique_key = (sending_slot, receiving_slot, item_id, location_id)
#
#                            if unique_key in seen_items:
#                                continue  # skip duplicate
#
#                            seen_items.add(unique_key)
#
#                            sender_name = slot_to_name.get(sending_slot, f"Slot {sending_slot}")
#                            receiver_name = slot_to_name.get(receiving_slot, f"Slot {receiving_slot}")
#
#                            item_name = item_id_to_name.get(item_id, f"Item {item_id}")
#                            location_name = location_id_to_name.get(location_id, f"Location {location_id}")
#
#                            event_text = f"{sender_name} sent {item_name} to {receiver_name} ({location_name})"
#
#                            add_event(event_text)
#
#                            print("Item event:", event_text)
# Below adds a status check EVERY time a check is completed. Found this spammy with multiple players but ensures status is always up to date.
#                            await ws.send(json.dumps([{"cmd": "Say","text": "!status"}]))
#                       elif "found" in text.lower():
#                           add_event(text)
                        if msg_type == "DeathLink":
                            add_event(f"💀 DeathLink: {text}")

# Run Flask and Websocket listener
def run_flask():
    app.run(port=5000)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()

    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    event_loop.run_until_complete(listen())