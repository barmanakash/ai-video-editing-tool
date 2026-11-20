"""Run from the project root:  python scripts/check_environment.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.system_check import run_checks  # noqa: E402


def main() -> int:
    report = run_checks()
    print(json.dumps(report, indent=2))
    print()
    if report["ok"]:
        print("[OK] Environment is ready for Phase 1.")
        return 0
    print("[!] Problems found:")
    for issue in report["issues"]:
        print(f"  - {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
