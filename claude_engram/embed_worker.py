"""Transient bulk-embedding worker.

Big embedding jobs (bootstrap re-embeds, model-change rebuilds, large
live-tick backlogs, memory-store sweeps) run here instead of the resident
scorer daemon: a short-lived process loads the encoder on the bulk device
(GPU when available), encodes ONE job, writes the vectors, and exits.
Process exit is the only way to fully release a CUDA context, so the GPU
is borrowed for seconds and returned — the resident daemon stays on cpu
and parks nothing on the GPU.

Worker protocol:
    python -m claude_engram.embed_worker <in.json> <out.npy>
    in.json:  {"texts": [...]}
    out.npy:  float32 [n, dim], normalized
    exit 0 ok | 1 failure | 3 no GPU (caller should use the daemon instead)

Parent API: embed_texts_bulk(texts) -> list[list[float]] | None.
None on ANY failure or when no GPU exists — callers fall back to their
existing daemon path. bulk_threshold() is the job size where spawning a
worker beats slicing through the daemon (env CLAUDE_ENGRAM_GPU_BULK_MIN,
default 512).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

GPU_BULK_MIN_DEFAULT = 512


def bulk_threshold() -> int:
    raw = os.environ.get("CLAUDE_ENGRAM_GPU_BULK_MIN", "").strip()
    try:
        return max(1, int(raw)) if raw else GPU_BULK_MIN_DEFAULT
    except ValueError:
        return GPU_BULK_MIN_DEFAULT


def embed_texts_bulk(texts: list) -> "list | None":
    """Run one big embed job in a transient worker process.

    Returns vectors aligned with ``texts``, or None on any failure — the
    caller falls back to the daemon path. Never raises. The worker itself
    refuses (exit 3) when there is no GPU: a CPU worker is just a slower
    daemon, so the fallback is strictly better there.
    """
    if not texts:
        return []
    tmpdir = ""
    try:
        import numpy as np

        tmpdir = tempfile.mkdtemp(prefix="engram_bulk_")
        in_path = os.path.join(tmpdir, "in.json")
        out_path = os.path.join(tmpdir, "out.npy")
        with open(in_path, "w", encoding="utf-8") as f:
            json.dump({"texts": [str(t) for t in texts]}, f)

        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        # Model load is the fixed cost (~5-10s); GPU encode is ~1s per few
        # thousand texts. The margin covers a slow disk-cold first load;
        # the cap keeps a hung worker from stalling the miner.
        timeout = min(900, 120 + len(texts) // 50)
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_engram.embed_worker",
                in_path,
                out_path,
            ],
            timeout=timeout,
            **kwargs,
        )
        if proc.returncode != 0:
            return None
        arr = np.load(out_path)
        if arr.ndim != 2 or arr.shape[0] != len(texts):
            return None
        return [row.tolist() for row in arr]
    except Exception:
        return None
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: embed_worker <in.json> <out.npy>", file=sys.stderr)
        return 2
    in_path, out_path = sys.argv[1], sys.argv[2]
    try:
        from claude_engram.embed_config import (
            load_sentence_transformer,
            resolve_bulk_device,
        )

        device = resolve_bulk_device()
        if not device.startswith(("cuda", "mps")):
            # No GPU: a worker adds nothing over the daemon. Fail fast so
            # the parent falls back before paying a model load for nothing.
            print("no GPU available - declining bulk job", file=sys.stderr)
            return 3

        import numpy as np

        with open(in_path, encoding="utf-8") as f:
            texts = json.load(f)["texts"]
        model = load_sentence_transformer(device=device)
        embs = model.encode(texts, normalize_embeddings=True, batch_size=256)
        np.save(out_path, np.asarray(embs, dtype=np.float32))
        print(f"embedded {len(texts)} texts on {model.device}", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"embed worker failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
