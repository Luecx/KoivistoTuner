import datetime
import os
import random
import shutil
import sys
import math
import subprocess as sp
import json
from threading import Thread, Lock
import platform

import numpy as np

IS_WINDOWS              = platform.system() == "Windows"
ROOT_FOLDER             = os.path.dirname(os.path.dirname(__file__))
CONFIG_FILE             = "config.json"
GAME_RESULTS            = "results.csv"
VARIABLES_FILE          = "variables.csv"
HISTORY_FILE            = "history.csv"
BOOK_FOLDER             = os.path.join(ROOT_FOLDER,"books")
SCRIPT_FOLDER           = os.path.dirname(__file__)
UCI_SETOPTION_FILE      = "VariableFilePath"  # relevant for setoption name [x] value variables.csv
MAX_GAMES_PER_HANDLER   = 100000



def synchronized(func):
    func.__lock__ = Lock()

    def synced_func(*args, **kws):
        with func.__lock__:
            return func(*args, **kws)

    return synced_func

def fix_path(path):
    path = path.replace("\\", "/")
    return path

@synchronized
def error(txt, ex=True):
    t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{t}] [ERR] {txt}", flush=True, file=sys.stderr)
    if ex:
        exit(-1)

@synchronized
def log(txt):
    t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{t}] [LOG] {txt}", flush=True)

class Variables:
    def __init__(self, variables):
        self.names  = []
        self.values = np.asfarray([])
        for key in variables:
            self.add(key, variables[key])

    def add(self, key, value):
        self.names += [key]
        self.values =  np.append(self.values, value)

    def copy(self):
        var = Variables({})
        var.names = self.names[:]
        var.values = np.copy(self.values)
        return var

    def mask(self, count):
        variables_to_change = random.sample(range(0,len(self.values)), count)
        mask = np.asfarray([1 if i in variables_to_change else 0 for i in range(len(self.values)) ])
        return np.asfarray(mask)

    def variation(self, count, strength):
        mask = self.mask(count)
        direction = np.random.normal(0, 1, len(mask))

        direction = direction * mask
        direction = direction / np.linalg.norm(direction)

        return np.abs(self.values * direction * strength)

    def two_versions(self, variation):
        vers_1 = self.copy()
        vers_2 = self.copy()

        vers_1.values += variation
        vers_2.values -= variation
        return vers_1, vers_2

    @synchronized
    def adjust(self, variation, result, strength):
        self.values = self.values + variation * result * strength

    def cutechess_command(self):
        return " ".join(f"option.{self.names[k]}={round(self.values[k])}" for k in range(len(self.names)))

    def __str__(self):
        return dict(zip(self.names, self.values)).__str__()

class Config:
    def __init__(self):
        # throw an error if there is no config file
        if not os.path.isfile(CONFIG_FILE):
            error(f"No {CONFIG_FILE} found")

        # open the config file
        with open(CONFIG_FILE) as f:
            data = json.load(f)

        # check the fields of the file
        # track if an error has occured. if so we will exit once all fields have been checked
        ex = False
        for relevant in ["batch"        ,"delta"        ,"apply_factor" ,"n_iter_adjust"    ,"n_threads",
                         "variables"    ,"uci_options"  ,"tc"           ,"engine"           ,"book"]:
            # if a field is missing, set ex to true and print an error
            if relevant not in data:
                ex = True
                # dont exit on this error but after this loop has finished
                error(f"No {relevant} in {CONFIG_FILE}", ex=False)
        if ex:
            error(f"{CONFIG_FILE} is not complete")

        # retrieve the data
        self.batch          = int      (data["batch"        ])
        self.delta          = float    (data["delta"        ])
        self.apply_factor   = float    (data["apply_factor" ])
        self.n_iter_adjust  = int      (data["n_iter_adjust"])
        self.n_threads      = int      (data["n_threads"    ])
        self.variables      = Variables(data["variables"    ])
        self.uci_options    =           data["uci_options"  ]
        self.tc             =           data["tc"           ]
        self.engine         =           data["engine"       ]
        self.book           =           data["book"         ]


class Handler:
    def __init__(self, id, config):
        self.id         = id
        self.config     = config

        self.mainloop()

    def create_versions(self):
        # create the variation (change in each variable)
        variation = config.variables.variation(config.n_iter_adjust, config.delta)
        # create two different versions where the variation is applied to the base values
        v1,v2     = config.variables.two_versions(variation)
        # return
        return variation, v1,v2

    def mainloop(self):
        while(True):
            # retrieve a random set of values which are changed as well as two variable sets
            # which uses the random set of values in both direction
            var, v1, v2         = self.create_versions()
            # generate the cutechess command based on the variables
            command             = self.create_cutechess_command(v1,v2)
            # run the match
            result              = self.run_match(command)
            # # transform the result into [-1,1]
            transformed_result  = self.transform_match_result(result)
            # adjust the variables
            config.variables.adjust(var, transformed_result, config.apply_factor)
            # print some output

            optimum_string = "\n".join([f"{config.variables.names[i]:>16} = {config.variables.values[i] : <16}"
                                          for i in range(len(config.variables.values))])
            log(f"[#{self.id:>2}] Finished Match. Score: {result:<4}")
            log(f"[#{self.id:>2}] Current optimum: \n{optimum_string}")

    def transform_match_result(self, result):
        # result is between 0 and 1 (0 if the engine2 won, 1 if engine1 won)
        # transform this into a normalised version between [-1,1]
        normalised = result * 2 - 1
        # use a sigmoid function which clamps between -1 and 1
        transformed = 2 / (1 + math.exp(-normalised * 8)) - 1
        # return
        return transformed

    def run_match(self, command):
        popen = sp.Popen(command, stdout=sp.PIPE, universal_newlines=True)

        # count wins for engine 1 and engine 2 as well as draws
        en1_wins = 0
        en2_wins = 0
        draws    = 0

        # get the output of cutechess
        for stdout_line in iter(popen.stdout.readline, ""):
            # check if a game has finished
            if "Finished game" in stdout_line:
                # read the result of the finished game
                result = stdout_line.split(":")[1].strip().split()[0]
                # engine 1 won
                if result == '1-0':
                    en1_wins += 1
                # engine 2 won
                elif result == '0-1':
                    en2_wins += 1
                # draw
                else:
                    draws += 1
        # close the stream
        popen.stdout.close()
        # check for errors
        return_code = popen.wait()
        if return_code:
            raise sp.CalledProcessError(return_code, command)

        # return score for white (wins + draws/2) / n_games
        return (en1_wins + draws / 2) / (en1_wins + en2_wins + draws)

    def create_cutechess_command(self, v1, v2):
        engine_args   = f"restart=off " \
                        f"cmd={config.engine} " \
                        f"proto=uci " \
                        f"tc={config.tc} "
        for option in self.config.uci_options:
            engine_args += f"option.{option}={self.config.uci_options[option]} "
        engine_1_add  = f"name=en1 {v1.cutechess_command()} "
        engine_2_add  = f"name=en2 {v2.cutechess_command()} "
        log(engine_1_add)
        log(engine_2_add)
        cutechess_args = f"cutechess-cli{'.exe' if IS_WINDOWS else ''} " \
                         f"-engine {engine_1_add}" \
                         f"-engine {engine_2_add}" \
                         f"-each {engine_args}" \
                         f"-openings file={fix_path(os.path.join(BOOK_FOLDER,config.book))} order=random " \
                         f"-concurrency {1} " \
                         f"-games {config.batch} " \
                         f"-wait 0 " \
                         f"-repeat " \
                         f"-srand {random.randint(0, 100000000)} "
        return cutechess_args







#-----------------------------------------------------------------------------------------------------------------------
#-----------------------------------------------------------------------------------------------------------------------
#-----------------------------------------------------------------------------------------------------------------------

def start_handler(id, manager):
    Handler(id, manager)

config = Config()

for i in range(config.n_threads):
    thread = Thread(target=start_handler, args=(i,  config))
    thread.start()


