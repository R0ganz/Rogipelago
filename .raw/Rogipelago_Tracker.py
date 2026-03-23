# Rogipelago Tracker - Integration with Archipelago, made pretty - By Roganz - Version
import asyncio
import re
from datetime import datetime
import websockets
import json
from flask import Flask, jsonify, send_from_directory, abort
import threading
from flask_cors import CORS
import sys
import logging
import webbrowser
import os
import time
from collections import deque

# DEBUG mode toggle
DEBUG = False  # Set to False when publishing

# Receiving  events, we can request status to refresh checks only during high-volume bursts
STATUS_REQUEST_COOLDOWN = 20
STATUS_REQUEST_FLOOD_THRESHOLD = 20
# Maximum number of recent events to display on website (full history kept in memory/logs)
MAX_DISPLAY = 200
MAX_LOGGING = 1000
overlay_data = {"players": {}, "recent_events": deque(maxlen=MAX_DISPLAY)}

# Input variables from the user (Can be passed directly in command line, or input manually on launch)
ARCHIPELAGO_URI = sys.argv[1] if len(sys.argv) > 1 else input("Enter the Archipelago server connection details (e.g. archipelago.gg:38281):")
SLOT_NAME = sys.argv[2] if len(sys.argv) > 2 else input("Enter a valid slot name:")
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else input("Enter password for this slot, else leave blank: ") or None
CUSTOM_PLAYER_COLOURS = {
    "Roganz": "#db1414",
    "Lizzz": "#8713bd"
}
ITEM_COLOUR = "#ca8d30"
LOCATION_COLOUR = "#5fbb35"
GAME_COLOUR = "#7a3cc8"

if ARCHIPELAGO_URI.startswith("archipelago"):
    ARCHIPELAGO_URI = "wss://" + ARCHIPELAGO_URI
else:
    ARCHIPELAGO_URI = "ws://" + ARCHIPELAGO_URI
# Logging setup
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    WEB_ROOT = os.path.join(BASE_DIR, "_internal")
    RAW_ROOT = os.path.join(BASE_DIR, ".raw")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    WEB_ROOT = BASE_DIR
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Script variables
slot_to_name = {}
slot_to_game = {}
item_id_to_name = {}
location_id_to_name = {}
multiworld_games = set()
connections = {}
players = []
websocket_connection = None
event_loop = None
last_status_request_time = 0

def message_handler(msg):
    global connections
    archipelago_response = msg.get("cmd")
    archipelago_response_type = msg.get("type")
    archipelago_error = msg.get("errors")
    if DEBUG:
        print("[DEBUG]", json.dumps(msg, indent=2))
    if "InvalidSlot" in str(archipelago_error):
        print("Slot given incorrect. Check the name within the YAML file and try again")
        return
    elif "InvalidGame" in str(archipelago_error):
        print("Game name incorrect. Check the name within the YAML file and try again")
        return
    elif "InvalidPassword" in str(archipelago_error):
        print("Password incorrect. Check the name within the YAML file and try again")
        return
    if archipelago_response == "Connected":
        print("Connected successfully")
        connections = {}  # reset connections
        # Request initial status
        asyncio.run_coroutine_threadsafe(
            websocket_connection.send(json.dumps([{
                "cmd": "Say",
                "text": "!status"
            }])),
            event_loop
        )
        slot_info = msg.get("slot_info", {})
        for player in msg["players"]:
            slot = player["slot"]
            name = player["name"]
            game = slot_info.get(str(slot), {}).get("game", "Unknown")
            slot_to_name[slot] = name
            slot_to_game[slot] = game
            multiworld_games.add(game)
            connections[slot] = {
                'name': player['name'],
                'alias': player['alias'],
                'team': player['team'],
                'connected': True
            }
            overlay_data["players"][name] = {
                "game": game,
                "checks_done": 0,
                "total_checks": 0,
                "percent": 0,
                "connections": 0,
                "deaths": 0,
                "connected": False,
                "colour": get_player_colour(slot, name),
                "time_started": None,
                "time_finished": None,
                "total_time": 0,
            }
        print("Detected games:", multiworld_games)
        for game in multiworld_games:
            asyncio.run_coroutine_threadsafe(
                websocket_connection.send(json.dumps([{
                    "cmd": "GetDataPackage",
                    "games": [game]
                }])),
                event_loop
            )
        rebuild_death_counts()
        load_time_data()
        webbrowser.open("http://localhost:5000")
    elif archipelago_response == "DataPackage":
        games = msg.get("data", {}).get("games", {})
        for game, data in games.items():
            item_id_to_name.setdefault(game, {})
            location_id_to_name.setdefault(game, {})
            for name, id in data.get("item_name_to_id", {}).items():
                item_id_to_name[game][id] = name
            for name, id in data.get("location_name_to_id", {}).items():
                location_id_to_name[game][id] = name
    elif archipelago_response == "PrintJSON" and archipelago_response_type in ["ItemSend", "ItemReceive"]:
        sender_slot = msg["item"]["player"]
        receiver_slot = msg.get("receiving")
        sender_name = slot_to_name.get(sender_slot, f"Player{sender_slot}")
        receiver_name = slot_to_name.get(receiver_slot, f"Player{receiver_slot}")
        sender_game = slot_to_game.get(sender_slot)
        receiver_game = slot_to_game.get(receiver_slot)
        item_id = msg["item"]["item"]
        location_id = msg["item"]["location"]
        item_name = item_id_to_name.get(receiver_game, {}).get(item_id, f"Item {item_id}")
        location_name = location_id_to_name.get(sender_game, {}).get(location_id, f"Location {location_id}")
        sender_colour = get_player_colour(sender_slot, sender_name)
        receiver_colour = get_player_colour(receiver_slot, receiver_name)
        event_ts = time.time()
        sender_run_time = 0
        if sender_name in overlay_data["players"]:
            sender_run_time = get_player_current_time(overlay_data["players"][sender_name])
        event_time_html = format_event_timestamp(event_ts, run_seconds=sender_run_time)
        event_text = (
            f'<span style="color:{sender_colour};font-weight:bold;text-shadow:0 0 6px {sender_colour}">{sender_name}</span> '
            f'sent <span style="color:{ITEM_COLOUR};text-shadow:0 0 6px {ITEM_COLOUR}">{item_name}</span> '
            f'to <span style="color:{receiver_colour};font-weight:bold;text-shadow:0 0 6px {receiver_colour}">{receiver_name}</span> '
            f'by completing <span style="color:{LOCATION_COLOUR};text-shadow:0 0 6px {LOCATION_COLOUR}">{location_name}</span> '
            f'{event_time_html}'
        )
        add_event(event_text)
        # Update checks for the sender (whose location was checked)
        if sender_slot in slot_to_name:
            player_name = slot_to_name[sender_slot]
            if player_name in overlay_data["players"]:
                player = overlay_data["players"][player_name]
                if "seen_locations" not in player:
                    player["seen_locations"] = set()
                if location_id not in player["seen_locations"]:
                    player["seen_locations"].add(location_id)
                    player["checks_done"] += 1
                    total = player["total_checks"]
                    player["percent"] = round((player["checks_done"] / total) * 100, 1) if total else 0
                    print(f"[LIVE CHECK] {player_name} +1 at {location_name}")
    elif archipelago_response == "PrintJSON" and archipelago_response_type == "Release":
        slot = msg.get("slot")
        player_name = slot_to_name.get(slot, f"Player{slot}")
        event_ts = time.time()
        player_run_time = 0
        if player_name in overlay_data["players"]:
            player_run_time = get_player_current_time(overlay_data["players"][player_name])
        event_time_html = format_event_timestamp(event_ts, run_seconds=player_run_time)
        event_text = (
            f'<span style="color:{get_player_colour(slot, player_name)};font-weight:bold;text-shadow:0 0 6px {get_player_colour(slot, player_name)}">{player_name}</span> '
            f'has released all remaining items from their world. {event_time_html}'
        )
        if player_name in overlay_data["players"]:
            player = overlay_data["players"][player_name]
            if player.get("time_started") is not None:
                player["total_time"] += event_ts - player["time_started"]
                player["time_started"] = None
            if player.get("time_finished") is None:
                player["time_finished"] = event_ts
                save_time_data()
                print(f"[RELEASE] {player_name} released at {player['time_finished']}")
        add_event(event_text)
    elif archipelago_response == "Bounced" and "DeathLink" in msg.get("tags", []):
        data = msg.get("data", {})
        name = data.get("source", "Unknown")
        cause = data.get("cause", "Died mysteriously.")
        colour = overlay_data["players"].get(name, {}).get("colour", "#fff")
        event_text = (
            f'<span style="color:{colour};font-weight:bold;text-shadow:0 0 6px {colour}">{name}</span> died: '
            f'<span style="color:{ITEM_COLOUR};text-shadow:0 0 6px {ITEM_COLOUR}">{cause}</span>'
        )
        if name in overlay_data["players"]:
            overlay_data["players"][name]["deaths"] += 1
        add_event(event_text)
    elif archipelago_response == "PrintJSON" and archipelago_response_type in ["Join", "Part", "Disconnect"]:
        slot = msg.get("slot")
        name = slot_to_name.get(slot)
        if not name or name not in overlay_data["players"]:
            return
        player = overlay_data["players"][name]
        now = time.time()
        if archipelago_response_type == "Join":
            slot_id = msg['slot']
            connections[slot_id]['connected'] = True
            connections[slot_id]['name'] = msg.get('alias', connections[slot_id].get('name'))
            player["connected"] = True
            if player["time_started"] is None:
                player["time_started"] = now
        else:
            player["connected"] = False
            if player["time_started"]:
                player["total_time"] += now - player["time_started"]
                player["time_started"] = None
        save_time_data()

    elif archipelago_response == "PrintJSON" and archipelago_response_type == "CommandResult":
        for entry in msg.get("data", []):
            text = entry.get("text", "")
            parse_player_status(text)
                        
    elif archipelago_response == "LocationChecks":
        print(f"[DEBUG] LocationChecks received for slot {msg.get('slot')}, locations: {msg.get('locations', [])}")
        player_slot = msg.get("slot")
        player_name = slot_to_name.get(player_slot)

        if player_name not in overlay_data["players"]:
            print(f"[DEBUG] Player {player_name} not in overlay_data")
            return
        locations = msg.get("locations", [])
        player = overlay_data["players"][player_name]
        if "seen_locations" not in player:
            player["seen_locations"] = set()
        new_locs = [loc for loc in locations if loc not in player["seen_locations"]]
        player["seen_locations"].update(new_locs)
        if not new_locs:
            return
        player["checks_done"] += len(new_locs)
        total = player["total_checks"]
        player["percent"] = round(
            (player["checks_done"] / total) * 100, 1
        ) if total else 0
        print(f"[LIVE CHECK] {player_name} +{len(new_locs)}")

def process_events():
    while True:
        if event_queue:
            msg = event_queue.popleft()
            try:
                message_handler(msg)
            except Exception as e:
                print("[ERROR processing message]", e, msg)
        else:
            time.sleep(0.01)
SAFE_URI = ARCHIPELAGO_URI.replace("://", "_").replace(":", "_")
LOG_FILE = f".raw/Rogipelago_{SAFE_URI}.log"
TIME_FILE = f".raw/Rogipelago_{SAFE_URI}.json"
os.makedirs(os.path.dirname(TIME_FILE), exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
log_buffer = []
event_queue = deque()
app = Flask(__name__)
CORS(app)

# Utility functions
def get_player_colour(slot, name):
    if name in CUSTOM_PLAYER_COLOURS:
        return CUSTOM_PLAYER_COLOURS[name]
    hue = (slot * 137) % 360
    return f"hsl({hue}, 70%, 60%)"

def format_run_time(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def get_player_current_time(player):
    current = player.get("total_time", 0)
    if player.get("time_started") is not None:
        current += time.time() - player["time_started"]
    return current

def periodic_time_save():
    while True:
        try:
            save_time_data()
        except Exception as e:
            print("[ERROR saving time data]", e)
        time.sleep(10)  # save every 10 seconds

def format_event_timestamp(event_ts, run_seconds=None):
    # Display host wall-clock time and put player's run time in hover text.
    local_dt = datetime.fromtimestamp(event_ts).astimezone()
    display_time = local_dt.strftime("%H:%M:%S")
    hover_time = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    if run_seconds is not None:
        hover_time += f" | Player run time: {format_run_time(run_seconds)}"
    return (f'<span style="color: #999; font-style: italic; cursor: help;" '
            f'title="{hover_time} (unix {int(event_ts)})">'
            f'[{display_time}]</span>')

def add_event(text):
    overlay_data["recent_events"].append(text)
    log_buffer.append(text)

def flush_logs():
    while True:
        if log_buffer:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write("\n".join(log_buffer) + "\n")
            log_buffer.clear()
        time.sleep(5)

def rebuild_death_counts():
    for player in overlay_data["players"]:
        overlay_data["players"][player]["deaths"] = 0
    death_pattern = re.compile(r'<span[^>]*>(.*?)</span> died:')
    for line in overlay_data["recent_events"]:
        match = death_pattern.search(line)
        if match:
            name = match.group(1)
            if name in overlay_data["players"]:
                overlay_data["players"][name]["deaths"] += 1

def save_time_data():
    data = {}
    now = time.time()
    for name, p in overlay_data["players"].items():
        total_time = p.get("total_time", 0)
        # If currently running, include in total
        if p.get("time_started") is not None:
            total_time += now - p["time_started"]
        data[name] = {
            "time_started": None,  # reset on load
            "time_finished": p.get("time_finished"),
            "total_time": total_time
        }
    with open(TIME_FILE, "w") as f:
        json.dump(data, f)

async def send_status_request():
    if websocket_connection:
        await websocket_connection.send(json.dumps([{"cmd": "Say", "text": "!status"}]))

def optional_send_status_request():
    global last_status_request_time
    if not websocket_connection or not event_loop:
        return
    now = time.time()
    if len(event_queue) < STATUS_REQUEST_FLOOD_THRESHOLD or now - last_status_request_time < STATUS_REQUEST_COOLDOWN:
        return
    last_status_request_time = now
    asyncio.run_coroutine_threadsafe(send_status_request(), event_loop)


def load_time_data():
    if not os.path.exists(TIME_FILE):
        return
    with open(TIME_FILE, "r") as f:
        data = json.load(f)
    for name, t in data.items():
        if name in overlay_data["players"]:
            overlay_data["players"][name]["time_started"] = None
            overlay_data["players"][name]["time_finished"] = t.get("time_finished")
            overlay_data["players"][name]["total_time"] = t.get("total_time", 0)

# Centralized status parser
def parse_player_status(status_text):
    now = time.time()
    lines = status_text.split("\n")
    for line in lines:
        if DEBUG:
            print(f"[DEBUG] {line}")
        if " has " in line and "/" in line and "(" in line:
            try:
                match = re.search(r"\((\d+)/(\d+)\)", line)
                if not match:
                    continue
                
                name = line.split(" has ")[0].strip()
                numbers_match = re.search(r"\((\d+)/(\d+)\)", line)
                if not numbers_match:
                    continue

                done = int(numbers_match.group(1))
                total = int(numbers_match.group(2))
                # Extract connections from "has X connection(s)"
                conn_match = re.search(r"has\s+(\d+)\s+connections?", line)
                conn_count = int(conn_match.group(1)) if conn_match else 0
                save_time_data()

                if name not in overlay_data["players"]:
                    overlay_data["players"][name] = {
                        "game": "Unknown",
                        "checks_done": 0,
                        "total_checks": 0,
                        "percent": 0,
                        "connections": 0,
                        "deaths": 0,
                        "connected": False,
                        "colour": get_player_colour(0, name),
                        "time_started": now,
                        "time_finished": None,
                        "total_time": 0.0,
                    }

                player = overlay_data["players"][name]
                # Update basic info
                player["checks_done"] = done
                player["total_checks"] = total
                player["percent"] = round((done / total)*100,1) if total else 0
                was_connected = player.get("connected", False)
                is_connected = conn_count > 0
                player["connections"] = conn_count
                player["connected"] = is_connected

                # If finished, do nothing
                if player["time_finished"] is not None:
                    continue

                # Update total_time continuously while connected and not finished
                if is_connected and player.get("time_finished") is None:
                    if player["time_started"] is None:
                        player["time_started"] = now
                    elapsed = now - player["time_started"]
                    player["total_time"] += elapsed
                    player["time_started"] = now

                # Pause timer when disconnected
                if not is_connected and player["time_started"] is not None:
                    elapsed = now - player["time_started"]
                    player["total_time"] += elapsed
                    player["time_started"] = None

            except Exception as e:
                print("Status parse error:", e, "Line:", line)

# Flask endpoints
@app.route("/")
def index():
    return send_from_directory(WEB_ROOT, "Rogipelago_Website.html")

@app.route("/<path:filename>")
def static_files(filename):
    requested = os.path.join(WEB_ROOT, filename)
    if os.path.isfile(requested):
        return send_from_directory(WEB_ROOT, filename)
    return abort(404)

@app.route("/data")
def data():
    now = time.time()
    output = {"players": {}, "recent_events": list(overlay_data.get("recent_events", []))}
    for name, p in overlay_data.get("players", {}).items():
        current_time = p.get("total_time", 0)
        if p.get("time_started") is not None:
            end_time = p.get("time_finished") or now
            current_time += end_time - p.get("time_started")

        sanitized_player = {}
        for k, v in p.items():
            if isinstance(v, set):
                sanitized_player[k] = list(v)
            else:
                sanitized_player[k] = v

        sanitized_player["current_time"] = int(current_time)
        output["players"][name] = sanitized_player

    return jsonify(output)

def make_serializable_player_data():
    cleaned = {}
    for name, p in overlay_data.get("players", {}).items():
        sanitized = {}
        for k, v in p.items():
            if isinstance(v, (set, deque)):
                sanitized[k] = list(v)
            elif isinstance(v, (int, float, str, bool)) or v is None:
                sanitized[k] = v
            else:
                sanitized[k] = v
        cleaned[name] = sanitized
    return cleaned

@app.route("/debug")
def debug():
    data = {
        "overlay_data": {
            "players": make_serializable_player_data(),
            "recent_events": list(overlay_data.get("recent_events", []))
        },
        "connections": connections,
        "slot_to_name": slot_to_name,
        "slot_to_game": slot_to_game,
        "multiworld_games": list(multiworld_games),
        "queue_length": len(event_queue)
    }
    return app.response_class(json.dumps(data, default=list, indent=2), mimetype="application/json")

@app.route("/debug.html")
def debug_html():
    debug_obj = {
        "overlay_data": {
            "players": make_serializable_player_data(),
            "recent_events": list(overlay_data.get("recent_events", []))
        },
        "connections": connections,
        "slot_to_name": slot_to_name,
        "slot_to_game": slot_to_game,
        "multiworld_games": list(multiworld_games),
        "queue_length": len(event_queue)
    }
    return f"<html><head><title>Debug Data</title></head><body><h1>Debug JSON</h1><pre>{json.dumps(debug_obj, indent=2)}</pre></body></html>"

@app.route("/refresh")
def manual_refresh():
    if websocket_connection and event_loop:
        asyncio.run_coroutine_threadsafe(send_status_request(), event_loop)
    return {"status": "requested"}

# Load previous log
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        overlay_data["recent_events"] = [line.strip() for line in f.readlines()]
    print(f"[LOG] Loaded {len(overlay_data['recent_events'])} previous events")

if overlay_data["recent_events"]:
    choice = input(f"It looks like you're continuing a previous session, ({len(overlay_data['recent_events'])} events). Continue? (y/n): ")
    if choice.lower().startswith("y"):
        CONTINUING_SESSION = True
    else:
        overlay_data["recent_events"] = []
        open(LOG_FILE, "w").close()

# WebSocket listener
async def listen():
    global websocket_connection
    while True:
        try:
            async with websockets.connect(ARCHIPELAGO_URI) as ws:
                websocket_connection = ws
                print("Connected to Archipelago server")

                await ws.send(json.dumps([{
                    "cmd": "Connect",
                    "name": SLOT_NAME,
                    "password": PASSWORD,
                    "game": "",
                    "uuid": SLOT_NAME,
                    "items_handling": 0,
                    "version": {"major":0,"minor":6,"build":6,"class":"Version"},
                    "tags": ["AP", "Tracker", "DeathLink"]
                }]))

                for player in overlay_data["players"]:
                    overlay_data["players"][player]["deaths"] = 0

                while True:
                    try:
                        raw = await ws.recv()
                        messages = json.loads(raw)
                        for msg in messages:
                            event_queue.append(msg)
                            optional_send_status_request()
                    except websockets.exceptions.ConnectionClosedOK:
                        print("[INFO] Server closed connection gracefully. Reconnecting in 5s...")
                        break
                    except websockets.exceptions.ConnectionClosedError as e:
                        print(f"[ERROR] Connection closed unexpectedly: {e}. Retrying in 5s...")
                        break
                    except json.JSONDecodeError as e:
                        print(f"[WARN] Failed to parse JSON: {e} - raw: {raw}")
        except Exception as e:
            print(f"[ERROR] Could not connect: {e}. Retrying in 5s...")
        await asyncio.sleep(5)

def run_flask():
    app.run(port=5000)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=process_events, daemon=True).start()
    threading.Thread(target=flush_logs, daemon=True).start()
    threading.Thread(target=periodic_time_save, daemon=True).start()
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    event_loop.run_until_complete(listen())
