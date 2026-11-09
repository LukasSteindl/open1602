"""Live scoreboard of the four-agent tournament, for an OBS browser source.

Every INTERVAL seconds:
  * the referee (port 7601, the operator's port) saves the running game as 'turnier-stats';
    'o1602-tool state FILE --scores' reads money, balance and inhabitants of every player from it;
    the file is deleted right away, so no agent finds it in the savegame folder.
    The agents' ports 7602-7605 are never touched.
  * the token counters of the language models are read from their logs:
      Claude, ClaudeJev  Claude Code transcripts (~/.claude/projects/*/<id>.jsonl, found by the
                         session title "Turnier-Agent 1" / "Turnier-Agent 2" in <id>/custom-title.json,
                         with their subagents); usage per assistant message, counted once per message id
      Sol, SolJev        Codex rollouts (~/.codex/sessions/**/rollout-*.jsonl), told apart by the agent
                         folder they work in (a3-sol / a4-sol-jev); the last cumulative token_count
  * everything goes to /stats.json; / serves panel.html.

Run:   python -I tools/agent/turnier/stats/stats_panel.py [--port 7690] [--interval 15]
Show:  http://127.0.0.1:7690/?key=KEY             (OBS browser source, 1920x1080, transparent)
       http://127.0.0.1:7690/?key=KEY&layout=list (a plain list, e.g. a browser beside the game)
       KEY: printed at the start, kept in %USERPROFILE%\\.open1602-turnier-stats-key
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CTL = ROOT / "bin" / "o1602-ctl.exe"
TOOL = ROOT / "bin" / "o1602-tool.exe"
REFEREE_PORT = 7601
SAVE_NAME = "turnier-stats"
SAVE_FILE = Path(os.environ["APPDATA"]) / "Open1602" / "saves" / f"{SAVE_NAME}.o1602"
HOME = Path(os.environ["USERPROFILE"])
# The page and its numbers only with ?key=...: the agents run on this computer too and should not
# just fetch the others' figures. The key is made once and kept outside the repository; only the
# OBS browser source carries it (obs_panel.py reads it from here).
KEY_FILE = HOME / ".open1602-turnier-stats-key"


def access_key() -> str:
    try:
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    except OSError:
        pass
    import secrets
    key = secrets.token_urlsafe(12)
    KEY_FILE.write_text(key, encoding="utf-8")
    return key

# Name in the game, colour on the map, model, where its window sits on the stream.
AGENTS = [
    {"name": "Claude",    "color": "#3d7bff", "model": "Opus 5.5", "window": "br"},
    {"name": "ClaudeJev", "color": "#f2c230", "model": "Opus 5.5", "window": "tl"},
    {"name": "Sol",       "color": "#f4f4f4", "model": "Sol 6.1",  "window": "tr"},
    {"name": "SolJev",    "color": "#ff8a1e", "model": "Sol 6.1",  "window": "bl"},
]
CLAUDE_TITLES = {"Claude": "Turnier-Agent 1", "ClaudeJev": "Turnier-Agent 2"}
CODEX_FOLDERS = {"Sol": "a3-sol", "SolJev": "a4-sol-jev"}


# ---------------------------------------------------------------- game

SCORE = re.compile(
    r"score player (\d+) money (-?\d+) inhabitants (\d+) taxes (-?\d+) running_costs (-?\d+) military (-?\d+) "
    r"sales (-?\d+) purchases (-?\d+) balance (-?\d+) cities (\d+) classes ([\d,]+) name (.*)")
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def run(args: list[str], timeout: float = 20) -> str:
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(args[0]).name}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def game_scores() -> dict:
    out = run([str(CTL), "--port", str(REFEREE_PORT), "save", SAVE_NAME])
    if not out.startswith("saved"):
        raise RuntimeError(out.strip())
    if not SAVE_FILE.exists():
        raise RuntimeError(f"the referee saved, but {SAVE_FILE} is not there ({out.strip()})")
    try:
        text = run([str(TOOL), "state", str(SAVE_FILE), "--scores"])
    finally:
        try:
            SAVE_FILE.unlink()
        except OSError:
            pass
    players = {}
    time_ms = 0
    for line in text.splitlines():
        if line.startswith("time_ms "):
            time_ms = int(line.split()[1])
        m = SCORE.match(line)
        if m:
            g = m.groups()
            players[g[11].strip()] = {
                "money": int(g[1]), "inhabitants": int(g[2]), "taxes": int(g[3]), "running_costs": int(g[4]),
                "military": int(g[5]), "sales": int(g[6]), "purchases": int(g[7]), "balance": int(g[8]),
                "cities": int(g[9]), "classes": [int(v) for v in g[10].split(",")],
            }
    return {"time_ms": time_ms, "players": players}


# ---------------------------------------------------------------- token logs

class JsonlTail:
    """Reads a growing jsonl file from where it stopped, whole lines only."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0

    def new_lines(self):
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.offset:  # rewritten
            self.offset = 0
        if size == self.offset:
            return
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            data = f.read(size - self.offset)
        end = data.rfind(b"\n")
        if end < 0:
            return
        self.offset += end + 1
        for raw in data[: end + 1].splitlines():
            if raw.strip():
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue


class ClaudeTokens:
    """Opus usage of one Claude Code session and its subagents. Input counts like Codex's: the fresh
    input plus the cache reads and cache writes (Claude's input_tokens alone leaves the cache out)."""

    def __init__(self, title: str):
        self.title = title
        self.tails: dict[Path, JsonlTail] = {}
        self.messages: dict[str, tuple[int, int, int, int]] = {}  # message id -> (in, cache write, cache read, out)

    def find(self) -> list[Path]:
        files = []
        for title_file in glob.glob(str(HOME / ".claude" / "projects" / "*" / "*" / "custom-title.json")):
            try:
                title = json.loads(Path(title_file).read_text(encoding="utf-8")).get("customTitle", "")
            except (OSError, ValueError):
                continue
            if title.startswith(self.title):
                folder = Path(title_file).parent
                files.append(folder.with_suffix(".jsonl"))
                files += [Path(p) for p in glob.glob(str(folder / "subagents" / "*.jsonl"))]
        return [f for f in files if f.exists()]

    def update(self) -> dict | None:
        files = self.find()
        if not files:
            return None
        for path in files:
            tail = self.tails.setdefault(path, JsonlTail(path))
            for rec in tail.new_lines():
                msg = rec.get("message") if rec.get("type") == "assistant" else None
                usage = msg.get("usage") if isinstance(msg, dict) else None
                if not usage:
                    continue
                key = f"{path.name}:{msg.get('id') or rec.get('uuid')}"
                self.messages[key] = (usage.get("input_tokens", 0) or 0,
                                      usage.get("cache_creation_input_tokens", 0) or 0,
                                      usage.get("cache_read_input_tokens", 0) or 0,
                                      usage.get("output_tokens", 0) or 0)
        fresh = sum(v[0] for v in self.messages.values())
        write = sum(v[1] for v in self.messages.values())
        read = sum(v[2] for v in self.messages.values())
        out = sum(v[3] for v in self.messages.values())
        return {"input": fresh + write + read, "cached": read, "output": out, "calls": len(self.messages),
                "sources": len(files)}


class CodexTokens:
    """Sol usage from the Codex rollouts of the tournament. A rollout belongs to an agent when it names
    that agent's folder more often than the other's; per rollout the last cumulative count."""

    def __init__(self, since: dt.datetime):
        self.since = since
        self.tails: dict[Path, JsonlTail] = {}
        self.mentions: dict[Path, dict[str, int]] = {}
        self.totals: dict[Path, dict] = {}

    def update(self) -> dict[str, dict | None]:
        cutoff = self.since.timestamp()
        for p in glob.glob(str(HOME / ".codex" / "sessions" / "**" / "rollout-*.jsonl"), recursive=True):
            path = Path(p)
            try:
                if path.stat().st_mtime < cutoff and path not in self.tails:
                    continue
            except OSError:
                continue
            tail = self.tails.setdefault(path, JsonlTail(path))
            counts = self.mentions.setdefault(path, {k: 0 for k in CODEX_FOLDERS})
            for rec in tail.new_lines():
                payload = rec.get("payload") or {}
                if rec.get("type") == "session_meta":
                    started = payload.get("timestamp", "")
                    if started and dt.datetime.fromisoformat(started.replace("Z", "+00:00")) < self.since:
                        counts["_old"] = 1
                usage = None
                if rec.get("type") == "event_msg" and payload.get("type") == "token_count":
                    usage = (payload.get("info") or {}).get("total_token_usage")
                elif rec.get("type") == "token_usage_record":
                    usage = payload.get("thread_token_usage")
                if usage:
                    best = self.totals.get(path)
                    if best is None or usage.get("total_tokens", 0) >= best.get("total_tokens", 0):
                        self.totals[path] = usage
                    continue
                line = json.dumps(payload) if payload else ""
                for agent, folder in CODEX_FOLDERS.items():
                    counts[agent] += line.count(folder)
        result: dict[str, dict | None] = {agent: None for agent in CODEX_FOLDERS}
        for path, counts in self.mentions.items():
            if counts.get("_old"):
                continue
            ranked = sorted(CODEX_FOLDERS, key=lambda a: counts[a], reverse=True)
            if counts[ranked[0]] == 0 or counts[ranked[0]] == counts[ranked[1]]:
                continue
            usage = self.totals.get(path)
            if not usage:
                continue
            r = result[ranked[0]] or {"input": 0, "cached": 0, "output": 0, "sources": 0}
            r["input"] += usage.get("input_tokens", 0) or 0
            r["cached"] += usage.get("cached_input_tokens", 0) or 0
            r["output"] += usage.get("output_tokens", 0) or 0
            r["sources"] += 1
            result[ranked[0]] = r
        return result


def tournament_start(claude: dict[str, ClaudeTokens]) -> dt.datetime:
    """When the Claude agents started, less ten minutes: older Codex rollouts are not the tournament's."""
    first = []
    for tokens in claude.values():
        for path in tokens.find():
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        stamp = json.loads(line).get("timestamp")
                        if stamp:
                            first.append(dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")))
                            break
            except (OSError, ValueError):
                continue
    if not first:
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=12)
    return min(first) - dt.timedelta(minutes=10)


# ---------------------------------------------------------------- collector + server

class Collector:
    def __init__(self, interval: float, since: dt.datetime | None):
        self.interval = interval
        self.claude = {name: ClaudeTokens(title) for name, title in CLAUDE_TITLES.items()}
        self.codex = CodexTokens(since or tournament_start(self.claude))
        self.lock = threading.Lock()
        self.snapshot = json.dumps({"updated": None, "agents": [], "errors": ["starting"]}).encode()

    def collect(self) -> dict:
        errors = []
        game = {"time_ms": None, "players": {}}
        try:
            game = game_scores()
        except Exception as e:  # noqa: BLE001 - shown on the panel, the loop goes on
            errors.append(f"game: {e}")
        tokens: dict[str, dict | None] = {}
        for name, t in self.claude.items():
            try:
                tokens[name] = t.update()
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name} tokens: {e}")
        try:
            tokens.update(self.codex.update())
        except Exception as e:  # noqa: BLE001
            errors.append(f"codex tokens: {e}")
        agents = []
        for a in AGENTS:
            agents.append({**a, "game": game["players"].get(a["name"]), "tokens": tokens.get(a["name"])})
        return {"updated": dt.datetime.now().strftime("%H:%M:%S"), "game_time_ms": game["time_ms"],
                "interval": self.interval, "agents": agents, "errors": errors}

    def loop(self):
        while True:
            started = time.monotonic()
            data = self.collect()
            with self.lock:
                self.snapshot = json.dumps(data).encode()
            for e in data["errors"]:
                print(f"{data['updated']} {e}", file=sys.stderr, flush=True)
            time.sleep(max(1.0, self.interval - (time.monotonic() - started)))


def serve(collector: Collector, port: int, key: str):
    page = HERE / "panel.html"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            path, _, query = self.path.partition("?")
            if parse_qs(query).get("key", [""])[0] != key:
                self.send_error(404)
                return
            if path == "/stats.json":
                with collector.lock:
                    body, kind = collector.snapshot, "application/json"
            elif path in ("/", "/index.html", "/panel.html"):
                body, kind = page.read_bytes(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=7690)
    ap.add_argument("--interval", type=float, default=15)
    ap.add_argument("--since", help="Codex rollouts from this UTC time on (ISO, default: Claude agents' start - 10 min)")
    ap.add_argument("--once", action="store_true", help="collect once, print the JSON and exit")
    args = ap.parse_args()
    if "ANNO1602_DIR" not in os.environ:
        sys.exit("ANNO1602_DIR is not set (o1602-tool needs the original's folder)")
    since = dt.datetime.fromisoformat(args.since.replace("Z", "+00:00")) if args.since else None
    collector = Collector(args.interval, since)
    if args.once:
        print(json.dumps(collector.collect(), indent=1))
        return
    threading.Thread(target=collector.loop, daemon=True).start()
    key = access_key()
    print(f"stats panel on http://127.0.0.1:{args.port}/?key={key} (every {args.interval:g} s)", flush=True)
    serve(collector, args.port, key)


if __name__ == "__main__":
    main()
