# Rogipelago Tracker - Integration with Archipelago, made pretty - By Roganz - Version Alpha 2.3
#!/usr/bin/env python3
import asyncio
from collections import deque
import re
from datetime import datetime
import websockets
import json
from flask import Flask, jsonify, send_from_directory
import threading
from flask_cors import CORS
import sys
import logging
import webbrowser
import os
import time
from queue import Queue
import atexit
from Rogipelago_Spoiler_Parser import load_spoiler_file

DEBUG = False
# Receiving  events, we can request status to refresh checks only during high-volume bursts
STATUS_REQUEST_COOLDOWN = 20
STATUS_REQUEST_FLOOD_THRESHOLD = 20
# Maximum number of recent events to display on website (full history kept in memory/logs)
MAX_DISPLAY = 200
overlay_data = {"players": {}, "recent_events": deque(maxlen=MAX_DISPLAY)}
# Input variables from the user (Can be passed directly in command line, or input manually on launch)
ARCHIPELAGO_URI_INPUT = sys.argv[1] if len(sys.argv) > 1 else input("Enter the Archipelago server connection details (e.g. archipelago.gg:38281): ")
SLOT_NAME = sys.argv[2] if len(sys.argv) > 2 else input("Enter a valid slot name: ")
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else input("Enter password for this slot, else leave blank: ") or None
SPOILER_FILE = sys.argv[4] if len(sys.argv) > 4 else input("Enter location of spoiler file for Sphere tracking and Go mode: ") or None
CUSTOM_PLAYER_COLOURS = {
    "Roganz": "#db1414",
    "Lizzz": "#8713bd"
}
ITEM_COLOUR = "#ca8d30"
LOCATION_COLOUR = "#5fbb35"
GAME_COLOUR = "#7a3cc8"

if ARCHIPELAGO_URI_INPUT.startswith("archipelago"):
    ARCHIPELAGO_URI = "wss://" + ARCHIPELAGO_URI_INPUT
else:
    ARCHIPELAGO_URI = "ws://" + ARCHIPELAGO_URI_INPUT
# Logging setup
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    WEB_ROOT = os.path.join(BASE_DIR)
    RAW_ROOT = os.path.join(BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    WEB_ROOT = BASE_DIR
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Spoiler logging
spoiler_data = load_spoiler_file(SPOILER_FILE)
SPOILERS_ENABLED = spoiler_data is not None
if SPOILERS_ENABLED:
    print("[SPOILER] Spoiler features ENABLED")
else:
    print("[SPOILER] Running in non-spoiler mode")

# Script variables
slot_to_name = {}
slot_to_game = {}
item_id_to_name = {}
location_id_to_name = {}
multiworld_games = set()
connections = {}
players = []
websocket_connection = None
session_active = False
event_loop = None
last_status_request_time = 0
data_lock = threading.RLock()
SPHERE_MAP = spoiler_data["sphere_map"] if SPOILERS_ENABLED else {}

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
            player = create_or_restore_player(name, game, slot)
            player["game"] = game
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
    elif archipelago_response == "DataPackage":
        with data_lock:
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
        #TODO TEST REMOVE THIS
        #sender_run_time = 0
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
        with data_lock:
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
                        if DEBUG == True:
                            print(f"[DEBUG] {player_name} +1 at {location_name}")
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
        with data_lock:
            if player_name in overlay_data["players"]:
                player = overlay_data["players"][player_name]
                update_player_timer(player, False, event_ts)
                if player.get("time_finished") is None:
                    player["time_finished"] = event_ts
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
        with data_lock:
            if name in overlay_data["players"]:
                overlay_data["players"][name]["deaths"] += 1
                save_tracker_state()
        add_event(event_text)
    elif archipelago_response == "PrintJSON" and archipelago_response_type in ["Join", "Part", "Disconnect"]:
        slot = msg.get("slot")
        name = slot_to_name.get(slot)
        if not name or name not in overlay_data["players"]:
            return
        with data_lock:
            player = overlay_data["players"][name]
            now = time.time()
            if archipelago_response_type == "Join":
                slot_id = msg['slot']
                connections.setdefault(slot_id, {})
                connections[slot_id]['connected'] = True
                connections[slot_id]['name'] = msg.get('alias', connections[slot_id].get('name'))
                player["connected"] = True
                update_player_timer(player, True, now)
            else:
                player["connected"] = False
                update_player_timer(player, False, now)

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
        with data_lock:
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
            save_tracker_state()
        print(f"[LIVE CHECK] {player_name} +{len(new_locs)}")

def process_events():
    while True:
        if not event_queue.empty():
            msg = event_queue.get()
            try:
                message_handler(msg)
            except Exception as e:
                print("[ERROR processing message]", e, msg)
        else:
            time.sleep(0.01)

        optional_send_status_request()

SAFE_URI = ARCHIPELAGO_URI.replace("://", "_").replace(":", "_")
LOG_FILE = f"Rogipelago_{SAFE_URI}.log"
STATE_FILE = f"Rogipelago_{SAFE_URI}_state.json"
log_buffer = []
event_queue = Queue()
app = Flask(__name__)
CORS(app)

# Utility functions
def get_player_colour(slot, name):
    if name in CUSTOM_PLAYER_COLOURS:
        return CUSTOM_PLAYER_COLOURS[name]
    hue = (slot * 137.5) % 360
    if 180 <= hue <= 270:
        saturation, lightness = 100, 65
    else:
        saturation, lightness = 70, 60
    return f"hsl({hue:.1f}, {saturation}%, {lightness}%)"

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

# Ensure timer state remains consistent when connection status changes.
def update_player_timer(player, is_connected, now=None):
    if now is None:
        now = time.time()
    changed = False
    if is_connected:
        if player.get("time_started") is None:
            player["time_started"] = now
            changed = True
    else:
        if player.get("time_started") is not None:

            player["total_time"] = (
                player.get("total_time", 0)
                + (now - player["time_started"])
            )
            player["time_started"] = None
            changed = True
    if changed:
        save_tracker_state()

# Create or initialize a new player entry, loading saved time data if available.
def create_or_restore_player(name, game="Unknown", slot=0):
    if name in overlay_data["players"]:
        return overlay_data["players"][name]
    player = {
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
        "total_time": 0.0,
        "seen_locations": set()
    }
    overlay_data["players"][name] = player
    return player

def periodic_time_save():
    while True:
        try:
            save_tracker_state()
        except Exception as e:
            print("[ERROR saving state]", e)
        time.sleep(10)

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
    with data_lock:
        overlay_data["recent_events"].append(text)
        log_buffer.append(text)
    save_tracker_state()

def save_tracker_state():
    with data_lock:
        players = {}
        for name, p in overlay_data["players"].items():
            players[name] = {
                "game": p.get("game"),
                "checks_done": p.get("checks_done", 0),
                "total_checks": p.get("total_checks", 0),
                "percent": p.get("percent", 0),
                "connections": p.get("connections", 0),
                "deaths": p.get("deaths", 0),
                "connected": p.get("connected", False),
                "colour": p.get("colour"),
                "time_started": p.get("time_started"),
                "time_finished": p.get("time_finished"),
                "total_time": p.get("total_time", 0),
                "seen_locations": list(p.get("seen_locations", set()))
            }
        payload = {
            "saved_at": time.time(),
            "players": players,
            "recent_events": list(overlay_data["recent_events"])
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)

def load_tracker_state():
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        saved_at = payload.get("saved_at", time.time())
        downtime = max(0, time.time() - saved_at)
        with data_lock:
            overlay_data["recent_events"] = deque(
                payload.get("recent_events", []),
                maxlen=MAX_DISPLAY
            )
            saved_players = payload.get("players", {})
            for name, saved in saved_players.items():

                player = create_or_restore_player(name)

                player.update(saved)

                player["seen_locations"] = set(
                    saved.get("seen_locations", [])
                )

                if (
                    player.get("time_started") is not None
                    and player.get("time_finished") is None
                ):
                    player["total_time"] += downtime
    except Exception as e:
        print("[ERROR] Could not load tracker state:", e)

def flush_logs():
    while True:
        with data_lock:
            if log_buffer:
                to_write = list(log_buffer)
                log_buffer.clear()
            else:
                to_write = None
        if to_write:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write("\n".join(to_write) + "\n")
        time.sleep(5)
async def send_status_request():
    if websocket_connection:
        await websocket_connection.send(json.dumps([{"cmd": "Say", "text": "!status"}]))

def optional_send_status_request():
    global last_status_request_time
    if not websocket_connection or not event_loop:
        return
    now = time.time()
    if event_queue.qsize() < STATUS_REQUEST_FLOOD_THRESHOLD:
        return
    if now - last_status_request_time < STATUS_REQUEST_COOLDOWN:
        return
    last_status_request_time = now
    asyncio.run_coroutine_threadsafe(send_status_request(), event_loop)

# Centralized status parser
def parse_player_status(status_text):
    now = time.time()
    lines = status_text.split("\n")
    for line in lines:
        with data_lock:
            if DEBUG:
                print(f"[DEBUG] {line}")
            try:
                # Archipelago status parser (handles brackets in game names now!)
                status_regex = re.search(
                    r'^(?P<name>.+?)\s+has\s+(?P<connections>\d+)\s+connections?.*\((?P<done>\d+)/(?P<total>\d+)\)\s*$',
                    line
                )

                if not status_regex:
                    continue

                name = status_regex.group("name").strip()
                done = int(status_regex.group("done"))
                total = int(status_regex.group("total"))
                conn_count = int(status_regex.group("connections"))

                # Remove self-connection from count
                if name == SLOT_NAME:
                    conn_count = max(0, conn_count - 1)

                # Create or restore player with saved time data (if new).
                create_or_restore_player(name, "Unknown", 0)
                player = overlay_data["players"][name]

                # Update check counts
                player["checks_done"] = done
                player["total_checks"] = total
                player["percent"] = round((done / total) * 100, 1) if total else 0

                is_connected = conn_count > 0
                player["connections"] = conn_count
                player["connected"] = is_connected
                state_changed = True
                save_tracker_state()
                # If finished, do nothing with the timer.
                if player["time_finished"] is not None:
                    continue

                # Update timer state only on actual connect/disconnect transitions.
                update_player_timer(player, is_connected, now)

            except Exception as e:
                print("[ERROR] Status parse:", e, "Line:", line)
# Flask endpoints
@app.route("/")
def index():
    return send_from_directory(WEB_ROOT, "Rogipelago_Website.html")

@app.route("/data")
def data():
    with data_lock:
        output = {"players": {}, "recent_events": list(overlay_data.get("recent_events", []))}
        for name, p in overlay_data.get("players", {}).items():
            current_time = int(get_player_current_time(p))
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
            if isinstance(v, (set, Queue)):
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
        "queue_length": event_queue.qsize()
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
        "queue_length": event_queue.qsize()
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
        with data_lock:
            overlay_data["recent_events"] = deque(
                [line.strip() for line in f.readlines()],
                maxlen=MAX_DISPLAY
            )
    print(f"[LOG] Loaded {len(overlay_data['recent_events'])} previous events")

load_tracker_state()
if overlay_data["recent_events"]:
    choice = input(
        f"It looks like you're continuing a previous session, "
        f"({len(overlay_data['recent_events'])} events). Continue? (y/n): "
    )
    if not choice.lower().startswith("y"):
        with data_lock:
            overlay_data["recent_events"].clear()
            overlay_data["players"].clear()
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        if os.path.exists(LOG_FILE):
            open(LOG_FILE, "w").close()

# WebSocket listener
async def listen():
    global websocket_connection
    global ARCHIPELAGO_URI
    while True:
        try:
            print(f"[WS] Connecting to {ARCHIPELAGO_URI}")
            async with websockets.connect(ARCHIPELAGO_URI) as ws:
                print("[WS] Connected to Archipelago server")
                await ws.send(json.dumps([{
                    "cmd": "Connect",
                    "name": SLOT_NAME,
                    "password": PASSWORD,
                    "game": "",
                    "uuid": SLOT_NAME,
                    "items_handling": 7,
                    "version": {"major":0,"minor":6,"build":6,"class":"Version"},
                    "tags": ["AP", "Tracker", "DeathLink"]
                }]))
                print("[WS] Sent Connect packet")
                connected = False
                while not connected:
                    raw = await ws.recv()
                    messages = json.loads(raw)

                    for msg in messages:
                        if msg.get("cmd") == "Connected":
                            connected = True
                            print("[WS] Authenticated with Archipelago")
                            event_queue.put(msg)
                        elif msg.get("cmd") == "ConnectionRefused":
                            print("[WS] Connection refused:", msg)
                            return
                        else:
                            event_queue.put(msg)
                websocket_connection = ws
                while True:
                    try:
                        raw = await ws.recv()
                        messages = json.loads(raw)
                        for msg in messages:
                            event_queue.put(msg)
                    except websockets.exceptions.ConnectionClosedOK:
                        print("[INFO] Server closed connection gracefully. Reconnecting in 5s...")
                        break
                    except websockets.exceptions.ConnectionClosedError as e:
                        print(f"[ERROR] Connection closed unexpectedly: {e}. Retrying in 5s...")
                        break
                    except json.JSONDecodeError as e:
                        print(f"[WARN] Failed to parse JSON: {e} - raw: {raw}")
        except websockets.InvalidMessage:
            if ARCHIPELAGO_URI.startswith("ws://"):
                ARCHIPELAGO_URI = ARCHIPELAGO_URI.replace("ws://", "wss://")
                continue
            elif ARCHIPELAGO_URI.startswith("wss://"):
                ARCHIPELAGO_URI = ARCHIPELAGO_URI.replace("wss://", "ws://")
                continue
        except Exception as e:
            print(f"[ERROR] Could not connect: {e}. Retrying in 5s...")
        await asyncio.sleep(5)

def shutdown_handler():
    print("[INFO] Saving tracker state before exit")
    save_tracker_state()

def run_flask():
    app.run(host="localhost", port=8745, debug=False, use_reloader=False)

def start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(listen())
load_tracker_state()

if __name__ == "__main__":
    print("[INFO] Starting Rogipelago Tracker")
    threading.Thread(target=process_events, daemon=True).start()
    threading.Thread(target=flush_logs, daemon=True).start()
    threading.Thread(target=periodic_time_save, daemon=True).start()
    threading.Thread(target=run_flask, daemon=True).start()
    # Start websocket asyncio loop (main thread)
    atexit.register(shutdown_handler)
    webbrowser.open("http://localhost:8745")
event_loop = asyncio.new_event_loop()
start_async_loop(event_loop)