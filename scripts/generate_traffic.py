"""Send simulated shop traffic to the shop database and print what customers experience.

Usage:
    python scripts/generate_traffic.py                       # 4 users, normal traffic, until Ctrl+C
    python scripts/generate_traffic.py --users 20 --mode flash_sale
    python scripts/generate_traffic.py --seconds 60 --seed 42
"""

import argparse
import time

from shopsim.actions import MODES
from shopsim.settings import load_shop_db_url
from shopsim.traffic import TrafficGenerator


def print_summary(traffic: TrafficGenerator) -> None:
    print(f"\n{time.strftime('%H:%M:%S')}  users={traffic.running_users}  mode={traffic.mode}")
    print(f"  {'action':<18}{'calls':>8}{'errors':>8}{'avg ms':>10}{'p95 ms':>10}")
    for s in traffic.summary():
        print(f"  {s.name:<18}{s.calls:>8}{s.errors:>8}{s.avg_ms:>10.2f}{s.p95_ms:>10.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulated shop traffic")
    parser.add_argument("--users", type=int, default=4, help="number of simulated users")
    parser.add_argument("--mode", choices=MODES, default="normal")
    parser.add_argument("--seconds", type=int, default=0, help="stop after this many seconds (0 = run until Ctrl+C)")
    parser.add_argument("--pause-ms", type=int, default=50, help="pause between requests per user")
    parser.add_argument("--seed", type=int, default=None, help="make the random traffic repeatable")
    args = parser.parse_args()

    traffic = TrafficGenerator(load_shop_db_url(), pause_ms=args.pause_ms, seed=args.seed)
    traffic.set_mode(args.mode)
    traffic.start(args.users)
    print(f"Started {args.users} users ({args.mode}). Ctrl+C to stop.")

    started = time.time()
    try:
        while args.seconds == 0 or time.time() - started < args.seconds:
            time.sleep(5)
            print_summary(traffic)
    except KeyboardInterrupt:
        pass
    finally:
        traffic.stop()
        print("\nStopped.")
        print_summary(traffic)


if __name__ == "__main__":
    main()