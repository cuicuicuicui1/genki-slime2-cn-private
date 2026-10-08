#!/usr/bin/env python3
"""Small, dependency-light NDS research helper for this project.

It never writes to the input ROM.  It can verify a ROM, list NitroFS files,
extract a named file, and unpack the project's simple resource archives.
"""
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path
from typing import Iterable

try:
    from ndspy.rom import NintendoDSRom
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: python -m pip install ndspy") from exc

ROOT = Path(__file__).resolve().parents[1]
NDS_DIR = ROOT / "tools" / "nds"
import sys
sys.path.insert(0, str(NDS_DIR))
try:
    from rs_format import unpack
except ImportError:
    unpack = None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_rom(path: Path) -> NintendoDSRom:
    if not path.is_file():
        raise SystemExit(f"ROM not found: {path}")
    return NintendoDSRom.fromFile(str(path))


def names(rom: NintendoDSRom) -> list[str]:
    return [rom.filenames.filenameOf(i) for i in range(len(rom.files))]


def cmd_info(args: argparse.Namespace) -> int:
    p = args.rom.resolve()
    digest = sha256(p)
    print(json.dumps({"path": str(p), "bytes": p.stat().st_size,
                      "sha256": digest, "expected_match":
                      None if not args.expected_sha256 else digest.lower() == args.expected_sha256.lower()},
                     ensure_ascii=False, indent=2))
    if args.expected_sha256 and digest.lower() != args.expected_sha256.lower():
        return 2
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    rom = load_rom(args.rom)
    rows = [{"id": i, "name": rom.filenames.filenameOf(i), "bytes": len(data)}
            for i, data in enumerate(rom.files)]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{row['id']:3d} {row['bytes']:8d} {row['name']}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    rom = load_rom(args.rom)
    all_names = names(rom)
    try:
        fid = all_names.index(args.file)
    except ValueError:
        raise SystemExit(f"NitroFS file not found: {args.file}")
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(rom.files[fid]))
    print(json.dumps({"file_id": fid, "name": args.file, "bytes": out.stat().st_size,
                      "sha256": sha256(out), "out": str(out.resolve())}, ensure_ascii=False, indent=2))
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    if unpack is None:
        raise SystemExit("rs_format.py is missing from tools/nds")
    rom = load_rom(args.rom)
    all_names = names(rom)
    try:
        fid = all_names.index(args.file)
    except ValueError:
        raise SystemExit(f"NitroFS file not found: {args.file}")
    members = unpack(bytes(rom.files[fid]))
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, member in enumerate(members):
        p = out / f"{i:03d}.bin"
        p.write_bytes(bytes(member.data))
        rows.append({"member": i, "offset": member.offset, "bytes": member.size,
                     "sha256": sha256(p), "path": str(p)})
    (out / "manifest.json").write_text(json.dumps({"file": args.file, "file_id": fid,
        "members": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"file": args.file, "members": len(rows), "out": str(out.resolve())}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sp = ap.add_subparsers(dest="command", required=True)
    p = sp.add_parser("info", help="verify SHA-256 and print ROM size")
    p.add_argument("--rom", type=Path, required=True); p.add_argument("--expected-sha256")
    p.set_defaults(func=cmd_info)
    p = sp.add_parser("list", help="list NitroFS files")
    p.add_argument("--rom", type=Path, required=True); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)
    p = sp.add_parser("extract", help="extract one NitroFS file")
    p.add_argument("--rom", type=Path, required=True); p.add_argument("--file", required=True); p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_extract)
    p = sp.add_parser("archive", help="unpack a u32-count/u32-offset/u32-size archive")
    p.add_argument("--rom", type=Path, required=True); p.add_argument("--file", required=True); p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_archive)
    args = ap.parse_args()
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
