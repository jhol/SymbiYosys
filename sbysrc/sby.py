#!/usr/bin/env python3
#
# SymbiYosys (sby) -- Front-end for Yosys-based formal verification flows
#
# Copyright (C) 2016  Clifford Wolf <clifford@clifford.at>
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#

import os, sys, getopt, shutil, tempfile
##yosys-sys-path##
from sby_core import SbyJob

sbyfile = None
workdir = None
tasknames = list()
opt_force = False
opt_backup = False
opt_tmpdir = False
exe_paths = dict()

def usage():
    print("""
sby [options] [<jobname>.sby [tasknames]]

    -d <dirname>
        set workdir name. default: <jobname> (without .sby)

    -f
        remove workdir if it already exists

    -b
        backup workdir if it already exists

    -t
        run in a temporary workdir (remove when finished)

    -T taskname
        add taskname (useful when sby file is read from stdin)

    --yosys <path_to_executable>
    --abc <path_to_executable>
    --smtbmc <path_to_executable>
    --suprove <path_to_executable>
    --aigbmc <path_to_executable>
    --avy <path_to_executable>
        configure which executable to use for the respective tool
""")
    sys.exit(1)

try:
    opts, args = getopt.getopt(sys.argv[1:], "d:btfT:", ["yosys=",
            "abc=", "smtbmc=", "suprove=", "aigbmc=", "avy="])
except:
    usage()

for o, a in opts:
    if o == "-d":
        workdir = a
    elif o == "-f":
        opt_force = True
    elif o == "-b":
        opt_backup = True
    elif o == "-t":
        opt_tmpdir = True
    elif o == "-T":
        tasknames.append(a)
    elif o == "--yosys":
        exe_paths["yosys"] = a
    elif o == "--abc":
        exe_paths["abc"] = a
    elif o == "--smtbmc":
        exe_paths["smtbmc"] = a
    elif o == "--suprove":
        exe_paths["suprove"] = a
    elif o == "--aigbmc":
        exe_paths["aigbmc"] = a
    elif o == "--avy":
        exe_paths["avy"] = a
    else:
        usage()

if len(args) > 0:
    sbyfile = args[0]
    assert sbyfile.endswith(".sby")

if len(args) > 1:
    tasknames = args[1:]


early_logmsgs = list()

def early_log(workdir, msg):
    early_logmsgs.append("SBY [%s] %s" % (workdir, msg))
    print(early_logmsgs[-1])


def read_sbyconfig(sbydata, taskname):
    cfgdata = list()
    tasklist = list()

    pycode = None
    tasks_section = False
    task_tags_active = set()
    task_tags_all = set()
    task_skip_block = False
    task_skiping_blocks = False

    for line in sbydata:
        line = line.rstrip("\n")
        line = line.rstrip("\r")

        if tasks_section and line.startswith("["):
            tasks_section = False

        if task_skiping_blocks:
            if line == "--":
                task_skip_block = False
                task_skiping_blocks = False
                continue

        task_skip_line = False
        for t in task_tags_all:
            if line.startswith(t+":"):
                line = line[len(t)+1:].lstrip()
                match = t in task_tags_active
            elif line.startswith("~"+t+":"):
                line = line[len(t)+2:].lstrip()
                match = t not in task_tags_active
            else:
                continue

            if line == "":
                task_skiping_blocks = True
                task_skip_block = not match
                task_skip_line = True
            else:
                task_skip_line = not match

            break

        if task_skip_line or task_skip_block:
            continue

        if tasks_section:
            line = line.split()
            if len(line) > 0:
                tasklist.append(line[0])
            for t in line:
                if taskname == line[0]:
                    task_tags_active.add(t)
                task_tags_all.add(t)

        elif line == "[tasks]":
            tasks_section = True

        elif line == "--pycode-begin--":
            pycode = ""

        elif line == "--pycode-end--":
            gdict = globals().copy()
            gdict["cfgdata"] = cfgdata
            gdict["taskname"] = taskname
            exec("def output(line):\n  cfgdata.append(line)\n" + pycode, gdict)
            pycode = None

        else:
            if pycode is None:
                cfgdata.append(line)
            else:
                pycode += line + "\n"

    return cfgdata, tasklist


sbydata = list()
with (open(sbyfile, "r") if sbyfile is not None else sys.stdin) as f:
    for line in f:
        sbydata.append(line)

if len(tasknames) == 0:
    _, tasknames = read_sbyconfig(sbydata, None)
    if len(tasknames) == 0:
        tasknames = [None]

assert (workdir is None) or (len(tasknames) == 1)


def run_job(taskname):
    my_workdir = workdir
    my_opt_tmpdir = opt_tmpdir

    if my_workdir is None and sbyfile is not None and not my_opt_tmpdir:
        my_workdir = sbyfile[:-4]
        if taskname is not None:
            my_workdir += "_" + taskname

    if my_workdir is not None:
        if opt_backup:
            backup_idx = 0
            while os.path.exists("%s.bak%03d" % (my_workdir, backup_idx)):
                backup_idx += 1
            early_log(my_workdir, "Moving direcory '%s' to '%s'." % (my_workdir, "%s.bak%03d" % (my_workdir, backup_idx)))
            shutil.move(my_workdir, "%s.bak%03d" % (my_workdir, backup_idx))

        if opt_force:
            early_log(my_workdir, "Removing direcory '%s'." % (my_workdir))
            if sbyfile:
                shutil.rmtree(my_workdir, ignore_errors=True)

        os.makedirs(my_workdir)

    else:
        my_opt_tmpdir = True
        my_workdir = tempfile.mkdtemp()

    sbyconfig, _ = read_sbyconfig(sbydata, taskname)
    job = SbyJob(sbyconfig, taskname, my_workdir, early_logmsgs)

    for k, v in exe_paths.items():
        job.exe_paths[k] = v

    job.run()

    if my_opt_tmpdir:
        job.log("Removing direcory '%s'." % (my_workdir))
        shutil.rmtree(my_workdir, ignore_errors=True)

    job.log("DONE (%s, rc=%d)" % (job.status, job.retcode))
    return job.retcode


retcode = 0
for t in tasknames:
    assert (t is None) or (t in tasknames)
    retcode += run_job(t)

sys.exit(retcode)

