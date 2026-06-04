import os
import re
from collections import defaultdict

def load_spoiler_file(path: str):
    if not path or not os.path.exists(path):
        print("[SPOILER] No spoiler file provided or file missing.")
        return None
    print(f"[SPOILER] Loading spoiler file: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        sphere_map = _parse_playthrough(lines)
        print("[SPOILER] Spoiler file successfully parsed.")
        print(f"[SPOILER] Parsed spheres for {len(sphere_map)} players.")
        return {
            "sphere_map": sphere_map
        }
    except Exception as e:
        print(f"[SPOILER] Failed to parse spoiler file: {e}")
        return None

# Parser, to build sphere maps for each player.
def _parse_playthrough(lines):
    in_playthrough = False
    current_sphere = None
    sphere_map = defaultdict(dict)
    sphere_start_regex = re.compile(r"^(\d+):\s*\{$")
    item_line_regex = re.compile(r":\s*(.*?)\s*\((.*?)\)\s*$")
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("Playthrough:"):
            in_playthrough = True
            continue
        if not in_playthrough:
            continue
        sphere_match = sphere_start_regex.match(line)
        if sphere_match:
            current_sphere = int(sphere_match.group(1))
            continue
        if line == "}":
            current_sphere = None
            continue
        if current_sphere is None:
            continue
        if not line:
            continue
        item_match = item_line_regex.search(line)
        if not item_match:
            continue
        item_name = item_match.group(1).strip()
        receiving_player = item_match.group(2).strip()
        sphere_map[receiving_player][item_name] = current_sphere
    return dict(sphere_map)