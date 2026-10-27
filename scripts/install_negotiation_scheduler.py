#!/usr/bin/env python3
"""Install the per-listing Trove scheduler as a user LaunchAgent."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.trove.negotiation-scheduler"
CONFIG = ROOT / "config" / "negotiation_scheduler.json"
SCHEDULER = ROOT / "scripts" / "negotiation_due_scheduler.py"
LOG_DIR = ROOT / "logs"


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 Trove 逐商品谈价调度器")
    parser.add_argument("--thread-id", help="覆盖配置中的 Codex 线程 ID")
    parser.add_argument("--python", default=sys.executable, help="调度器使用的 Python")
    parser.add_argument("--dry-run", action="store_true", help="只输出 LaunchAgent 配置")
    args = parser.parse_args()

    codex_path = shutil.which("codex")
    if not codex_path:
        raise SystemExit("codex executable not found")

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if args.thread_id:
        config["thread_id"] = args.thread_id
        CONFIG.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not config.get("thread_id"):
        raise SystemExit("thread_id is required")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents / f"{LABEL}.plist"
    payload = {
        "Label": LABEL,
        "ProgramArguments": [str(Path(args.python).resolve()), str(SCHEDULER)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "StartInterval": 60,
        "ProcessType": "Background",
        "StandardOutPath": str(LOG_DIR / "negotiation-scheduler.launchd.out.log"),
        "StandardErrorPath": str(LOG_DIR / "negotiation-scheduler.launchd.err.log"),
        "EnvironmentVariables": {
            "HOME": str(Path.home()),
            "PATH": os.pathsep.join(
                [
                    str(Path(codex_path).parent),
                    "/opt/homebrew/bin",
                    "/usr/local/bin",
                    "/usr/bin",
                    "/bin",
                ]
            ),
            "CODEX_HOME": str(Path.home() / ".codex"),
        },
    }
    plist_bytes = plistlib.dumps(payload, fmt=plistlib.FMT_XML)
    if args.dry_run:
        sys.stdout.buffer.write(plist_bytes)
        return 0

    temporary = plist_path.with_suffix(".plist.tmp")
    temporary.write_bytes(plist_bytes)
    temporary.replace(plist_path)

    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(plist_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    result = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())
    subprocess.run(
        ["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"],
        text=True,
        capture_output=True,
        check=False,
    )
    print(f"installed {LABEL}: {plist_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
