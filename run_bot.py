import subprocess
import sys
import time
import logging
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "bot.log")
BOT_SCRIPT = os.path.join(SCRIPT_DIR, "bot.py")
PYTHON = sys.executable

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode="a",
)
logger = logging.getLogger("watchdog")


def kill_old():
    os.system(f'taskkill /F /IM python.exe /T >nul 2>&1')
    time.sleep(2)


def run_bot():
    kill_old()
    fail_count = 0
    while True:
        try:
            logger.info(f"Starting bot (fail #{fail_count})...")
            proc = subprocess.Popen(
                [PYTHON, BOT_SCRIPT],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=SCRIPT_DIR,
            )
            logger.info(f"Bot PID: {proc.pid}")
            proc.wait()
            code = proc.returncode
            logger.warning(f"Bot exited code={code}")
            fail_count += 1
        except Exception as e:
            logger.error(f"Exception: {e}")
            fail_count += 1

        delay = min(5 + fail_count * 2, 60)
        logger.info(f"Restart in {delay}s...")
        time.sleep(delay)


if __name__ == "__main__":
    run_bot()
