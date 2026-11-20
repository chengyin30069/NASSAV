"""Provide a virtual display for Docker browser sessions."""

from contextlib import contextmanager
import os
from pathlib import Path
import select
import subprocess


@contextmanager
def browser_environment():
    environment = os.environ.copy()
    if environment.get("DISPLAY") or not Path("/.dockerenv").exists():
        yield environment
        return

    with subprocess.Popen(
        ["Xvfb", "-displayfd", "1", "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as display:
        try:
            ready, _, _ = select.select([display.stdout], [], [], 5)
            number = display.stdout.readline().strip() if ready else b""
            if not number.isdigit():
                raise OSError("Xvfb did not start")
            environment["DISPLAY"] = f":{number.decode('ascii')}"
            yield environment
        finally:
            if display.poll() is None:
                display.terminate()

