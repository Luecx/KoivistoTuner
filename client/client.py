####################################################################################################
#                                                                                                  #
#                                     Koivisto UCI Chess engine                                    #
#                           by. Kim Kahre, Finn Eggers and Eugenio Bruno                           #
#                                                                                                  #
#                 Koivisto is free software: you can redistribute it and/or modify                 #
#               it under the terms of the GNU General Public License as published by               #
#                 the Free Software Foundation, either version 3 of the License, or                #
#                                (at your option) any later version.                               #
#                    Koivisto is distributed in the hope that it will be useful,                   #
#                  but WITHOUT ANY WARRANTY; without even the implied warranty of                  #
#                   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the                  #
#                           GNU General Public License for more details.                           #
#                 You should have received a copy of the GNU General Public License                #
#                 along with Koivisto.  If not, see <http://www.gnu.org/licenses/>.                #
#                                                                                                  #
####################################################################################################
import argparse
import signal
import requests
import time
import sys
import random
import os
import datetime
import platform
import pathlib
import re
import subprocess as sp

IS_WINDOWS = platform.system() == "Windows"
def correct_path(path):
    if IS_WINDOWS:
        return path.replace("/", "\\")
    else:
        return path.replace("\\", "/")

# some paths
ROOT_PATH           = correct_path(os.path.dirname(os.path.abspath(__file__)))
ENGINE_FOLDER       = correct_path(ROOT_PATH + "/engine/")
BOOK_FOLDER         = correct_path(ROOT_PATH + "/books/")
PGN_FOLDER          = correct_path(ROOT_PATH + "/pgn/")

# true to save pgn output
SAVE_PGN_OUTPUT = True

# books
books = [
    "2moves_v1.pgn",
    "3moves_FRC.pgn",
    "4moves_noob.pgn",
    "8moves_v3.pgn",
]


class Client:
    def __init__(self, packet, args):

        # options for the client itself
        self.threads = args.T
        self.url     = args.U
        self.token   = args.P

        # amount of games played
        self.games = packet["games"]
        self.tc = packet["tc"]
        self.book = packet["book"]

        # uci options as a dictionary which maps string to string for uci: setoption name x value y
        self.options = packet["options"]

        # uci option which shall be adjusted for this test.
        # Also contains the default value and the deviation.
        # A test will run with center + deviation against center - deviation
        self.relevant_option = packet["relevant_option"]
        self.relevant_center = packet["value"]
        self.relevant_deviation = packet["relevant_deviation"]

        # information for git, requires repo and branch name
        self.git_repo = packet["git_repo"]
        self.git_branch = packet["git_branch"]

        # information to adjust the tc
        self.base_speed = packet["base_speed"]

        # information to check if the bench is correct
        self.bench = packet["bench"]

    def log(self, txt):
        t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{t}] [LOG] {txt}", flush=True)

    def check_directories(self):

        self.log("checking the folder structure")
        # make sure that /engine/ exists
        if os.path.isdir(ENGINE_FOLDER):
            self.log(f"Removing {ENGINE_FOLDER}")
            # if it already exists, make sure to clean the content of the folder
            self.remove_dir(ENGINE_FOLDER)

        self.log(f"creating {ENGINE_FOLDER}")
        os.mkdir(ENGINE_FOLDER)

        # if the pgn folder does not exist yet, make sure to create it
        if not os.path.isdir(PGN_FOLDER):
            os.mkdir(PGN_FOLDER)

    def check_books(self):

        pwd = os.getcwd()
        os.chdir(ROOT_PATH)

        # if the book folder does not exist yet, make sure to create it
        if not os.path.isdir(BOOK_FOLDER):
            self.log(f"creating {BOOK_FOLDER}")
            os.mkdir(BOOK_FOLDER)

        for book_name in books:
            r = requests.get(self.url + f"/static/books/{book_name}")
            binary_data = r.content
            with open(f"books/{book_name}", "wb") as file_handle:
                file_handle.write(binary_data)

        os.chdir(pwd)

    def download_and_compile_engine(self):
        pwd = os.getcwd()

        self.check_directories()
        self.check_books()

        # create a temporary folder for cloning
        os.chdir(ROOT_PATH)
        self.remove_dir("temp")
        os.mkdir("temp")
        os.chdir("temp")

        # cloning
        self.log(f"cloning branch {self.git_branch} from {self.git_repo}")
        sp.check_call(["git", "clone", "--depth", "1", self.git_repo, "-b", self.git_branch], stdout=sp.DEVNULL,
                      stderr=sp.STDOUT)

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
            "-o " + correct_path((ENGINE_FOLDER + self.engine_name(self.git_branch))).replace('\\', '/'),
            old_command)

        # actually compiling the project with an adjusted commmand
        self.log(f"Compiling")
        sp.check_call(new_command, shell=True, stdout=sp.DEVNULL, stderr=sp.STDOUT)

        # go back to the engine folder and remove the git stuff
        os.chdir(ROOT_PATH)
        self.log("Removing cloned git repository")
        self.remove_dir("temp")

        os.chdir(pwd)
        return True

    def run_benchmark(self):
        pwd = os.getcwd()
        os.chdir(ENGINE_FOLDER)

        self.log("Starting benchmark")
        processes = []
        for i in range(self.threads):
            processes.append(sp.Popen(self.engine_name(self.git_branch) + " bench", shell=True, stdout=sp.PIPE))

        for p in processes:
            p.wait()

        nodes = 0
        nps = 0

        for p in processes:
            for line in p.stdout:
                line = line.decode("utf-8")

                if "OVERALL" in line:
                    while "  " in line:
                        line = line.replace("  ", " ")

                    temp_nodes = int(line.split(" ")[1])
                    temp_nps = int(line.split(" ")[3])

                    if nodes != 0 and temp_nodes != nodes:
                        self.log("Non deterministic Bench!")
                        return False

                    nodes = temp_nodes
                    nps = temp_nps

        os.chdir(pwd)
        self.log("Finished benchmark")

        if nodes != self.bench:
            self.log(f"Wrong Bench. Expected {self.bench}, got {nodes}")
            return False

        return nps

    def build_cutechess_command(self):
        self.log("Building cutechess command")
        engine_args = f"restart=off " \
                      f"cmd={ENGINE_FOLDER + self.engine_name(self.git_branch)} " \
                      f"proto=uci " \
                      f"tc={self.tc} "
        engine_1_add = f"name=lower option.{self.relevant_option}={self.relevant_center - self.relevant_deviation} "
        engine_2_add = f"name=upper option.{self.relevant_option}={self.relevant_center + self.relevant_deviation} "
        cutechess_args = f"cutechess-cli{'.exe' if IS_WINDOWS else ''} " \
                         f"-engine {engine_1_add}" \
                         f"-engine {engine_2_add}" \
                         f"-each {engine_args}" \
                         f"-openings file={BOOK_FOLDER}{self.book} order=random " \
                         f"-concurrency {self.threads} " \
                         f"-games {self.games} " \
                         f"-pgnout {PGN_FOLDER}{time.time_ns()}.pgn " \
                         f"-repeat " \
                         f"-srand {random.randint(0, 100000000)} "
        return cutechess_args

    def adjust_tc(self, nps):
        scalar = self.base_speed / float(nps)

        moves_to_go = None
        time = None
        increment = None
        tc = self.tc

        if "/" in self.tc:
            split = tc.split("/")
            moves_to_go = int(split[0])
            tc = split[1]

        if "+" in self.tc:
            split = tc.split("+")
            time = float(split[0]) * scalar
            increment = float(split[1]) * scalar

        else:
            time = float(tc) * scalar

        self.tc = f"{moves_to_go + '/' if moves_to_go is not None else ''}" \
                  f"{round(time, 3)}" \
                  f"{'+' + str(round(increment, 3)) if increment is not None else ''}"

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
            p = None
            p = sp.Popen(cutechess_command, shell=True, stdout=sp.PIPE)
            wdl = None
            for stdout_line in iter(p.stdout.readline, ""):
                stdout_line = stdout_line.decode("utf-8").strip()
                if not stdout_line:
                    break
                print(stdout_line, flush=True)
                if "Score" in stdout_line:
                    wdl = tuple(map(int, stdout_line.split("Score of")[1].split(": ")[1].split(" [")[0].split(" - ")))

            p.stdout.close()
            return wdl
        except KeyboardInterrupt:
            if p is not None:
                p.send_signal(signal.SIGINT)

    def engine_name(self, branch):
        return f"{branch}{'.exe' if IS_WINDOWS else ''}"

    def remove_dir(self, path):
        path = correct_path(path)
        if os.path.isdir(path):
            if IS_WINDOWS:
                os.system(f"rmdir /S /Q {path}")
            else:
                os.system(f"rm -rf {path}")




def poll_for_work(args):
    return requests.get(args.U + f"/poll_for_work?token={args.P}").json()


def push_wdl(args, w, d, l):
    return requests.get(args.U + f"/push_wdl?w={w}&d={d}&l={l}&token={args.P}").json()


if __name__=='__main__':
    parser = argparse.ArgumentParser(description='Tune some values.')
    parser.add_argument('-T', metavar='Threads', type=int,
                        help='number of threads')
    parser.add_argument('-U', metavar='URL', type=str,
                        help='server URL')
    parser.add_argument('-P', metavar='Token', type=str,
                        help='Token')
    args = parser.parse_args()

    args = parser.parse_args()

    while True:
        work = poll_for_work(args)
        client = Client(work, args)
        w, d, l = client.iterate()
        push_wdl(args, w, d, l)

local = {
    "threads": 16
}
