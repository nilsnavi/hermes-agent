#!/usr/bin/env python3
"""Hermes Aux Canary handler (Sprint 1.3.10 fixture source).

Reads config.json at startup; on SIGHUP (reload) re-reads it (same PID, NO
restart); on SIGTERM exits. Writes a health state file. No secrets, no env
values, no network.
"""
import json
import os
import signal
import time

BASE = "/home/hermes/.hermes/managed/canary-service"
CONFIG = os.path.join(BASE, "config.json")
STATE = os.path.join(BASE, "state.json")


def read_config():
    with open(CONFIG) as f:
        return json.load(f)


def write_state(gen, healthy):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"generation": gen, "healthy": healthy, "pid": os.getpid()}, f)
    os.replace(tmp, STATE)


def main():
    running = True
    gen = 0

    def on_term(*_a):
        nonlocal running
        running = False

    def on_hup(*_a):
        nonlocal gen
        gen += 1
        read_config()
        write_state(gen, True)

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGHUP, on_hup)

    read_config()
    write_state(gen, True)
    while running:
        time.sleep(1)
    os._exit(0)


if __name__ == "__main__":
    main()
