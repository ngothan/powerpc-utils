#!/usr/bin/env python3
# Copyright (c) 2003, 2004, 2012 International Business Machines
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
# Author Todd Inglett <tinglett@us.ibm.com>
# updates by Michael Strosaker <strosake@us.ibm.com>
# updates by Vasant Hegde <hegdevasant@in.ibm.com>

# Snapshot system config
# Command-line parameters:
#    a:       all data; collect detailed information (more files and output)
#    d dir:   specify the directory where files and output will be collected
#               (default: /tmp/ibmsupt)
#    h:       print this help message
#    o file:  specify the output file (.tar required, .tar.gz optional)
#               (default: snap.tar.gz)
#    v:       verbose output
#
#  Exit codes (view with "echo $?" immediately after running):
#    0:  snap data was successfully captured
#    1:  invalid command line
#    2:  other fatal error

import argparse
import os
import sys
import stat
import shutil
import tarfile
import time
import glob
import subprocess
from pathlib import Path


PSERIES_PLATFORM = str(Path(__file__).resolve().parent / "pseries_platform")
outdir_default = "/tmp/ibmsupt"  # note NO trailing /
outfile_default = "snap.tar.gz"   # in the working dir.
cmddir = "snap_commands"          # cmd output dir.

# Does an IBM Flash Adapter exist?
rsxx_exists = False


def check_distro_support() -> None:
    redhat_release_file = "/etc/redhat-release"
    suse_release_file = "/etc/SuSE-release"
    distro_file = "/etc/issue"

    try:
        if os.path.exists(redhat_release_file):
            with open(redhat_release_file, "r", encoding="utf-8", errors="ignore") as fh:
                line = fh.readline()
            parts = line.split()
            redhat_version = None
            # Try to find a numeric token
            for token in parts:
                try:
                    redhat_version = float(token)
                    break
                except ValueError:
                    continue
            if redhat_version is not None and redhat_version >= 7.0:
                print("snap is not supported on the RHEL 7 onwards..!")
                print("Please use sosreport to collect log data..!! ")
                sys.exit(1)
        elif os.path.exists(suse_release_file):
            with open(suse_release_file, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if "VERSION" in line:
                        parts = line.split("=")
                        if len(parts) > 1:
                            try:
                                suse_version = float(parts[1].strip())
                            except ValueError:
                                suse_version = None
                            if suse_version is not None and suse_version >= 12:
                                print("snap is deprecated from SLES 12 onwards..!")
                                print("Please use supportconfig to collect log data..!! ")
                                sys.exit(1)
        else:
            with open(distro_file, "r", encoding="utf-8", errors="ignore") as fh:
                first = fh.readline()
            if "Ubuntu" in first:
                print("snap: is not supported on the Ubuntu platform")
                sys.exit(1)
    except OSError as exc:
        print(f"open: {exc}")
        sys.exit(2)


# Files to include in all snaps
snap_paths_general = [
    "/var/log/messages",
    "/var/log/platform",
    "/var/log/scanoutlog.*",
    # "/proc/bus/pci",  ?? binary file
    "/proc/cmdline",
    "/proc/cpuinfo",
    "/proc/devices",
    "/proc/dma",
    "/proc/filesystems",
    "/proc/fs",
    "/proc/ide",
    "/proc/interrupts",
    "/proc/iomem",
    "/proc/ioports",
    "/proc/loadavg",
    "/proc/locks",
    "/proc/mdstat",
    "/proc/meminfo",
    "/proc/misc",
    "/proc/modules",
    "/proc/mounts",
    "/proc/net",
    "/proc/partitions",
    "/proc/pci",
    "/proc/ppc64/lparcfg",
    "/proc/ppc64/eeh",
    "/proc/ppc64/pci",
    "/proc/ppc64/systemcfg",
    "/proc/scsi",
    "/proc/slabinfo",
    "/proc/stat",
    "/proc/swaps",
    "/proc/sys",
    "/proc/sysvipc",
    "/proc/uptime",
    "/proc/version",
    "/dev/nvram",
    "/etc/fstab",
    "/etc/raidtab",
    "/etc/yaboot.conf",
]

# Files to include in all snaps on SuSE systems
snap_paths_general_SuSE = [
    "/etc/SuSE-release",
    "/var/log/boot.msg",
]

# Files to include in all snaps on Red Hat systems
snap_paths_general_RedHat = [
    "/etc/redhat-release",
    "/var/log/dmesg",
]

# Files to include only in detailed snaps (-a option)
snap_paths_detailed = [
    "/proc/tty",
    "/etc/inittab",
    "/proc/ppc64/",
    "/proc/device-tree/",
]

# Command output to include in all snaps
snap_commands_general = [
    "lscfg -vp",
    "ifconfig -a",
    "lspci -vvv",
]

# Command output to include only in detailed snaps (-a option)
snap_commands_detailed = [
    "rpm -qa",
    "servicelog --dump",
    "servicelog_notify --list",
    "usysattn",
    "usysident",
    "serv_config -l",
    "bootlist -m both -r",
    "lparstat -i",
    "lsmcode -A",
    "lsvpd --debug",
    "lsvio -des",
    "ppc64_cpu --smt --cores-present --cores-on --run-mode --frequency --dscr",
]

# Command output to include for IBM Flash Adapter(s)
snap_command_rsxx = [
    "rs_cardreport -d 'all'",
]

# Files, which are to be ignored as they are deprecated
snap_deprecated_files = [
    "retrans_time",
    "base_reachable_time",
]


def error(is_fatal: bool, message: str, verbose: bool) -> None:
    if is_fatal:
        print(f"{Path(sys.argv[0]).name}: {message}")
        sys.exit(2)
    else:
        if verbose:
            print(f"{Path(sys.argv[0]).name}: {message}")


def print_usage_and_exit(parser: argparse.ArgumentParser, code: int) -> None:
    # Keep usage text aligned with the Perl script
    print(f"Usage: {Path(sys.argv[0]).name} [-athv] [-d dir] [-o file]\n")
    print("  Command-line parameters:")
    print("    a:       all data; collect detailed information (more files and output)")
    print("    d dir:   specify the directory where files and output will be collected")
    print("               (default: /tmp/ibmsupt)")
    print("    o file:  specify the output file (.tar required, .tar.gz optional)")
    print("               (default: snap.tar.gz)")
    print("    t:       add hostname and timestamp to output filename")
    print("    v:       verbose output\n")
    print("    h:       print this help message")
    print("  Exit codes (view with \"echo $?\" immediately after running):")
    print("    0:  snap data was successfully captured")
    print("    1:  invalid command line")
    print("    2:  other fatal error\n")
    sys.exit(code)


def safe_makedirs(path: str, verbose: bool) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        error(False, f"Cannot create directory: {path}", verbose)


def copy_file(source: str, destination: str, verbose: bool) -> None:
    # Create directories, if necessary
    dest_dir = os.path.dirname(destination)
    if dest_dir and not os.path.isdir(dest_dir):
        # Re-create the original behavior by incrementally creating path elements
        parts = dest_dir.split("/")
        prefix = "" if dest_dir.startswith("/") else None
        current = "/" if dest_dir.startswith("/") else ""
        for part in parts:
            if part == "":
                continue
            current = (current + part) if current.endswith("/") else (current + "/" + part)
            if not os.path.isdir(current):
                try:
                    os.mkdir(current, 0o644)
                except OSError:
                    error(False, f"Cannot create directory: {current}", verbose)
                    return
    # Copy file
    try:
        with open(source, "rb", buffering=0) as src, open(destination, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
    except FileNotFoundError:
        error(False, f"Cannot open file for reading: {source}", verbose)
    except PermissionError as exc:
        error(False, f"System read/write error while processing {source}: {exc}", verbose)
    except OSError as exc:
        error(False, f"System error while copying {source} -> {destination}: {exc}", verbose)


def recurse_dir(directory: str, outdir: str, verbose: bool) -> None:
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name in (".", "..") or entry.is_symlink():
                    continue
                full_path = os.path.join(directory, entry.name)
                if entry.is_dir(follow_symlinks=False):
                    recurse_dir(full_path, outdir, verbose)
                else:
                    if any(depr in entry.name for depr in snap_deprecated_files):
                        continue
                    copy_file(full_path, outdir + full_path, verbose)
    except OSError:
        error(False, f"Could not open directory {directory}", verbose)


def snap_paths(paths: list[str], outdir: str, verbose: bool) -> None:
    for path in paths:
        # For now do not collect proc ppc64 files for guest.
        platform_env = os.environ.get("platform")
        platform_guest = os.environ.get("PLATFORM_POWERKVM_GUEST")
        if "/proc/ppc64/" in path and platform_env and platform_guest and platform_env == platform_guest:
            continue

        if os.path.isdir(path):
            recurse_dir(path, outdir, verbose)
        else:
            # Check for wildcard (* in last character only)
            if path.endswith("*"):
                dir_part = path[: path.rfind("/")]
                search_prefix = path[path.rfind("/") + 1 : -1]
                try:
                    with os.scandir(dir_part) as it:
                        for entry in it:
                            if entry.name.startswith(search_prefix):
                                copy_file(os.path.join(dir_part, entry.name), outdir + "/" + dir_part.strip("/") + "/" + entry.name, verbose)
                except OSError:
                    error(False, f"Could not open directory {dir_part}", verbose)
            else:
                copy_file(path, outdir + path, verbose)


def snap_commands(commands: list[str], cmdoutdir: str, verbose: bool) -> None:
    if not os.path.isdir(cmdoutdir):
        try:
            os.mkdir(cmdoutdir, 0o644)
        except OSError:
            error(False, f"Cannot create directory: {cmdoutdir}", verbose)
            return

    for command in commands:
        # Retrieve the name of the binary to run (for output file name)
        path_part = command.split(" ")[0]
        filename = os.path.basename(path_part)
        out_path = os.path.join(cmdoutdir, f"{filename}.out")
        # Run command, capture stdout+stderr to file
        with open(out_path, "wb") as fh:
            proc = subprocess.run(command, shell=True, stdout=fh, stderr=subprocess.STDOUT)
        exit_value = proc.returncode
        if exit_value != 0:
            error(False, f"\"{command}\" returned {exit_value}", verbose)


def main(argv: list[str]) -> int:
    # Must be executed as root
    if os.geteuid() != 0:
        print(f"{Path(sys.argv[0]).name}: Must be executed as root")
        return 2

    # check for the distro version
    check_distro_support()

    # Source pseries_platform and import its environment
    per_env = {}
    try:
        # Use env -0 for robust parsing
        bash_cmd = f". {PSERIES_PLATFORM}; env -0"
        result = subprocess.run(["bash", "-c", bash_cmd], check=False, stdout=subprocess.PIPE)
        for item in result.stdout.split(b"\x00"):
            if not item:
                continue
            key, _, val = item.partition(b"=")
            try:
                per_env[key.decode()] = val.decode()
            except UnicodeDecodeError:
                # Skip undecodable entries
                continue
        os.environ.update(per_env)
    except Exception:
        pass

    platform_val = os.environ.get("platform")
    platform_unknown = os.environ.get("PLATFORM_UNKNOWN")
    platform_powernv = os.environ.get("PLATFORM_POWERNV")
    platform_name = os.environ.get("platform_name", "unknown")
    if platform_val is not None and (platform_val == platform_unknown or platform_val == platform_powernv):
        print(f"snap: is not supported on the {platform_name} platform")
        return 1

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-a", action="store_true")
    parser.add_argument("-t", action="store_true")
    parser.add_argument("-d", metavar="dir")
    parser.add_argument("-o", metavar="file")
    parser.add_argument("-v", action="store_true")
    parser.add_argument("-h", action="store_true")

    try:
        args, extras = parser.parse_known_args(argv)
    except SystemExit:
        print_usage_and_exit(parser, 1)
        return 1

    if args.h:
        print_usage_and_exit(parser, 0)
        return 0

    outdir = args.d if args.d else outdir_default
    cmdoutdir = f"{outdir}/{cmddir}"
    outfile = args.o if args.o else outfile_default
    verbose = args.v

    if os.path.exists(outdir):
        print(f"{Path(sys.argv[0]).name}: cannot run; {outdir} already exists.")
        return 2

    if outdir.endswith("/"):
        outdir = outdir[:-1]

    if args.o:
        if ".tar" not in args.o:
            print(f"{Path(sys.argv[0]).name}: The filename provided, {args.o}, does not contain .tar;", end="")
            print(f" Using default filename {outfile}")
            outfile = outfile_default
        else:
            outfile = args.o

    if args.t:
        host = subprocess.run(["hostname"], stdout=subprocess.PIPE, text=True).stdout.strip()
        halias = host.split(".")
        current_time = time.strftime("%Y%m%d%H%M%S", time.localtime())
        temp = outfile[: outfile.rfind(".tar")] if ".tar" in outfile else outfile
        temp1 = outfile[outfile.rfind(".tar") + 1 :] if ".tar" in outfile else "tar"
        outfile = f"{temp}-{halias[0]}-{current_time}.{temp1}"

    if os.path.exists(outfile):
        print(f"{Path(sys.argv[0]).name}: cannot run; {outfile} already exits.")
        return 2

    # Check to see if we need to gather information on IBM Flash Adapter(s).
    global rsxx_exists
    rsxx_exists = any(glob.glob("/dev/rsxx*"))

    # Collect paths
    snap_paths(snap_paths_general, outdir, verbose)

    # Check distro
    if os.path.exists("/etc/SuSE-release"):
        snap_paths(snap_paths_general_SuSE, outdir, verbose)
    elif os.path.exists("/etc/redhat-release"):
        snap_paths(snap_paths_general_RedHat, outdir, verbose)

    # Run commands and capture output
    snap_commands(snap_commands_general, cmdoutdir, verbose)

    # Gather detail files if requested (-a option)
    if args.a:
        snap_paths(snap_paths_detailed, outdir, verbose)
        snap_commands(snap_commands_detailed, cmdoutdir, verbose)

    # Gather information regarding IBM Flash Adapter(s)
    if rsxx_exists:
        # Verify the rsxx utils are installed.
        proc = subprocess.run("rpm -qa | grep rsxx-utils > /dev/null", shell=True)
        if proc.returncode == 0:
            snap_commands(snap_command_rsxx, cmdoutdir, verbose)
        else:
            print("Warning: The rsxx-utils RPM are not installed, "
                  "unable to gather IBM Flash Adapter information.\n"
                  "\t Run 'yum install rsxx-utils' to install.")

    basefile, extension = (outfile.split(".tar", 1) + [""])[:2]
    basedir = outdir[: outdir.rfind("/")]
    compressdir = outdir[outdir.rfind("/") + 1 :]

    # Create tar file (without compression first, to mimic original)
    tar_tmp = f"{basefile}.tar"
    try:
        with tarfile.open(tar_tmp, "w") as tf:
            # Equivalent to: tar -cf <tar_tmp> --directory=<basedir> <compressdir>
            tf.add(outdir, arcname=compressdir)
    except Exception as exc:
        print(f"{Path(sys.argv[0]).name}: Failed to create tar: {exc}")
        return 2

    if extension == ".gz":
        # gzip -f
        try:
            with open(tar_tmp, "rb") as f_in:
                with tarfile.open(f"{basefile}.tar.gz", "w:gz") as tf_gz:
                    # Repack: add the tar content directory directly for simplicity
                    # Instead of re-reading tar stream, just add again from filesystem
                    tf_gz.add(outdir, arcname=compressdir)
            os.remove(tar_tmp)
            final_out = f"{basefile}.tar.gz"
        except Exception as exc:
            print(f"{Path(sys.argv[0]).name}: Failed to gzip tar: {exc}")
            return 2
    elif extension == "":
        final_out = tar_tmp
    else:
        outfile = f"{basefile}.tar"
        print(f"{Path(sys.argv[0]).name}: Unrecognized extension {extension}")
        final_out = outfile

    # Delete temporary directory
    try:
        subprocess.run(["rm", "-rf", outdir], check=False)
    except Exception:
        pass

    print(f"output written to {final_out}")
    print("WARNING: archive may contain confidential data and/or cleartext passwords!")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


