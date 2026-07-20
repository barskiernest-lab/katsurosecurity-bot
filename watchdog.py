import subprocess
import sys
import time
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_SCRIPT = os.path.join(SCRIPT_DIR, "bot.py")
PYTHON = sys.executable
LOG = os.path.join(SCRIPT_DIR, "watchdog.log")

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")

def run():
    log("Watchdog started")
    while True:
        log("Starting bot...")
        try:
            proc = subprocess.Popen(
                [PYTHON, BOT_SCRIPT],
                cwd=SCRIPT_DIR,
                stdout=open(os.path.join(SCRIPT_DIR, "bot_stdout.log"), "a"),
                stderr=subprocess.STDOUT,
            )
            log(f"Bot PID: {proc.pid}")
            proc.wait()
            log(f"Bot exited code={proc.returncode}")
        except Exception as e:
            log(f"Error: {e}")
        log("Restart in 5s...")
        time.sleep(5)

if __name__ == "__main__":
    run()
