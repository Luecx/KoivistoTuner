import signal
import requests
import time
import sys
import random
import os
import shutil
import datetime
import platform
import pathlib
import re
import subprocess as sp

IS_WINDOWS    = platform.system() == "Windows"


def correct_path(path):
    if IS_WINDOWS:
        return path.replace("/","\\")
    else:
        return path.replace("\\", "/")

def remove_dir(path):
    path = correct_path(path)
    if os.path.isdir(path):
        if IS_WINDOWS:
            os.system(f"rmdir /S /Q {path}")
        else:
            os.system(f"rm -rf {path}")

def engine_name(branch):
    return f"{branch}{'.exe' if IS_WINDOWS else ''}"

ROOT_PATH     = correct_path(os.path.dirname(os.path.abspath(__file__)))
ENGINE_FOLDER = correct_path(ROOT_PATH + "/engine/")
BOOK_FOLDER   = correct_path(ROOT_PATH + "/books/")
PGN_FOLDER    = correct_path(ROOT_PATH + "/pgn/")

SAVE_PGN_OUTPUT = True

books = {
    1: 8,
    2: 6,
    3: 16,
}


class Client:
    def __init__(self, options, packet):

        # options for the client itself
        self.threads = options["threads"]

        # amount of games played
        self.games   = packet["games"]
        self.tc      = packet["tc"]
        self.book    = packet["book"]

        # uci options as a dictionary which maps string to string for uci: setoption name x value y
        self.options = packet["options"]

        # uci option which shall be adjusted for this test.
        # Also contains the default value and the deviation.
        # A test will run with center + deviation against center - deviation
        self.relevant_option    = packet["relevant_option"]
        self.relevant_center    = packet["relevant_center"]
        self.relevant_deviation = packet["relevant_deviation"]

        # information for git, requires repo and branch name
        self.git_repo           = packet["git_repo"]
        self.git_branch         = packet["git_branch"]

        # information to adjust the tc
        self.base_speed         = packet["base_speed"]

        # information to check if the bench is correct
        self.bench              = packet["bench"]

    def log(self, txt):
        t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{t}] [LOG] {txt}", flush=True)

    def check_directories(self):

        self.log("checking the folder structure")
        # make sure that /engine/ exists
        if os.path.isdir(ENGINE_FOLDER):
            self.log(f"Removing {ENGINE_FOLDER}")
            # if it already exists, make sure to clean the content of the folder
            remove_dir(ENGINE_FOLDER)

        self.log(f"creating {ENGINE_FOLDER}")
        os.mkdir(ENGINE_FOLDER)

        # if the book folder does not exist yet, make sure to create it
        if not os.path.isdir(BOOK_FOLDER):
            os.mkdir(BOOK_FOLDER)

        # if the pgn folder does not exist yet, make sure to create it
        if not os.path.isdir(PGN_FOLDER):
            os.mkdir(PGN_FOLDER)

    def download_and_compile_engine(self):
        pwd = os.getcwd()

        self.check_directories()

        # create a temporary folder for cloning
        os.chdir(ROOT_PATH)
        remove_dir("temp")
        os.mkdir("temp")
        os.chdir("temp")

        # cloning
        self.log(f"cloning branch {self.git_branch} from {self.git_repo}")
        sp.check_call(["git", "clone", "--depth", "1", self.git_repo, "-b", self.git_branch], stdout=sp.DEVNULL, stderr=sp.STDOUT)

        # finding the makefile inside the git repo, throw a warning if no makefile was found
        makefiles = [os.path.abspath(k) for k in pathlib.Path('.').rglob("makefile")]
        if len(makefiles) < 1:
            self.log("Cannot find makefile in project")
            return False
        if len(makefiles) > 1:
            self.log("Found more than one makefile in project")
            return False

        # changing the directory to the directory of the makefile
        self.log(f"Found {makefiles[0]}")

        # getting the compile command using make
        os.chdir(os.path.dirname(makefiles[0]))
        p = sp.Popen(f"make -f {makefiles[0]} --just-print", shell=True, stdout=sp.PIPE)
        p.wait()
        old_command = p.stdout.readline().decode("UTF-8")
        new_command = re.sub(
            "-o(.*)?[-\n]",
            "-o " + correct_path((ENGINE_FOLDER + engine_name(self.git_branch))).replace('\\', '/'),
            old_command)

        # actually compiling the project with an adjusted commmand
        self.log(f"Compiling")
        sp.check_call(new_command, shell=True, stdout=sp.DEVNULL, stderr=sp.STDOUT)

        # go back to the engine folder and remove the git stuff
        os.chdir(ROOT_PATH)
        self.log("Removing cloned git repository")
        remove_dir("temp")

        os.chdir(pwd)
        return True

    def run_benchmark(self):
        pwd = os.getcwd()
        os.chdir(ENGINE_FOLDER)

        self.log("Starting benchmark")
        processes = []
        for i in range(self.threads):
            processes.append(sp.Popen(engine_name(self.git_branch) + " bench", shell=True, stdout=sp.PIPE))

        for p in processes:
            p.wait()

        nodes = 0
        nps   = 0

        for p in processes:
            for line in p.stdout:
                line = line.decode("utf-8")

                if "OVERALL" in line:
                    while "  " in line:
                        line = line.replace("  ", " ")

                    temp_nodes  = int(line.split(" ")[1])
                    temp_nps    = int(line.split(" ")[3])

                    if nodes != 0 and temp_nodes != nodes:
                        self.log("Non deterministic Bench!")
                        return False

                    nodes = temp_nodes
                    nps   = temp_nps

        os.chdir(pwd)
        self.log("Finished benchmark")

        if nodes != self.bench:
            self.log(f"Wrong Bench. Expected {self.bench}, got {nodes}")
            return False

        return nps

    def build_cutechess_command(self):
        self.log("Building cutechess command")
        engine_args    = f"restart=off " \
                         f"cmd={ENGINE_FOLDER + engine_name(self.git_branch)} " \
                         f"proto=uci " \
                         f"tc={self.tc} " \
                         f"book={self.book} " \
                         f"bookdepth={books[self.book]} "
        engine_1_add   = f"name=lower option.{self.relevant_option}={self.relevant_center-self.relevant_deviation} "
        engine_2_add   = f"name=upper option.{self.relevant_option}={self.relevant_center+self.relevant_deviation} "
        cutechess_args = f"cutechess-cli{'.exe' if IS_WINDOWS else ''} " \
                         f"-engine {engine_1_add}" \
                         f"-engine {engine_2_add}" \
                         f"-each {engine_args}" \
                         f"-concurrency {self.threads} " \
                         f"-games {self.games} " \
                         f"-pgnout {PGN_FOLDER}{time.time_ns()}.pgn " \
                         f"-repeat " \
                         f"-srand {random.randint(0, 100000000)} "
        return cutechess_args

    def adjust_tc(self, nps):
        scalar = self.base_speed / float(nps)

        moves_to_go     = None
        time            = None
        increment       = None
        tc              = self.tc

        if "/" in self.tc:
            split       = tc.split("/")
            moves_to_go = int(split[0])
            tc          =     split[1]


        if "+" in self.tc:
            split       = tc.split("+")
            time        = float(split[0]) * scalar
            increment   = float(split[1]) * scalar

        else:
            time        = float(tc) * scalar

        self.tc         = f"{moves_to_go + '/' if moves_to_go is not None else ''}" \
                          f"{round(time,3)}" \
                          f"{'+' + str(round(increment,3)) if increment is not None else ''}"

        self.log(f"Adjust tc: {self.tc}")

        return self.tc

    def iterate(self):
        if not self.download_and_compile_engine():
            exit(-1)

        nps = self.run_benchmark()
        if not nps:
            exit(-1)

        self.adjust_tc(nps)
        self.log("starting cutechess...")
        cutechess_command = self.build_cutechess_command()
        try:
            p = sp.Popen(cutechess_command, shell=True).wait()
        except KeyboardInterrupt:
            p.send_signal(signal.SIGINT)



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

# while True:
#     work = poll_for_work()
#     w, d, l = do_work(work)
#     push_wdl(w, d, l)

local = {
    "threads": 16
}
packet = {
    "games": 1000,
    "tc": "10+0.1",
    "book": 1,
    "options": {
        "Hash": 16,
        "Threads": 1
    },
    "relevant_option": "Hash",
    "relevant_center": 16,
    "relevant_deviation": 8,

    "git_repo": "https://github.com/Luecx/Koivisto.git",
    "git_branch": "master",

    "bench": 6853435,
    "base_speed": 2000000
}
client = Client(local, packet)

client.iterate()