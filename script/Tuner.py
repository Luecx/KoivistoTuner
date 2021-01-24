import datetime
import os
import random
import shutil
import sys
import subprocess as sp
import json
from threading import Thread
import platform

import numpy as np

IS_WINDOWS              = platform.system() == "Windows"
ROOT_FOLDER             = os.path.dirname(os.path.dirname(__file__))
CONFIG_FILE             = "config.json"
VARIABLES_FILE          = "variables.csv"
BOOK_FOLDER             = os.path.join(ROOT_FOLDER,"books")
SCRIPT_FOLDER           = os.path.dirname(__file__)
UCI_SETOPTION_FILE      = "VariableFilePath"  # relevant for setoption name [x] value variables.csv
MAX_GAMES_PER_HANDLER   = 10


def fix_path(path):
    path = path.replace("\\", "/")
    return path

def error(txt, ex=True):
    t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{t}] [ERR] {txt}", flush=True, file=sys.stderr)
    if ex:
        exit(-1)


def log(txt):
    t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{t}] [LOG] {txt}", flush=True)


def sample(n, n_max):
    k = list(range(n_max))
    out = []
    for i in range(n):
        index = random.randint(0, len(k)-1)
        out += [k.pop(index)]
    return out


class Config:
    def __init__(self):
        if not os.path.isfile(CONFIG_FILE):
            error(f"No {CONFIG_FILE} found")

        with open(CONFIG_FILE) as f:
            data = json.load(f)

        ex = False
        for relevant in ["batch", "delta", "apply_factor", "n_iter_adjust", "n_threads", "variables", "uci_options", "tc",
                         "engine", "book"]:
            if relevant not in data:
                ex = True
                error(f"No {relevant} in {CONFIG_FILE}", ex=False)
        if ex:
            error(f"{CONFIG_FILE} is not complete")

        self.batch          = int(data["batch"])
        self.delta          = float(data["delta"])
        self.apply_factor   = float(data["apply_factor"])
        self.n_iter_adjust  = int(data["n_iter_adjust"])
        self.n_threads      = int(data["n_threads"])
        self.variables      = data["variables"]
        self.uci_options    = data["uci_options"]
        self.tc             = data["tc"]
        self.engine         = data["engine"]
        self.book           = data["book"]


class Manager:

    def __init__(self, config):
        self.config    = config
        self.variables = config.variables
        self.factors = [0] * config.n_threads

    def process_result(self, handler, result):
        id = handler.id
        # check if the value has been adjusted
        i = 0

        log(f"Processing batch result of handler #{id} result={result}")

        for name in self.variables:
            self.variables[name] += self.variables[name] * self.factors[id][i] * self.config.apply_factor * result
            i += 1

        self.assign_task(handler)
        self.output_variables()

    def output_variables(self):
        with open(VARIABLES_FILE, 'w+') as f:
            for var in self.variables:
                f.write(f"{var}:{self.variables[var]},\n")

    def assign_task(self, handler):
        id = handler.id

        log(f"Assigning batch task to handler #{id}")

        # the indices which shall be adjusted as well as their adjustments
        sam = sample(config.n_iter_adjust, len(self.variables))
        factors = np.array(np.zeros((len(self.variables),)))

        # computing the factors
        for c in range(len(self.variables)):
            if c in sam:
                factors[c] = random.gauss(0, 1)

        # # normalising the values
        factors /= np.linalg.norm(factors)
        factors = np.multiply(factors, config.delta)

        self.factors[id] = factors

        # writing to the given handler
        with open(f"{id}/en1_{VARIABLES_FILE}", 'w+') as f:
            c = 0
            for var in self.variables:
                f.write(f"{var} {int(config.variables[var] * (1 + factors[c]))},\n")
                c += 1

        # writing to the given handler
        with open(f"{id}/en2_{VARIABLES_FILE}", 'w+') as f:
            c = 0
            for var in self.variables:
                f.write(f"{var} {int(config.variables[var] * (1 - factors[c]))},\n")
                c += 1


class Handler:
    def __init__(self, config, manager, id):
        self.config = config
        self.manager = manager
        self.id = id

        log(f"creating directory {id}")
        if os.path.isdir(f"{id}"):
            shutil.rmtree(f"{id}")
        os.mkdir(f"{id}")
        self.manager.assign_task(self)

    def start_tournament(self):
        command = self.create_cutechess_command()
        popen = sp.Popen(command, stdout=sp.PIPE, universal_newlines=True)

        games_of_batch = 0
        en1_wins = 0
        en2_wins = 0

        for stdout_line in iter(popen.stdout.readline, ""):
            if "Finished game" in stdout_line:
                result = stdout_line.split(":")[1].strip().split()[0]

                games_of_batch += 1
                if result == '1-0':
                    en1_wins += 1
                if result == '0-1':
                    en2_wins += 1
                if games_of_batch % config.batch == 0:
                    if en1_wins > en2_wins:
                        self.report_result(1)
                    if en1_wins < en2_wins:
                        self.report_result(-1)
                    if en1_wins == en2_wins:
                        self.report_result(0)

                    games_of_batch = 0
                    en1_wins = 0
                    en2_wins = 0

        popen.stdout.close()
        return_code = popen.wait()
        if return_code:
            raise sp.CalledProcessError(return_code, command)

    def report_result(self, result):
        manager.process_result(self, result)

    def create_cutechess_command(self):
        log("Building cutechess command")
        engine_args = f"restart=off " \
                      f"cmd={config.engine} " \
                      f"proto=uci " \
                      f"tc={config.tc} "
        for option in self.config.uci_options:
            engine_args += f"option.{option}={self.config.uci_options[option]} "
        engine_1_add = f"name=en1 option.{UCI_SETOPTION_FILE}={fix_path(os.path.join(str(self.id), 'en1_' + VARIABLES_FILE))} "
        engine_2_add = f"name=en2 option.{UCI_SETOPTION_FILE}={fix_path(os.path.join(str(self.id), 'en2_' + VARIABLES_FILE))} "
        cutechess_args = f"cutechess-cli{'.exe' if IS_WINDOWS else ''} " \
                         f"-engine {engine_1_add}" \
                         f"-engine {engine_2_add}" \
                         f"-each {engine_args}" \
                         f"-openings file={fix_path(os.path.join(BOOK_FOLDER,config.book))} order=random " \
                         f"-concurrency {1} " \
                         f"-games {MAX_GAMES_PER_HANDLER} " \
                         f"-wait 5 " \
                         f"-repeat " \
                         f"-srand {random.randint(0, 100000000)} "
        return cutechess_args


def start_handler(id, config, manager):
    handler = Handler(config, manager, id)
    handler.start_tournament()


config  = Config()
manager = Manager(config)

for i in range(config.n_threads):
    thread = Thread(target=start_handler, args=(i, config, manager))
    thread.start()
