import json
from flask import Flask, request
app = Flask(__name__)

@app.route('/poll_for_work')
def poll_for_work():
    token = request.args.get("token", None)

    config = json.loads(open("config.json").read())
    status = json.loads(open("status.json").read())
    if token not in config["tokens"]:
        return json.dumps({"err": "AUTH_DENIED"})
    
    packet = config["static_packet"]
    packet["value"] = status["value"]
    return json.dumps(packet)

@app.route('/push_wdl')
def push_wdl():
    token = request.args.get("token", '')
    config = json.loads(open("config.json").read())
    status = json.loads(open("status.json").read())
    if token not in config["tokens"]:
        return json.dumps({"err": "AUTH_DENIED"})

    status["w"] += int(request.args.get("w", None))
    status["d"] += int(request.args.get("d", None))
    status["l"] += int(request.args.get("l", None))

    if status["w"] + status["d"] + status["l"] > config["static_packet"]["n_games_per_iteration"]:
        right_direction = status["w"] > status["l"]
        status["delta"] = status["delta"] * 1 if right_direction else status["delta"] * -1
        new_value = status["value"] + status["delta"]

        open("log.log", "a").write(f'value {status["value"]} new_value {new_value} w d l {status["w"]} + {status["d"]} + {status["l"]}\n')

        status["w"] = 0
        status["d"] = 0
        status["l"] = 0

        status["value"] = new_value

    open("status.json", "w").write(json.dumps(status))
    return json.dumps({"status": "OK"})