import requests
import time
import sys
import random

def poll_for_work():
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <url> <token>")

    url   = sys.argv[1]
    token = sys.argv[2]

    return requests.get(url + f"/poll_for_work?token={token}").json()

def do_work(work):
    print(f"Work packet received: {work}")

    # doing serious work, compiling stuff if needed, finding out paths, calling cutechess-cli!
    time.sleep(0.1)

    w = int(random.random() * (work["n_games_per_packet"] // 2))
    l = int(random.random() * (work["n_games_per_packet"] // 2))
    d = work["n_games_per_packet"] - w - l

    return w, d, l

def push_wdl(w, d, l):
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <url> <token>")

    url   = sys.argv[1]
    token = sys.argv[2]

    return requests.get(url + f"/push_wdl?w={w}&d={d}&l={l}&token={token}").json()

while True:
    work = poll_for_work()
    w, d, l = do_work(work)
    push_wdl(w, d, l)
