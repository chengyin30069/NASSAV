"""Run FlareSolverr and NASSAV in one container, cleaning up both on exit."""

import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


SOLVER_HEALTH = "http://127.0.0.1:8191/health"
SOLVER_START_TIMEOUT = 60


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> int:
    solver = subprocess.Popen(
        [sys.executable, "-u", "/app/flaresolverr.py"], cwd="/app"
    )
    downloader = None
    stopping = None

    def handle_signal(signum, _frame):
        nonlocal stopping
        stopping = signum
        if downloader is not None and downloader.poll() is None:
            downloader.send_signal(signum)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        deadline = time.monotonic() + SOLVER_START_TIMEOUT
        while time.monotonic() < deadline:
            if stopping is not None:
                return 128 + stopping
            if solver.poll() is not None:
                print("FlareSolverr exited before becoming ready", file=sys.stderr)
                return 1
            try:
                with urlopen(SOLVER_HEALTH, timeout=1) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError):
                time.sleep(0.5)
        else:
            print("FlareSolverr did not become ready within 60 seconds", file=sys.stderr)
            return 1

        downloader = subprocess.Popen([sys.executable, "main.py", *sys.argv[1:]], cwd="/NASSAV")
        status = downloader.wait()
        return 128 - status if status < 0 else status
    finally:
        stop_process(solver)


if __name__ == "__main__":
    sys.exit(main())
