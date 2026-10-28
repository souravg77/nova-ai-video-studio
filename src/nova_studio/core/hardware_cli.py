"""`nova-hw` — print the honest hardware report + profile selection.

Runnable headless so the report can be captured without the GUI (roadmap
section 6A: verify the real hardware first).
"""
from __future__ import annotations

import argparse
import json

from .. import config
from .capability import CapabilityManager, Profile
from .hardware import collect_hardware_report
from .preflight import check_dev_setup_space
from ..models.registry import default_registry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NOVA hardware report")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)

    report = collect_hardware_report()
    mgr = CapabilityManager(report, benchmarks=[], registry=default_registry())
    tier = mgr.detected_tier()
    eff, reason = mgr.select_profile(Profile.AUTO)
    cfg = config.default_config()
    disk = check_dev_setup_space(cfg.paths.workspace)

    if args.json:
        print(json.dumps({
            "report": report.model_dump(),
            "tier": int(tier),
            "auto_profile": eff.value,
            "reason": reason,
            "disk": disk.__dict__,
        }, indent=2))
        return 0

    print("=" * 70)
    print("NOVA AI Video Studio — Hardware Report")
    print("=" * 70)
    print(report.human_summary())
    print(f"\nInstalled RAM:        {report.physical_ram_gb} GB")
    print(f"Virtual/commit total: {round(report.virtual_memory_total_mb/1024,1)} GB "
          f"(page file is NOT RAM or VRAM)")
    print(f"Max dedicated VRAM:   {round(report.max_dedicated_vram_mb/1024,2)} GB")
    print(f"Backends available:   {', '.join(report.backends_available) or 'none'}")
    print(f"\nDetected tier:        {int(tier)} ({tier.name})")
    print(f"Auto profile:         {eff.value}")
    print(f"Reason:               {reason}")
    print(f"\nWorkspace:            {cfg.paths.workspace}")
    print(f"Disk preflight:       {disk.message}")
    if report.warnings:
        print("\nWarnings:")
        for w in report.warnings:
            print(f"  ! {w}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
