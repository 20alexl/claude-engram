"""Correction gate against the neutral 220-prompt corpus.

The miner stores a "USER PREFERENCE" when a short reply after work has the
shape of a correction (mining/decision_gate.looks_like_correction). This
bench scores that gate on tests/bench_decision_capture_v2.py's corpus,
which no session wrote: positives are its negation and convention
decisions ("don't use var anymore", "always validate at the boundary"),
negatives every prompt labeled not-a-decision (questions, tasks, commands,
bug reports, praise/status, exploratory, ambiguous). The decision gate is
scored the same way on the whole corpus.

Run: venv/Scripts/python.exe tests/bench_correction_gate.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CLAUDE_ENGRAM_NO_DAEMON", "1")

from claude_engram.mining.decision_gate import looks_like_correction, looks_like_decision  # noqa: E402


def _corpus():
    spec = importlib.util.spec_from_file_location("bench_v2", ROOT / "tests" / "bench_decision_capture_v2.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CORPUS


def _prf(fn, pos, neg):
    tp = sum(1 for p in pos if fn(p))
    fp = sum(1 for p in neg if fn(p))
    fn_ = len(pos) - tp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn_) if tp + fn_ else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return tp, fp, fn_, prec, rec, f1


def main() -> int:
    corpus = _corpus()
    neg = [p for p, is_dec, _c, _d in corpus if not is_dec]
    corr_pos = [p for p, is_dec, cat, _d in corpus if is_dec and cat in ("negation", "convention")]
    dec_pos = [p for p, is_dec, _c, _d in corpus if is_dec]
    ok = True
    print(f"{'gate':22s} {'pos':>4} {'neg':>4} {'tp':>4} {'fp':>4} {'fn':>4}   prec    rec     f1   floor")
    for name, fn, pos, floor_p, floor_r in (
        # Floors sit a little under what the tuned gates score (2026-09-22:
        # correction 0.97 / 0.80, decision 1.00 / 0.95), so a regression
        # shows and a small corpus edit does not.
        ("correction gate", looks_like_correction, corr_pos, 0.85, 0.75),
        ("decision gate", looks_like_decision, dec_pos, 0.90, 0.90),
    ):
        tp, fp, fn_, p, r, f = _prf(fn, pos, neg)
        good = p >= floor_p and r >= floor_r
        ok = ok and good
        print(f"{name:22s} {len(pos):4d} {len(neg):4d} {tp:4d} {fp:4d} {fn_:4d}   {p:.2f}   {r:.2f}   {f:.2f}   p>={floor_p} r>={floor_r} {'PASS' if good else 'FAIL'}")
        if "--verbose" in sys.argv:
            for x in neg:
                if fn(x):
                    print("     FP:", x[:90])
            for x in pos:
                if not fn(x):
                    print("     FN:", x[:90])
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
