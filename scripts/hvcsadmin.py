#!/usr/bin/env python3
# IBM "hvcsadmin": HVCS driver 'helper' application
#
# Copyright (c) 2004, 2005 International Business Machines.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# Author(s): Ryan S. Arnold <rsa@us.ibm.com>
#
# This application provides a simple command line interface for simplifying
# the management of hvcs.
#
# For further details please reference man page hvcsadmin.8

import argparse
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

# Globals mirroring Perl variables
APP_NAME = "hvcsadmin"
APP_VERSION = "1.0.0"
DRIVER = "hvcs"
GLOBAL_NODE_NAME = "hvcs"
NOISY = 0

# Simply output using the same noisy levels as the Perl script.
def verboseprint(output: str) -> None:
    if NOISY > 1:
        sys.stdout.write(output)

def statusprint(output: str) -> None:
    if NOISY > 0:
        sys.stdout.write(output)

def errorprint(output: str) -> None:
    sys.stderr.write(output)

# Simply output the version information about this helper application.
def versioninfo() -> None:
    print(f"IBM {APP_NAME} version {APP_VERSION}")
    print("Copyright (C) 2004, IBM Corporation.")
    print("Author(s) Ryan S. Arnold")

# Help information text displayed to the user when they invoke the script with
# the -h tag.
def helpinfo() -> None:
    print(f"Usage: {APP_NAME} [options]")
    print("Options:")
    print(" -all")
    print("\t\t\tClose all open vty-server adapter connections.")
    print("")
    print(f" -close </dev/{DRIVER}*>")
    print("\tClose the vty-server adapter connection for the")
    print(f"\t\t\t{DRIVER} device node specified in the option.")
    print("")
    print(" -console <partition>")
    print(f"\tWhich /dev/{DRIVER}\\* node provides the console for")
    print("\t\t\tthe option specified partition?")
    print("")
    print(" -help")
    print("\t\t\tOutput this help text.")
    print("")
    print(f" -node </dev/{DRIVER}*>")
    print("\tWhich vty-server adapter is mapped to the option")
    print(f"\t\t\tspecified /dev/{DRIVER}\\* node?")
    print("")
    print(" -noisy")
    print(f"\t\t\tThis is a stackable directive denoting the verbosity")
    print(f"\t\t\tof the {APP_NAME} script.  The default noise level of")
    print(f"\t\t\t'0' makes {APP_NAME} silent on success but verbose on")
    print("\t\t\terror. A noise level of '1' will output additional")
    print("\t\t\tsuccess information.  A noisy level of '2' will")
    print(f"\t\t\toutput {APP_NAME} script trace information.")
    print("")
    print(f"\t\t\tNOTE: options for which {APP_NAME} queries data are")
    print("\t\t\tnot squelched with the default noise level.")
    print("")
    print(" -rescan")
    print("\t\tDirect the hvcs driver to rescan partner info")
    print("\t\t\tfor all vty-server adapters.")
    print("")
    print(" -status")
    print("\t\tOutput a table with each row containing a vty-server,")
    print(f"\t\t\tadapter, its /dev/{DRIVER}\\* device node mapping, and")
    print("\t\t\tits connection status.  \"vterm_state:0\" means it is")
    print("\t\t\tfree and \"vterm_state:1\" means the vty-server is")
    print("\t\t\tconnected to its vty partner adapter.")
    print("")
    print(f" -version\t\tOutput the {APP_NAME} script's version number.")
    print("")

def run_cmd(cmd: str) -> subprocess.Popen:
    # helper to execute shell commands similar to Perl backticks/open
    try:
        return subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except Exception as e:
        errorprint(f"{APP_NAME}: failed to run command: {cmd}: {e}\n")
        sys.exit(1)

# Determine the sysfs path and driver name programatically because these can
# change.
def rescan() -> None:
    verboseprint(f"{APP_NAME}: initiating rescan of all vty-server adapter partners.\n")

    # use systool to find the vio devices which we want to close
    proc = run_cmd("systool -b vio -D -p")
    out, err = proc.communicate()
    if proc.returncode != 0:
        errorprint(f"systool: {err or 'unknown error'}\n")
        sys.exit(1)

    local_driver = ""
    driver_path = ""
    for line in out.splitlines():
        m = re.match(r'^\s*Driver = "(.*)"\s*$', line)
        if m:
            local_driver = m.group(1)
            driver_path = ""
            continue

        m = re.match(r'^\s*Driver path = "(.*)"\s*$', line)
        if m:
            driver_path = m.group(1)
            if local_driver == DRIVER:
                try:
                    with open(os.path.join(driver_path, "rescan"), "w") as f:
                        f.write("1")
                    statusprint(f"{APP_NAME}: {DRIVER} driver rescan executed.\n")
                    return
                except Exception:
                    pass
            continue

    errorprint(f"{APP_NAME}: {DRIVER} sysfs entry or {DRIVER} rescan attribute not found.\n")

def closeall() -> None:
    # Programatically locate all the vty-server adapters and close their
    # connections (or at least attempt to).  One or more closures may fail if
    # there is an application using the device node that is mapped to the
    # vty-server adapter that is being closed.

    # use systool to find the vio devices which we want to close
    proc = run_cmd("systool -b vio -D -A vterm_state -p")
    out, err = proc.communicate()
    if proc.returncode != 0:
        errorprint(f"systool:  {err or 'unknown error'}\n")
        sys.exit(1)

    local_driver = ""
    local_device = ""
    vterm_state = ""
    device_path = ""
    for line in out.splitlines():
        m = re.match(r'^\s*Driver = "(.*)"\s*$', line)
        if m:
            local_driver = m.group(1)
            local_device = ""
            device_path = ""
            continue

        m = re.match(r'^\s*Device path = "(.*)"\s*$', line)
        if m:
            device_path = m.group(1)
            continue

        m = re.match(r'^\s*Device = "(.*)"\s*$', line)
        if m:
            local_device = m.group(1)
            continue

        m = re.match(r'^\s*vterm_state\s*= "(.*)"\s*$', line)
        if m:
            vterm_state = m.group(1)
            if (local_driver == DRIVER) and (vterm_state == "1"):
                try:
                    with open(os.path.join(device_path, "vterm_state"), "w") as f:
                        f.write("0")
                    statusprint(f"{APP_NAME}: closed vty-server@{local_device} partner adapter connection.\n")
                except Exception:
                    pass
            continue

# This is a input validation routine which checks a user entered device path
# to determine if the device index is in the proper range.
def validindex(dev_index: str) -> int:
    verboseprint(f"{APP_NAME}: is {dev_index} a valid device node number? ...\n")

    # We didn't find an invalid number that starts with 0 and has more digits
    if re.match(r'(^0.+$)', dev_index or ""):
        errorprint(f'{APP_NAME}: "{dev_index}" is an invalid device node number.\n')
        return -1

    verboseprint(f"{APP_NAME}: {dev_index} is a valid device node index.\n")
    return 0

# Checks to see if the user entered device node exists in the /dev directory.
# If this unexpectedly indicates that there is no device it may be because
# udev is managing the /dev directory and the hvcs driver has not yet been
# inserted.
def finddeventry(node_name: str, dev_number: str) -> int:
    device_path = f"/dev/{node_name}{dev_number}"

    verboseprint(f"{APP_NAME}: is {device_path} in /dev? ...\n")

    if not os.path.exists(device_path):
        errorprint(f"{APP_NAME}: {device_path} not found in /dev.\n")
        return -1
    verboseprint(f"{APP_NAME}: found {device_path} in /dev.\n")
    return 0

def is_driver_installed() -> str:
    val = ""
    local_driver = ""
    driver_path = ""

    verboseprint(f"{APP_NAME}: is {DRIVER} loaded.\n")

    proc = run_cmd("systool -b vio -D -p")
    out, err = proc.communicate()
    if proc.returncode != 0:
        errorprint(f"systool:  {err or 'unknown error'}\n")
        return ""

    for line in out.splitlines():
        m = re.match(r'^\s*Driver = "(.*)"\s*$', line)
        if m:
            local_driver = m.group(1)
            driver_path = ""
            continue
        m = re.match(r'^\s*Driver path = "(.*)"\s*$', line)
        if m:
            driver_path = m.group(1)
            # grab only the Driver,Driver path pair for DRIVER
            if local_driver == DRIVER:
                verboseprint(f"{APP_NAME}: verified that {DRIVER} is loaded at {driver_path}.\n")
                return driver_path
            continue

    errorprint(f"{APP_NAME}: {DRIVER} is not loaded.\n")
    return ""

# Verify that the systools package is installed.  This package is required for
# using this scripts because this script uses systools to make sysfs queries.
# It then strips relevant data from the systool queries for use in additional
# features.
def findsystools() -> int:
    #--------------- Look for the systool application -----------------------
    proc = run_cmd("which systool")
    out, _ = proc.communicate()
    whichline = (out or "").strip()

    verboseprint(f'{APP_NAME}: looking for "systool" application.\n')

    if whichline == "":
        errorprint(f"{APP_NAME}: systool is not installed or not in the path?\n")
        errorprint(f"{APP_NAME}: systool is required by the {APP_NAME} script.\n")
        return -1
    verboseprint(f'{APP_NAME}: found "systool" at {whichline}.\n')

    return 0

# This function is a helper function that is used to return a sysfs hvcs
# device path based upon a partition number.  This function always looks for
# the zeroeth indexed partner adapter, meaning it will always return the path
# to the console device for the selected target partition.
def get_device_path_by_partition(target_partition: str) -> str:
    local_driver = ""
    found_partition = ""
    found_slot = ""
    device_path = ""

    verboseprint(f"{APP_NAME}: fetching device path for partition {target_partition}.\n")

    proc = run_cmd("systool -b vio -D -A current_vty -p")
    out, err = proc.communicate()
    if proc.returncode != 0:
        errorprint(f"systool:  {err or 'unknown error'}\n")
        return ""

    for line in out.splitlines():
        m = re.match(r'^\s*Driver = "(.*)"\s*$', line)
        if m:
            local_driver = m.group(1)
            device_path = ""
            found_partition = ""
            found_slot = ""
            continue

        m = re.match(r'^\s*Device path = "(.*)"\s*$', line)
        if m:
            device_path = m.group(1)
            continue

        # Grab the partition number out of clc, e.g. the numeric index
        # following the V, and grab the slot number, e.g. the numeric index
        # following the C: "U9406.520.100048A-V15-C0"
        m = re.match(r'^\s*current_vty\s*= "\w+\.\w+\.\w+-V(\d+)-C(\d+)"\s*$', line)
        if m:
            found_partition = m.group(1)
            found_slot = m.group(2)
            if (local_driver == DRIVER
                and (target_partition == found_partition)
                and (found_slot == "0")):
                verboseprint(f"{APP_NAME}: found console device for partition {target_partition} at {device_path}.\n")
                return device_path

    statusprint(f"{APP_NAME}: could not find device path for partition {target_partition}.\n")

    return ""

# This function is a helper function that is used to return a sysfs path based
# upon an index number.  The "index" is the number that is part of the hvcs
# device path name.  For instance, in "/dev/hvcs2", the number '2' is refered
# to as the "index".  Additionally, the sysfs entry keeps track of the index
# number for the hvcs entries in sysfs so there is a correlation between the
# data kept in the sysfs entry and the actual /dev/hvcs* entry.
def get_device_path_by_index(target_index: str) -> str:
    device_path = ""
    index = ""
    local_driver = ""
    val = ""

    verboseprint(f"{APP_NAME}: fetching device path for index {target_index}.\n")

    proc = run_cmd("systool -b vio -D -A index -p")
    out, err = proc.communicate()
    if proc.returncode != 0:
        errorprint(f"systool:  {err or 'unknown error'}\n")
        return ""

    for line in out.splitlines():
        m = re.match(r'^\s*Driver = "(.*)"\s*$', line)
        if m:
            local_driver = m.group(1)
            device_path = ""
            index = ""
            continue

        m = re.match(r'^\s*Device path = "(.*)"\s*$', line)
        if m:
            device_path = m.group(1)
            continue

        m = re.match(r'^\s*index\s*= "(.*)"\s*$', line)
        if m:
            index = m.group(1)
            if (local_driver == DRIVER) and (index == target_index):
                verboseprint(f"{APP_NAME}: found device path for device index {target_index} at {device_path}.\n")
                return device_path
            continue

    statusprint(f"{APP_NAME}: /dev/{GLOBAL_NODE_NAME}{target_index} does not map to a vty-server adapter.\n")

    return ""

# This function takes a sysfs path to an hvcs adapter and displays it in a
# formatted manner.  This path is gathered using one of the previous path
# retrieval functions.  Generally devices are displayed in a sequence and a
# table is created out of these details though they can be displayed
# individually as well.
def displaybypath(path: str) -> int:
    verboseprint(f"{APP_NAME}: displaying status information for {path}.\n")

    if path == "":
        errorprint(f"{APP_NAME}: displaybypath( $ ) path parameter is empty.\n")
        return -1

    if not os.path.exists(os.path.join(path, "current_vty")):
        errorprint(f"{APP_NAME}: {path}/current_vty attribute does not exist.\n")
        sys.exit(1)

    verboseprint(f"{APP_NAME}: {path}/current_vty attribute exists.\n")

    if not os.path.exists(os.path.join(path, "index")):
        errorprint(f"{APP_NAME}: {path}/index attribute does not exist.\n")
        sys.exit(1)

    verboseprint(f"{APP_NAME}: {path}/index attribute exists.\n")

    if not os.path.exists(os.path.join(path, "vterm_state")):
        errorprint(f"{APP_NAME}: {path}/vterm_state attribute does not exist.\n")
        sys.exit(1)

    verboseprint(f"{APP_NAME}: verified that {path}/vterm_state attribute exists.\n")

    with open(os.path.join(path, "current_vty")) as f:
        current_vty = f.read().strip()

    # parse the CLC, nasty as it may be
    m = re.search(r'(\w+\.\w+\.\w+)-V(\d+)-C(\d+)$', current_vty)
    machine = m.group(1) if m else ""
    partition = m.group(2) if m else ""
    slot = m.group(3) if m else ""

    with open(os.path.join(path, "vterm_state")) as f:
        vterm_state = f.read().strip()

    with open(os.path.join(path, "index")) as f:
        device_index = f.read().strip()

    # /sys/devices/vio/30000005
    m = re.search(r'.+(3[0-9a-fA-F]+)$', path)
    vty_server = m.group(1) if m else ""

    print(f"vty-server@{vty_server} partition:{partition} slot:{slot} /dev/{DRIVER}{device_index} vterm-state:{vterm_state}")
    return -1 if path == "" else 0

# This function simply takes a /dev/hvcs* entry and displays the relevant
# sysfs entry data about that device node.
def querynode(dev_node: str) -> None:
    dev_index = getindex(dev_node)
    dev_name = getnodename(dev_node)

    verboseprint(f"{APP_NAME}: querying status information for node {dev_node}.\n")

    if dev_name != GLOBAL_NODE_NAME:
        errorprint(f"{APP_NAME}: {dev_node} is an invalid device node name.\n")
        sys.exit(1)

    if validindex(dev_index):
        sys.exit(1)

    if finddeventry(dev_name, dev_index):
        sys.exit(1)

    # check modinfo version of the hvcs module?

    path = get_device_path_by_index(dev_index)
    if path == "":
        return
    displaybypath(path)

# This function displays the sysfs information about a console to a specific
# partition.  This function should only display output if a device is found
# that maps to a zero slotted vty-server adapter, since only slot 0 adapters
# are console adapters.
def queryconsole(partition: str) -> None:
    path = get_device_path_by_partition(partition)
    if path == "":
        return
    displaybypath(path)

def status() -> None:
    try:
        entries = sorted(os.listdir("/dev"))
    except Exception:
        entries = []
    path = ""
    count = 0

    verboseprint(f"{APP_NAME}: gathering status for all vty-server adapters.\n")
    verboseprint(f"{APP_NAME}: some device nodes won't be mapped to vty-server adapters.\n")

    for entry in entries:
        m = re.search(rf'{re.escape(GLOBAL_NODE_NAME)}(\d)$', entry)
        if m:
            path = get_device_path_by_index(m.group(1))
            if path != "":
                displaybypath(path)
                count += 1
        path = ""

    if count == 0:
        print(f"{APP_NAME}: no hvcs adapters found.")

def getindex(devnode: str) -> str:
    m = re.search(rf'{re.escape(GLOBAL_NODE_NAME)}([0-9]+)$', devnode or "")
    return m.group(1) if m else "-1"

def getnodename(devnode: str) -> str:
    m = re.search(rf'({re.escape(GLOBAL_NODE_NAME)})[0-9]+$', devnode or "")
    return m.group(1) if m else ""

def closedevice(parameter: str) -> None:
    node_name = getnodename(parameter)
    node_index = getindex(parameter)

    #--------------- Is the specified device name valid? --------------------
    if node_name != GLOBAL_NODE_NAME:
        errorprint(f"{APP_NAME}: {parameter} is an invalid device node name.\n")
        sys.exit(1)

    #--------------- Is the specified device index reasonable? --------------
    if validindex(node_index):
        sys.exit(1)

    #--------------- Does the /dev/ entry exist -----------------------------
    if finddeventry(node_name, node_index):
        sys.exit(1)

    # check modinfo version of the hvcs module

    #--------------- Gather sysfs info from systool -------------------------
    device_path = get_device_path_by_index(node_index)
    if device_path == "":
        sys.exit(1)

    verboseprint(f"{APP_NAME}: vty-server adapter {device_path} maps to /dev/{node_name}{node_index}.\n")

    vstate_path = os.path.join(device_path, "vterm_state")
    if not os.path.exists(vstate_path):
        errorprint(f"{APP_NAME}: vterm_state attribute does not exist.\n")
        sys.exit(1)

    verboseprint(f"{APP_NAME}: verified that {vstate_path} attribute exists.\n")

    with open(vstate_path) as f:
        catval = f.read().strip()

    if re.fullmatch(r"0", catval):
        statusprint(f"{APP_NAME}: vty-server adapter {device_path} is already disconnected.\n")
        sys.exit(0)

    verboseprint(f"{APP_NAME}: preparing to terminate vty-server connection at {device_path}.\n")

    try:
        with open(vstate_path, "w") as f:
            f.write("0")
    except Exception:
        pass

    with open(vstate_path) as f:
        cat = f.read().strip()

    if not re.fullmatch(r"0", cat):
        errorprint(f"{APP_NAME}: vty-server adapter {device_path} disconnection failed.\n")
        errorprint(f"{APP_NAME}: please check dmesg for further information.\n")
        sys.exit(1)

    m = re.search(r'.+(3\d+)$', device_path)
    vty_server = m.group(1) if m else ""

    statusprint(f"{APP_NAME}: /dev/node/{node_name}{node_index} is mapped to vty-server@{vty_server}.\n")
    statusprint(f"{APP_NAME}: closed vty-server@{vty_server} partner adapter connection.\n")

# Load platform gating environment and check, mirroring the Perl sourcing of
# pseries_platform and ENV checks.
def load_platform_env_and_check() -> None:
    PSERIES_PLATFORM = str(Path(__file__).resolve().parent / "pseries_platform")

    # Source and emit environment, then parse it here.
    bash_cmd = f'. {shlex.quote(PSERIES_PLATFORM)}; env -0'
    proc = run_cmd(f"bash -c {shlex.quote(bash_cmd)}")
    out, _ = proc.communicate()
    env = {}
    for kv in (out or "").split("\x00"):
        if not kv:
            continue
        if "=" in kv:
            k, v = kv.split("=", 1)
            env[k] = v

    if env.get("platform") is None or env.get("PLATFORM_PSERIES_LPAR") is None:
        errorprint(f"{APP_NAME}: failed to read platform variables from the environment\n")
        sys.exit(1)

    try:
        if int(env.get("platform", "-1")) != int(env.get("PLATFORM_PSERIES_LPAR", "-2")):
            print(f"{APP_NAME}: is not supported on the {env.get('platform_name', '')} platform")
            sys.exit(1)
    except ValueError:
        print(f"{APP_NAME}: is not supported on the {env.get('platform_name', '')} platform")
        sys.exit(1)

def main(argv):
    global NOISY

    PSERIES_PLATFORM = str(Path(__file__).resolve().parent / "pseries_platform")
    # keep the platform gating logic behaviorally equivalent to Perl
    load_platform_env_and_check()

    help_flag = False
    version = False
    close_device = ""
    all_flag = False
    query_node = ""
    query_console = ""
    status_flag = False
    rescan_flag = False

    # -noisy is the only option that stacks
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-all", dest="all_flag", action="store_true")
    parser.add_argument("-help", "-?", dest="help_flag", action="store_true")
    parser.add_argument("-noisy", dest="noisy", action="count", default=0)
    parser.add_argument("-status", dest="status_flag", action="store_true")
    parser.add_argument("-rescan", dest="rescan_flag", action="store_true")
    parser.add_argument("-version", dest="version", action="store_true")
    parser.add_argument("-node", dest="query_node", metavar="DEV", default="")
    parser.add_argument("-close", dest="close_device", metavar="DEV", default="")
    parser.add_argument("-console", dest="query_console", metavar="PART", default="")
    args, _ = parser.parse_known_args(argv)

    num_options = len(argv)

    # An empty invocation of this script will result in the help text being
    # output.  If help text has been specified then this script will terminate
    # after outputing the help text without completing further operations.
    if num_options == 0 or args.help_flag:
        helpinfo()
        return

    if args.version:
        versioninfo()
        return

    NOISY = args.noisy
    verboseprint(f"{APP_NAME}: executing in verbose mode.\n")

    #--------------- Look for the systool application -----------------------
    # The systool application is required for invoking most/many of these
    # operations so we'll express it as a standard requirement.
    if findsystools():
        sys.exit(1)

    # DON'T rely on the module existence to determine whether DRIVER is
    # supported since it could have been built into the kernel.

    #--------------- Look for the DRIVER module in lsmod -------------------
    if not is_driver_installed():
        sys.exit(1)

    if args.status_flag:
        status()
        return

    if args.rescan_flag:
        rescan()

    if args.all_flag:
        closeall()
        return

    if args.close_device:
        closedevice(args.close_device)
        return

    if args.query_node:
        querynode(args.query_node)
        return

    if args.query_console:
        queryconsole(args.query_console)
        return

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        sys.exit(130)
