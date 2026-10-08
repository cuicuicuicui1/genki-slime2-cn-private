#!/usr/bin/env python3
"""Read-only safety checks for NDS build candidates.

This tool never modifies either ROM. It reports NitroFS file changes and can
fail a build when files outside an explicit allowlist changed. It is intended
for reviewing a candidate before sharing it with testers.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

try:
    from ndspy.rom import NintendoDSRom
    from ndspy import fnt
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: python -m pip install ndspy") from exc


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rom(path: Path) -> NintendoDSRom:
    if not path.is_file():
        raise SystemExit(f"ROM not found: {path}")
    return NintendoDSRom.fromFile(str(path))


def names(r: NintendoDSRom) -> list[str]:
    return [r.filenames.filenameOf(i) for i in range(len(r.files))]


def identity(r: NintendoDSRom) -> dict:
    return {
        "arm9_sha256": hashlib.sha256(bytes(r.arm9)).hexdigest(),
        "arm7_sha256": hashlib.sha256(bytes(r.arm7)).hexdigest(),
        "arm9_overlay_table_sha256": hashlib.sha256(bytes(r.arm9OverlayTable)).hexdigest(),
        "arm7_overlay_table_sha256": hashlib.sha256(bytes(r.arm7OverlayTable)).hexdigest(),
        "fnt_sha256": hashlib.sha256(bytes(fnt.save(r.filenames))).hexdigest(),
        "file_count": len(r.files),
    }


def cmd_info(args: argparse.Namespace) -> int:
    p = args.rom.resolve()
    digest = sha256(p)
    result = {"path": str(p), "bytes": p.stat().st_size, "sha256": digest}
    if args.expected_sha256:
        result["expected_sha256"] = args.expected_sha256.lower()
        result["expected_match"] = digest.lower() == args.expected_sha256.lower()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not args.expected_sha256 or result["expected_match"] else 2


def cmd_diff(args: argparse.Namespace) -> int:
    before = rom(args.before)
    after = rom(args.after)
    before_names, after_names = names(before), names(after)
    same_identity = identity(before) == identity(after)
    changed = []
    max_files = max(len(before.files), len(after.files))
    for i in range(max_files):
        old = bytes(before.files[i]) if i < len(before.files) else None
        new = bytes(after.files[i]) if i < len(after.files) else None
        if old != new:
            changed.append({
                "id": i,
                "before_name": before_names[i] if i < len(before_names) else None,
                "after_name": after_names[i] if i < len(after_names) else None,
                "before_bytes": None if old is None else len(old),
                "after_bytes": None if new is None else len(new),
                "before_sha256": None if old is None else hashlib.sha256(old).hexdigest(),
                "after_sha256": None if new is None else hashlib.sha256(new).hexdigest(),
            })
    allow = set(args.allow_file or [])
    allowed_ids = set()
    for item in allow:
        try:
            allowed_ids.add(int(item, 0))
        except ValueError:
            pass
    unexpected = [row for row in changed if row["id"] not in allowed_ids and
                  row.get("before_name") not in allow and row.get("after_name") not in allow]
    result = {
        "before": str(args.before.resolve()), "after": str(args.after.resolve()),
        "before_sha256": sha256(args.before), "after_sha256": sha256(args.after),
        "same_rom_identity": same_identity, "changed_files": changed,
        "allowlist": sorted(allow), "unexpected_changes": unexpected,
        "passed": not unexpected and same_identity,
    }
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sp = ap.add_subparsers(dest="command", required=True)
    p = sp.add_parser("info", help="print a ROM SHA-256 and size")
    p.add_argument("--rom", type=Path, required=True)
    p.add_argument("--expected-sha256")
    p.set_defaults(func=cmd_info)
    p = sp.add_parser("diff", help="report NitroFS changes and enforce an allowlist")
    p.add_argument("--before", type=Path, required=True)
    p.add_argument("--after", type=Path, required=True)
    p.add_argument("--allow-file", action="append", help="file ID (decimal/0x...) or NitroFS name; repeatable")
    p.add_argument("--json-report", type=Path)
    p.set_defaults(func=cmd_diff)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
