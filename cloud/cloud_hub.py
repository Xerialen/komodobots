#!/usr/bin/env python3
"""Cloud Hub - a trimmed port of Xerialen/local-hub for the komodobots AWS box.

Shows ONLY three things (nothing else):
  1. Cloud servers        - live `quakestat -json` of the standing mvdsv (28501-28504)
  2. Demos recorded online - MVDs the cloud servers wrote to ~/nquakesv/ktx/demos
  3. Successful attempts   - committed tricks/<map>/<route>__<runid>.mvd from the repo

It also serves the built botlab dashboard under /botlab/ and the demo files under
/demos/, so any listed demo plays in-browser via the dashboard's FTE pane
(/botlab/panes/demo.html?demo=...&map=...).

Stdlib only. Binds loopback; reached over the Cloudflare tunnel
(komodolab.xerious.org), which is IP-independent and so survives the box's
stop/start public-IP changes.

Usage: cloud_hub.py [bind] [port]   (defaults 127.0.0.1 8099; env HUB_BIND/HUB_PORT)
"""
from __future__ import annotations

import logging
import http.server
import json
import os
import re
import subprocess
import sys
import urllib.parse


LOGGER = logging.getLogger(__name__)
HOME = os.path.expanduser("~")
HUB_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("KOMODO_REPO", os.path.join(HOME, "projects/komodobots"))
ONLINE_DEMOS_DIR = os.environ.get("ONLINE_DEMOS_DIR", os.path.join(HOME, "nquakesv/ktx/demos"))
ATTEMPTS_DIR = os.path.join(REPO, "tricks")
DASH_DIST = os.path.join(REPO, "lab", "dashboard", "dist")
# Generated ledgers (4v4 validation, casting) land in the dashboard's public
# data dir; the hub serves them under /demos/records/ with a fall-back to the
# committed *.example.json so the dashboard renders before any real run writes one.
RECORDS_DIR = os.environ.get("RECORDS_DIR", os.path.join(REPO, "lab", "dashboard", "public", "data"))
MAPS_DIR = os.path.join(HOME, "nquakesv", "qw", "maps")
SERVER_PORTS = [int(p) for p in os.environ.get("HUB_SERVER_PORTS", "28501,28502,28503,28504").split(",")]

BIND = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HUB_BIND", "127.0.0.1")
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.environ.get("HUB_PORT", "8099"))

_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")
_KNOWN_MAPS = ("frobodm2", "phantombase", "aerowalk", "ztricks", "dm3", "dm2", "e1m2", "e2m2")


def _guess_map(name: str) -> str:
    low = name.lower()
    for m in _KNOWN_MAPS:
        if m in low:
            return m
    return "dm3"


def _safe_child(base: str, name: str):
    """Resolve URL-decoded `name` strictly inside `base`; None if it escapes or is unsafe.
    QW demo names contain []()@ etc. (e.g. `4on4_leap[dm3]20260615-2036.mvd`), so we do NOT
    char-allowlist; the realpath-within-base check is the security boundary, plus a guard
    against path separators / NULs."""
    name = urllib.parse.unquote(name)
    if not name or "/" in name or "\\" in name or "\x00" in name:
        return None
    full = os.path.realpath(os.path.join(base, name))
    root = os.path.realpath(base)
    return full if (full == root or full.startswith(root + os.sep)) else None


def servers_json():
    args = ["quakestat", "-json", "-maxsim", "16"]
    for p in SERVER_PORTS:
        args += ["-qws", f"127.0.0.1:{p}"]
    by_port = {}
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=6)
        for d in json.loads(out.stdout or "[]"):
            addr = d.get("address", "")
            if ":" in addr:
                try:
                    by_port[int(addr.rsplit(":", 1)[-1])] = d
                except ValueError:
                    pass
    except Exception:
        pass
    rows = []
    for p in SERVER_PORTS:
        d = by_port.get(p) or {}
        rows.append({
            "port": p,
            "online": d.get("status") == "online",
            "name": d.get("name") or f"server:{p}",
            "map": d.get("map"),
            "players": d.get("numplayers"),
            "maxplayers": d.get("maxplayers"),
            "spectators": d.get("numspectators"),
        })
    return rows


def online_demos_json():
    items = []
    try:
        names = os.listdir(ONLINE_DEMOS_DIR)
    except FileNotFoundError:
        return items
    for n in names:
        if not n.lower().endswith((".mvd", ".qwd", ".dem")):
            continue
        try:
            st = os.stat(os.path.join(ONLINE_DEMOS_DIR, n))
        except OSError:
            continue
        items.append({
            "name": n,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "map": _guess_map(n),
            "url": "/demos/online/" + urllib.parse.quote(n),
        })
    items.sort(key=lambda d: d["mtime"], reverse=True)
    return items


def attempts_json():
    items = []
    if not os.path.isdir(ATTEMPTS_DIR):
        return items
    for mp in sorted(os.listdir(ATTEMPTS_DIR)):
        md = os.path.join(ATTEMPTS_DIR, mp)
        if not os.path.isdir(md):
            continue
        for n in sorted(os.listdir(md)):
            if not n.lower().endswith((".mvd", ".qwd")):
                continue
            if "__" in n:
                route, rest = n.split("__", 1)
                runid = rest.rsplit(".", 1)[0]
            else:
                route, runid = n.rsplit(".", 1)[0], ""
            items.append({
                "map": mp,
                "route": route,
                "runid": runid,
                "name": n,
                "url": f"/demos/attempts/{urllib.parse.quote(mp)}/" + urllib.parse.quote(n),
            })
    return items


class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = "cloudhub/1.0"
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".wasm": "application/wasm", ".mvd": "application/octet-stream",
                      ".qwd": "application/octet-stream", ".dem": "application/octet-stream"}

    def log_message(self, fmt, *args):  # quieter
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _file(self, path):
        if not path or not os.path.isfile(path):
            self.send_error(404)
            return
        try:
            data = open(path, "rb").read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _under(self, base, rel):
        rel = urllib.parse.unquote(rel)
        full = os.path.realpath(os.path.join(base, rel))
        root = os.path.realpath(base)
        if not (full == root or full.startswith(root + os.sep)):
            self.send_error(403)
            return
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        self._file(full)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file(os.path.join(HUB_DIR, "index.html"))
        if path == "/api/servers":
            return self._json(servers_json())
        if path == "/api/online-demos":
            return self._json(online_demos_json())
        if path == "/api/attempts":
            return self._json(attempts_json())
        if path == "/healthz":
            return self._json({"ok": True})
        if path.startswith("/demos/online/"):
            return self._file(_safe_child(ONLINE_DEMOS_DIR, path[len("/demos/online/"):]))
        m = re.match(r"^/demos/attempts/([^/]+)/(.+)$", path)
        if m:
            mapdir = _safe_child(ATTEMPTS_DIR, m.group(1))
            target = _safe_child(mapdir, m.group(2)) if mapdir and os.path.isdir(mapdir) else None
            return self._file(target)
        if path.startswith("/demos/records/"):
            name = path[len("/demos/records/"):]
            target = _safe_child(RECORDS_DIR, name)
            if not (target and os.path.isfile(target)) and name.endswith(".json"):
                # Fall back to the committed example ledger so the dashboard
                # renders before any real run has written records.
                target = _safe_child(RECORDS_DIR, name[:-5] + ".example.json")
            return self._file(target)
        if path == "/botlab":
            self.send_response(302)
            self.send_header("Location", "/botlab/")
            self.end_headers()
            return
        if path.startswith("/botlab/"):
            return self._under(DASH_DIST, path[len("/botlab/"):] or "index.html")
        if path.startswith("/maps/"):
            return self._under(MAPS_DIR, path[len("/maps/"):])
        self.send_error(404)


if __name__ == "__main__":
    httpd = http.server.ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"cloud-hub on {BIND}:{PORT}  repo={REPO}  online_demos={ONLINE_DEMOS_DIR}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
