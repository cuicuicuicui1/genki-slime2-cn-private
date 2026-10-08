#!/usr/bin/env python3
"""Lint translation JSON without touching a ROM.

The accepted project files are arrays of objects containing id/source/translation.
The checker intentionally does not judge translation quality; it catches structural
mistakes that can cause a crash, stuck message, bad speaker header or page drift.
"""
from __future__ import annotations
import argparse, collections, json, re, sys
from pathlib import Path

CONTROL_RE = re.compile(r"<[^>]+>")
SPEAKER_RE = re.compile(r"<SPEAKER>(.*?)<SPEAKER>", re.S)


def load(path: Path):
    with path.open(encoding="utf-8-sig") as f:
        obj = json.load(f)
    if not isinstance(obj, list):
        raise ValueError(f"expected JSON array: {path}")
    return obj


def controls(text: str) -> list[str]:
    return CONTROL_RE.findall(text or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("translations", type=Path)
    ap.add_argument("--source", type=Path, help="optional source records JSON")
    ap.add_argument("--json-report", type=Path)
    args = ap.parse_args()
    rows = load(args.translations)
    source = {r.get("id"): r for r in load(args.source)} if args.source else {}
    errors: list[dict] = []
    seen: set[str] = set()
    stats = collections.Counter()
    for n, row in enumerate(rows):
        rid = row.get("id")
        if not rid: errors.append({"row": n, "error": "missing id"}); continue
        if rid in seen: errors.append({"id": rid, "error": "duplicate id"})
        seen.add(rid)
        src = row.get("source", source.get(rid, {}).get("source", "")) or ""
        dst = row.get("translation")
        if not isinstance(dst, str) or not dst.strip():
            errors.append({"id": rid, "error": "empty translation"}); continue
        if source and rid not in source:
            errors.append({"id": rid, "error": "not found in supplied source corpus"})
        # Compare control-code multisets, but allow deliberate text changes.
        a, b = collections.Counter(controls(src)), collections.Counter(controls(dst))
        if a != b:
            errors.append({"id": rid, "error": "control codes differ", "source": dict(a), "translation": dict(b)})
        if dst.count("<SPEAKER>") not in (0, 2):
            errors.append({"id": rid, "error": "speaker delimiter count is not 0 or 2"})
        if "<END>" in src and "<END>" not in dst:
            errors.append({"id": rid, "error": "missing END"})
        if "<PAGE>" in src and dst.count("<PAGE>") != src.count("<PAGE>"):
            errors.append({"id": rid, "error": "page count changed"})
        stats["records"] += 1
        stats["cjk_chars"] += sum(1 for c in dst if "\u3400" <= c <= "\u9fff")
        stats["japanese_kana"] += sum(1 for c in dst if "\u3040" <= c <= "\u30ff")
    report = {"translation_file": str(args.translations), "source_file": str(args.source) if args.source else None,
              "stats": dict(stats), "errors": errors, "passed": not errors}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return 0 if not errors else 1

if __name__ == "__main__":
    raise SystemExit(main())
