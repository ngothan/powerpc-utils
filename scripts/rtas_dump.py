#!/usr/bin/env python3

# This updated version of the rtas_dump script will
# do everything the original rtas_dump script does except
# it does it cleaner and without as many cmdline options.
#
# Copyright (C) 2004 International Business Machines
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
# Author: Nathan Fontenot <nfont@linux.vnet.ibm.com>
#

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


# RTAS event decoder path (matches Perl: $ENV{RTAS_EVENT_DECODE} || "/usr/sbin/rtas_event_decode")
RE_DECODE = os.environ.get("RTAS_EVENT_DECODE", "/usr/sbin/rtas_event_decode")


def usage_exit(parser: argparse.ArgumentParser) -> None:
    """
    usage statement
    """
    parser.print_help()
    sys.exit(1)


def source_env_from_pseries(pseries_platform_path: Path) -> dict:
    """
    Read environment variables after sourcing the pseries_platform file.

    This mirrors the Perl approach which ran a subshell to source the file
    and then dumped %ENV. Here we use `env -0` to safely capture all variables.
    """
    if not pseries_platform_path.exists():
        return {}

    bash_cmd = f". {sh_quote(str(pseries_platform_path))}; env -0"
    try:
        completed = subprocess.run(
            ["bash", "-c", bash_cmd],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        # If sourcing fails, proceed without updating the environment
        return {}

    env_blob = completed.stdout
    env_map: dict[str, str] = {}
    for entry in env_blob.split(b"\x00"):
        if not entry:
            continue
        if b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        try:
            env_map[key.decode("utf-8", "ignore")] = value.decode("utf-8", "ignore")
        except Exception:
            # Best-effort decoding
            env_map[key.decode(errors="ignore")] = value.decode(errors="ignore")
    return env_map


def sh_quote(s: str) -> str:
    """Minimal shell quoting for safe inclusion in a bash -c string."""
    return "'" + s.replace("'", "'\\''") + "'"


def verify_re_decode_exists(re_decode_path: str) -> None:
    # make sure the rtas_event_decode application is available
    if not os.path.exists(re_decode_path):
        sys.stderr.write(
            f"File {re_decode_path} does not exist and is needed by rtas_dump.\n"
        )
        sys.exit(1)
    if not os.access(re_decode_path, os.X_OK):
        sys.stderr.write(f"File {re_decode_path} is not executable.\n")
        sys.exit(1)


def handle_rtas_event(
    fh,
    base_args: list[str],
    event_no: int,
    initial_rtas_payload: str,
) -> None:
    """
    Read in the contents of an RTAS event and invoke rtas_event_decode on it.
    Mirrors the Perl sub handle_rtas_event().
    """

    re_decode_args = base_args + ["-n", str(event_no)]

    # create the pipe to rtas_event_decode
    proc = subprocess.Popen(
        [RE_DECODE] + re_decode_args,
        stdin=subprocess.PIPE,
        stdout=sys.stdout,
        stderr=sys.stderr,
        text=True,
    )

    rtas_str = initial_rtas_payload

    # Continue reading lines until we reach the end of the RTAS event
    for line in fh:
        # Split on 'RTAS' and append trailing data to match Perl behavior
        parts = line.split("RTAS", 1)
        if len(parts) == 2:
            crud, data = parts
            rtas_str += "RTAS" + data
        else:
            # No 'RTAS' in line, just append raw line
            rtas_str += line

        if "RTAS event end" in line:
            break

    # Send the accumulated event to the decoder
    try:
        assert proc.stdin is not None
        proc.stdin.write(rtas_str)
        proc.stdin.close()
    finally:
        proc.wait()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rtas_dump",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Dump the contents of an RTAS event, by default RTAS events\n"
            "are read from stdin unless the -f flag is used.\n\n"
            " -d         debug flag, passed through to rtas_event_decode\n"
            " -f <FILE>  dump the RTAS events from <FILE>\n"
            " -h         print this message and exit\n"
            " -n <NUM>   only dump RTAS event number <NUM>\n"
            " -v         dump the entire RTAS event, not just the header\n"
            " -w <width> set the output character width\n"
        ),
    )

    parser.add_argument("-h", "--help", action="store_true", dest="help_flag")
    parser.add_argument("-d", "--dump_raw", action="store_true", dest="debug_flag")
    parser.add_argument("-f", "--file", dest="filename", metavar="FILE")
    parser.add_argument("-n", dest="event_no", type=int)
    parser.add_argument("-w", dest="width", type=int)
    parser.add_argument("-v", "--verbose", action="count", default=0)

    args, extra = parser.parse_known_args(argv)
    if args.help_flag:
        usage_exit(parser)
    return args


def main(argv: list[str]) -> int:
    # Main
    script_dir = Path(__file__).resolve().parent
    pseries_platform = script_dir / "pseries_platform"

    # Source pseries platform and update environment
    sourced_env = source_env_from_pseries(pseries_platform)
    if sourced_env:
        os.environ.update(sourced_env)

    # Platform checks (mirrors Perl logic)
    platform = os.environ.get("platform")
    platform_unknown = os.environ.get("PLATFORM_UNKNOWN")
    platform_powernv = os.environ.get("PLATFORM_POWERNV")
    platform_name = os.environ.get("platform_name", "unknown")

    try:
        if platform is not None and (
            (platform_unknown is not None and platform == platform_unknown)
            or (platform_powernv is not None and platform == platform_powernv)
        ):
            print(
                f"rtas_dump: is not supported on the {platform_name} platform"
            )
            return 1
    except Exception:
        # If comparison fails for any reason, continue; behavior will mimic permissive Perl
        pass

    args = parse_args(argv)

    # Ensure decoder exists and is executable
    verify_re_decode_exists(RE_DECODE)

    # get a reference to our input filehandle
    fh = None
    close_input_file = False
    if args.filename:
        if os.path.exists(args.filename):
            fh = open(args.filename, "r", encoding="utf-8", errors="ignore")
            close_input_file = True
        else:
            print(f"File {args.filename} does not exist")
            return -1
    else:
        fh = sys.stdin

    # create the arg list to rtas_event_decode
    base_args: list[str] = []
    if args.debug_flag:
        base_args += ["-d"]
    if args.verbose and args.verbose > 0:
        # Perl uses -v multiple times based on count; pass through count
        base_args += ["-v"] * args.verbose
    if args.width:
        base_args += ["-w", str(args.width)]

    # Read input and process RTAS events
    for line in fh:
        if "RTAS event begin" in line:
            # found the beginning of an RTAS event, process it.
            # Extract event number like the Perl: split on 'RTAS:' then split on space
            crud_and_data = line.split("RTAS:", 1)
            if len(crud_and_data) == 2:
                crud, data = crud_and_data
                parts = data.split()
                this_event_no_str = parts[0] if parts else ""
                try:
                    this_event_no = int(this_event_no_str)
                except ValueError:
                    # If we cannot parse number, skip this event block
                    continue

                if args.event_no is not None and args.event_no != this_event_no:
                    # Skip this block by consuming lines until the end marker
                    for skip_line in fh:
                        if "RTAS event end" in skip_line:
                            break
                    continue

                initial_payload = "RTAS:" + data
                handle_rtas_event(fh, base_args, this_event_no, initial_payload)

    if close_input_file and fh is not None and fh is not sys.stdin:
        fh.close()

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


