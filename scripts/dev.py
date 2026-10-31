#!/usr/bin/env python3
"""Run the whole stack locally without Docker: 8 internal geo services + the gateway (which also serves the website).

    python scripts/dev.py                # payment mode from .env (default: masumi)
    python scripts/dev.py --unpaid       # DEV ONLY: orders are marked UNPAID, no Cardano transaction
Logs go to state/logs/. Stop with Ctrl-C.
"""
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stack  # noqa: E402

ROOT = stack.ROOT


def load_dotenv(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unpaid", action="store_true", help="DEV ONLY: AGROLAND_PAYMENT_MODE=dev-unpaid")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--de-base", type=int, default=8000, help="first of 4 consecutive ports for the German geo services (audit, matcher, escrow, architect)")
    ap.add_argument("--in-base", type=int, default=9000, help="first of 4 consecutive ports for the Indian geo services")
    ap.add_argument("--state", default=str(ROOT / "state"))
    a = ap.parse_args()
    env = {**os.environ, **load_dotenv(ROOT / ".env")}
    state = Path(a.state)
    (state / "logs").mkdir(parents=True, exist_ok=True)
    keyfile = state / "dev-keys.env"
    k = stack.keys({**env, **load_dotenv(keyfile)})
    keyfile.write_text("".join(f"{x}={y}\n" for x, y in k.items()))
    os.chmod(keyfile, 0o600)
    de_ports = tuple(range(a.de_base, a.de_base + 4))
    in_ports = tuple(range(a.in_base, a.in_base + 4))
    procs = []
    try:
        for p in stack.geo_processes(state, k, de_ports=de_ports, in_ports=in_ports):
            log = open(state / "logs" / f"{p['name']}.log", "ab")
            procs.append(subprocess.Popen(p["args"], cwd=p["cwd"], env=p["env"], stdout=log, stderr=log))
            print(f"started {p['name']} on :{p['port']}")
        genv = {**env, **stack.gateway_env(k, state, a.port, de_ports=de_ports, in_ports=in_ports)}
        if a.unpaid:
            genv["AGROLAND_PAYMENT_MODE"] = "dev-unpaid"
            print("!! DEV-UNPAID MODE: orders are not paid, no Cardano transaction exists. Never use for the public demo.")
        genv["PYTHONPATH"] = str(ROOT / "gateway")
        gw = subprocess.Popen([sys.executable, "-m", "uvicorn", "agroland.main:app", "--host", env.get("AGROLAND_HOST", "127.0.0.1"), "--port", str(a.port)], env=genv, cwd=str(ROOT))
        procs.append(gw)
        print(f"AgroLand on http://127.0.0.1:{a.port}")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("a process exited; check state/logs/")
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.send_signal(signal.SIGTERM)
        for p in procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
