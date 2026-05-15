"""Tiny sysinfo HTTP server — started as a daemon thread by the worker.

GET http://<host>:9101/  →  JSON { hostname, cpu, mem, cpu_temp, fans }
"""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from socket import gethostname
from threading import Thread

import psutil

PORT = 9101

_prev_cpu = None


def _hwmon():
    cpu_temp = None
    fans = []
    try:
        for h in os.listdir("/sys/class/hwmon"):
            d = f"/sys/class/hwmon/{h}"
            try:
                name = open(f"{d}/name").read().strip()
            except OSError:
                continue
            if name == "coretemp":
                try:
                    cpu_temp = round(int(open(f"{d}/temp1_input").read()) / 1000)
                except OSError:
                    pass
            fan_drivers = {"dell_smm", "nct6775", "it87", "f71882fg"}
            if name in fan_drivers or any(name.startswith(p) for p in ("nct", "it8", "f71")):
                for i in range(1, 5):
                    try:
                        v = int(open(f"{d}/fan{i}_input").read())
                        if v > 0:
                            fans.append(v)
                    except OSError:
                        pass
    except OSError:
        pass
    return cpu_temp, fans


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        cpu_temp, fans = _hwmon()
        data = {
            "hostname": gethostname(),
            "cpu":      psutil.cpu_percent(),
            "mem":      psutil.virtual_memory().percent,
            "cpu_temp": cpu_temp,
            "fans":     fans,
        }
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start():
    """Start the sysinfo HTTP server in a daemon thread. Non-blocking."""
    psutil.cpu_percent()  # prime the rolling interval

    def _serve():
        try:
            HTTPServer(("", PORT), _Handler).serve_forever()
        except Exception:
            pass  # port already in use or other non-fatal error

    Thread(target=_serve, daemon=True, name="sysinfo-http").start()
