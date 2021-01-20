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

IS_WINDOWS    = platform.system() is "Windows"


def correct_path(path):
    if IS_WINDOWS:
        return path.replace("/","\\")
    else:
        return path.replace("\\", "/")


ROOT_PATH     = correct_path(os.path.dirname(os.path.abspath(__file__)))
ENGINE_FOLDER = correct_path(ROOT_PATH + "/engine/")
ENGINE_NAME   = "engine.exe" if IS_WINDOWS else "engine"
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
        print(f"[{t}] [LOG] {txt}")

    def check_directories(self):

        self.log("checking the folder structure")
        # make sure that /engine/ exists
        if os.path.isdir(ENGINE_FOLDER):
            self.log(f"Removing {ENGINE_FOLDER}")
            # if it already exists, make sure to clean the content of the folder
            if IS_WINDOWS:
                os.system(f"rmdir /S /Q {correct_path(ENGINE_FOLDER)}")
            else:
                os.system(f"rm -rf {ENGINE_FOLDER}")

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

        os.chdir(ENGINE_FOLDER)
        self.log(f"cloning branch {self.git_branch} from {self.git_repo}")
        sp.check_call(["git", "clone", "--depth", "1", self.git_repo, "-b", self.git_branch], stdout=sp.DEVNULL, stderr=sp.STDOUT)

        makefiles = [k for k in pathlib.Path('.').rglob("makefile")]
        if len(makefiles) < 1:
            self.log("Cannot find makefile in project")
        if len(makefiles) > 1:
            self.log("Found more than one makefile in project")

        self.log(f"Found {makefiles[0]}")
        os.chdir(os.path.dirname(makefiles[0]))

        # getting the compile command using make
        os.system("make --just-print > temp.txt")
        with open("temp.txt") as t:
            old_command = t.readline()
            print(old_command)
            # reading the makefile output out of temp.txt and replace the -o value

            new_command = re.sub(
                "-o(.*)?[-\n]",
                "-o " + correct_path((ENGINE_FOLDER + ENGINE_NAME)).replace('\\', '/'),
                old_command)

        # actually compiling the project with an adjusted commmand
        os.system(new_command + " > temp.txt")
        os.remove("temp.txt")

        # go back to the engine folder and remove the git stuff
        os.chdir(ENGINE_FOLDER)
        self.log("Removing cloned git repository")
        for path in os.listdir("."):
            if os.path.isdir(os.path.join(".", path)):
                if IS_WINDOWS:
                    os.system(f"rmdir /S /Q {correct_path(os.path.join('.', path))}")
                else:
                    os.system(f"rm -rf {correct_path(os.path.join('.', path))}")

        os.chdir(pwd)

    def run_benchmark(self):
        pwd = os.getcwd()
        os.chdir(ENGINE_FOLDER)

        print(os.path.exists(ENGINE_NAME))
        print(os.path.abspath(ENGINE_NAME))

        processes = []
        for i in range(self.threads):
            self.log("Running benchmark")
            process = sp.Popen([os.path.abspath(ENGINE_NAME),"bench"],stdout=sp.PIPE,shell=True)
            # print(process.args)
            # process.wait()
            # os.system("engine.exe bench")
            self.log("Finished benchmark")

        # for p in processes:
        #     p.wait()

        # p())for p in processes:
        #         #     while True:
        #         #         output = p.stdout.readline()
        #         #         if output == '' and p.poll() is not None:
        #         #             break
        #         #         if output:
        #         #             print(output.stri

        os.chdir(pwd)

    def build_cutechess_command(self):
        self.log("Building cutechess command")
        engine_args    = f"restart=off " \
                         f"cmd={ENGINE_FOLDER + ENGINE_NAME} " \
                         f"proto=uci " \
                         f"tc={self.tc} " \
                         f"book={self.book} " \
                         f"bookdepth={books[self.book]} "
        engine_1_add   = f"name=lower option.{self.relevant_option}={self.relevant_center-self.relevant_deviation} "
        engine_2_add   = f"name=upper option.{self.relevant_option}={self.relevant_center+self.relevant_deviation} "
        cutechess_args = "cutechess-cli " \
                         f"-fcp {engine_1_add}" \
                         f"-scp {engine_2_add}" \
                         f"-both {engine_args}" \
                         f"-concurrency {self.threads} " \
                         f"-draw 100 0 " \
                         f"-resign 5 10 " \
                         f"-games {self.games} " \
                         f"-pgnout {PGN_FOLDER}{time.time_ns()}.pgn " \
                         f"-repeat " \
                         f"-srand({random.randint(0, 100000000)}) "
        return cutechess_args


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
    "threads": 1
}
packet = {
    "games": 1000,
    "tc": "10+0.1",
    "book": 1,
    "options": {
        "Hash": 16,
        "Threads": 1
    }   ,
    "relevant_option": "Hash",
    "relevant_center": 16,
    "relevant_deviation":8,

    "git_repo": "https://github.com/Luecx/Koivisto.git",
    "git_branch": "master",

    "bench": 1,
    "base_speed": 2000000
}
client = Client(local, packet)

# client.download_and_compile_engine()
client.run_benchmark()
