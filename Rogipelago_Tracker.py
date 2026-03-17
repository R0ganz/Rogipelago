import asyncio
import websockets
import json
from flask import Flask, jsonify, send_from_directory
import threading
from flask_cors import CORS
import sys
import logging
import webbrowser

# Variables to configure
ARCHIPELAGO_URI = sys.argv[1] if len(sys.argv) > 1 else input("Enter the Archipelago server connection details (e.g. archipelago.gg:38281):")
SLOT_NAME = sys.argv[2] if len(sys.argv) > 2 else input("Enter a valid slot name:")
GAME_NAME = sys.argv[3] if len(sys.argv) > 3 else input("Enter the game that slot is playing: ")
PASSWORD = sys.argv[4] if len(sys.argv) > 4 else input ("Enter password for this slot, else leave blank: ") or None

if ARCHIPELAGO_URI.startswith("archipelago"):
    ARCHIPELAGO_URI = "wss://" + ARCHIPELAGO_URI
else:
    ARCHIPELAGO_URI = "ws://" + ARCHIPELAGO_URI

#Data Storage
overlay_data = {
    "players": {},
    "recent_events": [],
    "max_events": 20
}

# Hides Flask's logging to console, which was cluttering the output. Can be set to INFO instead of ERROR for debugging.
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

slot_to_name = {}
slot_to_game = {}
item_id_to_name = {}
location_id_to_name = {}
game_item_names = {}
game_location_names = {}
multiworld_games = set()
seen_locations = set()
websocket_connection = None
event_loop = None
CUSTOM_PLAYER_COLOURS = {
    "Roganz": "#db1414"
}
ITEM_COLOUR = "#ca8d30"
LOCATION_COLOUR = "#5fbb35"
GAME_COLOUR = "#7a3cc8"


app = Flask(__name__)
CORS(app)


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

def add_event(text):
    overlay_data["recent_events"].append(text)
    if len(overlay_data["recent_events"]) > overlay_data["max_events"]:
        overlay_data["recent_events"].pop(0)
    

async def periodic_status(ws):
    while True:
        await asyncio.sleep(300) # 5 minutes
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
            "version": {"major":0,"minor":6,"build":6,"class":"Version"},
            "tags": ["Tracker","DeathLink"]
        }]))
# Connection response parser
        while True:
            raw = await ws.recv()
            # Remove the # below for debugging
            #print(raw)
            messages = json.loads(raw)

            for msg in messages:
                cmd = msg.get("cmd")
                error = msg.get("errors")
                if "InvalidSlot" in str(error):
                    input("Invalid slot name.")
                    return
                elif "InvalidGame" in str(error):
                    input("Invalid game name.")
                    return
                elif "InvalidPassword" in str(error):
                    input("Invalid password.")
                    return
                # Successful connection
                elif cmd == "Connected":
                    print("Connected as slot")
                    #Colours for the events
                    slot_info = msg.get("slot_info", {})
                    for player in msg["players"]:
                        #Colours for the events
                        slot = player["slot"]
                        name = player["name"]
                        game = slot_info.get(str(slot), {}).get("game","Unknown")
                        slot_to_name[slot] = name
                        slot_to_game[slot] = game
                        multiworld_games.add(game)
                        def get_player_colour(slot, name):
                            if name in CUSTOM_PLAYER_COLOURS:
                                return CUSTOM_PLAYER_COLOURS[name]
                            else:
                                # Generate a colour based on the slot number for consistency
                                hue = (slot * 137) % 360  # Prime number to spread colours
                                return f"hsl({hue}, 70%, 60%)"
                        player_colour = get_player_colour(slot, name)
                        overlay_data["players"][name] = {
                            "game": game,
                            "checks_done": 0,
                            "total_checks": 0,
                            "percent": 0,
                            "connections":0,
                            "connected":False,
                            "colour": player_colour
                        }
                    webbrowser.open("http://localhost:5000")

                    
                    # Request datapackage
                    print("Detected games:", multiworld_games)
                    await ws.send(json.dumps([{
                        "cmd": "GetDataPackage",
                        "games": list(multiworld_games)
                    }]))

                    await ws.send(json.dumps([{
                        "cmd": "Say",
                        "text": "!status"
                    }]))

                # RECEIVE ITEM/LOCATION DATABASE
                elif cmd == "DataPackage":
                    data = msg.get("data", {})
                    games = data.get("games", {})
                    item_id_to_name.clear()
                    location_id_to_name.clear()
                    total_items = 0
                    total_locations = 0
                    for game_name, game_data in games.items():
                        items = game_data.get("item_name_to_id", {})
                        locations = game_data.get("location_name_to_id", {})
                        for name, id in items.items():
                            item_id_to_name[id] = name
                            total_items += 1
                        for name, id in locations.items():
                            location_id_to_name[id] = name
                            total_locations += 1
                        print(f"Loaded {game_name}: {len(items)} items, {len(locations)} locations")
                        print(f"TOTAL: {total_items} items, {total_locations} locations loaded")

                # ITEM EVENTS
                elif cmd == "PrintJSON" and msg.get("type") in ["ItemSend", "ItemReceive"]:
                    item = msg["item"]
                    item_id = item["item"]
                    location_id = item["location"]
                    item_name = item_id_to_name.get(item_id, f"Unknown Item {item_id}")
                    location_name = location_id_to_name.get(location_id, f"Unknown Location {location_id}")
                    # Sender info
                    sender_slot = item.get("player")
                    sender_name = slot_to_name.get(sender_slot, f"Player{sender_slot}")
                    sender_game = slot_to_game.get(sender_slot, "Unknown Game")
                    # Receiver info
                    receiver_slot = msg.get("receiving")
                    receiver_name = slot_to_name.get(receiver_slot, f"Player{receiver_slot}")
                    #HTML Finished event text with colours and formatting
                    SENDER_COLOUR = get_player_colour(sender_slot, sender_name)
                    RECEIVER_COLOUR = get_player_colour(receiver_slot, receiver_name)
                    sender_html = f'<span style="color:{SENDER_COLOUR};font-weight:bold">{sender_name}</span>'
                    receiver_html = f'<span style="color:{RECEIVER_COLOUR};font-weight:bold">{receiver_name}</span>'
                    item_html = f'<span style="color:{ITEM_COLOUR};font-weight:bold;text-shadow:0 0 6px {ITEM_COLOUR};">{item_name}</span>'
                    location_html = f'<span style="color:{LOCATION_COLOUR}">{location_name}</span>'
                    game_html = f'<span style="color:{GAME_COLOUR}">{sender_game}</span>'
                    event_text = (
                        f"{sender_html} sent {item_html} to {receiver_html} "
                        f"by completing {location_html} in {game_html}"
                    )
                    add_event(event_text)
                    print(event_text)

# Status response parser
                elif cmd == "PrintJSON":
                    for entry in msg.get("data",[]):
                        text = entry.get("text","")
                        lines = text.split("\n")
                        for line in lines:
                            if " has " in line and "(" in line and "/" in line:
                                try:
                                    name = line.split(" has ")[0].strip()
                                    numbers = line.split("(")[1].split(")")[0]
                                    done,total = numbers.split("/")
                                    connections = int(line.split(" has ")[1].split(" connection")[0])
                                    done = int(done)
                                    total = int(total)
                                    overlay_data["players"][name]["checks_done"] = done
                                    overlay_data["players"][name]["total_checks"] = total
                                    overlay_data["players"][name]["percent"] = round((done/total)*100,1)
                                    overlay_data["players"][name]["connections"] = connections
                                    overlay_data["players"][name]["connected"] = connections>0
                                except:
                                    pass
                # Deathlink
                elif cmd == "DeathLink" in msg.get("tags",[]):
                    data = msg.get("data",{})
                    player = data.get("source","Unknown")
                    cause = data.get("cause","Died mysteriously.")
                    player_html = f'<span style="color:{SENDER_COLOUR};font-weight:bold">{player}</span>'
                    cause_html = f'<span style="color:{ITEM_COLOUR};font-weight:bold;text-shadow:0 0 6px {ITEM_COLOUR};">{cause}</span>'
                    event_text = f"💀 {player_html} died: {cause_html}"
                    print("DeathLink detected:",event_text)
                    add_event(event_text)

def run_flask():
    app.run(port=5000)

if __name__ == "__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    event_loop.run_until_complete(listen())