"""Puts the stats panel into the OBS scene 'Live' as a browser source, over the game windows.

    D:\\anno\\stream\\.venv\\Scripts\\python.exe -I tools/agent/turnier/stats/obs_panel.py [add|remove|shot OUT.png]
        [--url http://127.0.0.1:7690/] [--scene Live] [--name Turnier-Stats]

add     create the browser source (1920x1080, transparent, no audio of its own) on top of the scene,
        or update its URL if it is there; it covers the whole canvas, the page draws the cards
remove  take it out of the scene again
shot    an image of the scene as streamed (to check where the cards land)
Needs obs-websocket on (Tools > WebSocket Server Settings); the password is read from its config.
"""
import argparse
import base64
import json
import os
from pathlib import Path

import obsws_python as obs

ap = argparse.ArgumentParser()
ap.add_argument("action", nargs="?", default="add", choices=["add", "remove", "shot"])
ap.add_argument("out", nargs="?")
ap.add_argument("--url", default="http://127.0.0.1:7690/", help="without the key; it is added from the key file")
ap.add_argument("--scene", default="Live")
ap.add_argument("--name", default="Turnier-Stats")
args = ap.parse_args()

cfg = json.loads((Path(os.environ["APPDATA"]) / "obs-studio/plugin_config/obs-websocket/config.json").read_text())
cl = obs.ReqClient(host="127.0.0.1", port=cfg["server_port"], password=cfg["server_password"], timeout=5)

video = cl.get_video_settings()
width, height = video.base_width, video.base_height
inputs = {i["inputName"] for i in cl.get_input_list().inputs}

if args.action == "shot":
    r = cl.get_source_screenshot(args.scene, "png", 1280, 720, -1)
    Path(args.out or "live.png").write_bytes(base64.b64decode(r.image_data.split(",", 1)[1]))
    print("wrote", args.out or "live.png")
elif args.action == "remove":
    if args.name in inputs:
        cl.remove_input(args.name)
        print("removed", args.name)
    else:
        print("no source", args.name)
else:
    key = (Path(os.environ["USERPROFILE"]) / ".open1602-turnier-stats-key").read_text(encoding="utf-8").strip()
    url = args.url + ("&" if "?" in args.url else "?") + "key=" + key
    settings = {
        "url": url, "is_local_file": False, "width": width, "height": height, "fps": 10,
        "css": "body { background-color: rgba(0, 0, 0, 0); margin: 0; overflow: hidden; }",
        "reroute_audio": True,  # whatever the page might play goes into OBS's mixer (muted), not twice to the speakers
        "shutdown": False, "restart_when_active": False,
    }
    if args.name in inputs:
        cl.set_input_settings(args.name, settings, True)
        cl.press_input_properties_button(args.name, "refreshnocache")  # load a changed panel.html
        print("updated", args.name)
    else:
        cl.create_input(args.scene, args.name, "browser_source", settings, True)
        print("created", args.name, f"{width}x{height}")
    cl.set_input_mute(args.name, True)
    item = cl.get_scene_item_id(args.scene, args.name).scene_item_id
    cl.set_scene_item_transform(args.scene, item, {"positionX": 0, "positionY": 0, "scaleX": 1.0, "scaleY": 1.0})
    # On top of the game windows; the title text stays above it.
    items = cl.get_scene_item_list(args.scene).scene_items
    top = max(i["sceneItemIndex"] for i in items)
    titel = next((i for i in items if i["sourceName"] == "Titel"), None)
    cl.set_scene_item_index(args.scene, item, top if titel is None else max(0, titel["sceneItemIndex"]))
    cl.set_scene_item_enabled(args.scene, item, True)
    print("in scene", args.scene)
