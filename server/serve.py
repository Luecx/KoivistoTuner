import json

@app.route('/poll_for_work')
def poll_for_work():
    token = request.form.get("token", None)

    config = json.loads(open("config.json").read())
    status = json.loads(open("status.json").read())
    if token not in config["tokens"]:
        return json.dumps({"err": "AUTH_DENIED"})
    
    packet = config["static_packet"]
    packet["value"] = status["value"]
    return json.dumps()

@app.route('/push_wdl')
def push_wdl():
    token = request.form.get("token", '')
    config = json.loads(open("config.json").read())
    status = json.loads(open("status.json").read())
    if token not in config["tokens"]:
        return json.dumps({"err": "AUTH_DENIED"})

    status["w"] += request.form.get("w", None)
    status["d"] += request.form.get("d", None)
    status["l"] += request.form.get("l", None)

    if status["w"] + status["d"] + status["l"] > config["n_games_per_iteration"]:
        status["w"] = 0
        status["d"] = 0
        status["l"] = 0

        right_direction = status["w"] > status["l"]
        delta = status["delta"] * 1 if right_direction else status["delta"] * -1
        new_value = status["value"] + delta

        open("log.log", "a").write(f'value {status["value"]} new_value {new_value} w d l {status["w"]} + {status["d"]} + {status["l"]}\n')
        status["value"] = new_value

    open("status.json", "w").write(json.dumps(status))