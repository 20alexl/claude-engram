"""
Persistent embedding/scorer server.

Keeps the configured sentence-transformers model loaded in memory and serves
scoring/embedding requests via TCP localhost. Auto-starts on first hook call,
auto-exits after 30 min idle. The model is set by embed_config (default
BAAI/bge-base-en-v1.5; all-MiniLM-L6-v2 is the light option at ~90MB RAM).

Latency: ~5-25ms per request (vs ~500ms+ cold start without server)

Protocol: JSON lines over TCP
  Request:  {"text": "let's use Redis"}\n
  Response: {"score": 0.85, "text": "let's use redis"}\n
"""

import json
import os
import re
import signal
import socket
import sys
import time
import threading
from pathlib import Path

from claude_engram.embed_config import embed_signature

# How long to stay alive without requests (seconds)
IDLE_TIMEOUT = int(
    os.environ.get("CLAUDE_ENGRAM_SCORER_TIMEOUT", "1800")
)  # 30 min default

# Where to store the port number so hooks can find us. MODEL_FILE records the
# embedding signature the running server loaded: a client whose configured
# model differs must not use this server (vectors from two models share no
# space), so it replaces it instead. Honors CLAUDE_ENGRAM_DIR so isolated
# storage gets an isolated server (and tests never touch the real one).


def _storage_root() -> Path:
    override = os.environ.get("CLAUDE_ENGRAM_DIR", "")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude_engram"


PORT_FILE = _storage_root() / "scorer_port"
PID_FILE = _storage_root() / "scorer_pid"
MODEL_FILE = _storage_root() / "scorer_model"
DEVICE_FILE = _storage_root() / "scorer_device"


def _load_model_and_templates():
    """Load the configured embedding model and template embeddings."""
    import numpy as np

    from claude_engram.embed_config import load_sentence_transformer
    from claude_engram.hooks.intent import _get_or_build_template_cache

    model = load_sentence_transformer()

    # _get_or_build_template_cache is signature-stamped: it rebuilds the
    # template embeddings automatically when the configured model changed.
    cache = _get_or_build_template_cache()
    if cache is None:
        raise RuntimeError("could not build decision template cache")
    decision_embs = np.array(cache["decision_embeddings"])
    non_decision_embs = np.array(cache["non_decision_embeddings"])

    return model, decision_embs, non_decision_embs


def _score_text(text, model, decision_embs, non_decision_embs):
    """Score a single text against templates. Returns (score, extracted_text)."""
    import numpy as np
    from claude_engram.hooks.intent import DECISION_THRESHOLD, AMBIGUITY_MARGIN

    if len(text.strip()) < 15:
        return 0.0, ""

    sentences = re.split(r"(?<=[.!])\s+|\n+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 15]
    if not sentences:
        sentences = [text.strip()]

    best_score = 0.0
    best_text = ""

    for sentence in sentences[:5]:
        emb = model.encode([sentence], normalize_embeddings=True)
        d_sims = np.dot(decision_embs, emb.T).flatten()
        nd_sims = np.dot(non_decision_embs, emb.T).flatten()

        best_d = float(np.max(d_sims))
        best_nd = float(np.max(nd_sims))

        if best_d >= DECISION_THRESHOLD and (best_d - best_nd) >= AMBIGUITY_MARGIN:
            score = min((best_d - 0.3) / 0.5, 1.0)
            if score > best_score:
                best_score = score
                best_text = sentence[:150]

    return best_score, best_text


class _ModelHolder:
    """The embedding model, loaded lazily in a background thread so the
    server can bind and serve hook events immediately. Embedding/scoring
    requests wait on `ready`; hook events never touch it."""

    def __init__(self):
        self.ready = threading.Event()
        self.model = None
        self.decision_embs = None
        self.non_decision_embs = None

    def load(self):
        try:
            (
                self.model,
                self.decision_embs,
                self.non_decision_embs,
            ) = _load_model_and_templates()
            try:
                # Breadcrumb for status display: the device actually in use
                # (cuda vs cpu), readable without importing torch.
                DEVICE_FILE.write_text(str(self.model.device))
            except Exception:
                pass
            print(f"Model loaded on {self.model.device}.", file=sys.stderr)
        except Exception as e:
            print(f"Model load failed: {e}", file=sys.stderr)
        finally:
            self.ready.set()

    def wait(self, timeout: float = 20.0) -> bool:
        self.ready.wait(timeout)
        return self.model is not None


# Hook events the daemon may run in-process. Lifecycle events (session
# start/end, stop, compaction) stay in their own processes: they spawn
# miners and servers and are rare enough that warm imports buy nothing.
_HOOK_EVENTS = {
    "pre_edit_json",
    "post_edit_json",
    "bash_json",
    "prompt_json",
    "pre_read_json",
    "tool_failure_json",
}

# remind's stdin cache / session id / CLAUDE_PROJECT_DIR are per-event
# process state; under the daemon they're module globals, so dispatch is
# serialized. Handlers are ~5-30ms warm — queueing beats races.
_HOOK_LOCK = threading.Lock()


def _serve_hook_event(request: dict) -> dict:
    """Run a remind.py hook dispatch in-process. The entire win of the
    daemon: a cold hook process pays interpreter start + imports before any
    work; here only the work remains."""
    hook_type = str(request.get("hook_event", ""))
    if hook_type not in _HOOK_EVENTS:
        return {"error": f"unsupported hook_event {hook_type!r}"}
    payload = request.get("stdin", "") or ""
    env = request.get("env") if isinstance(request.get("env"), dict) else {}

    import contextlib
    import io

    with _HOOK_LOCK:
        from claude_engram.hooks import remind

        old_argv = sys.argv
        old_proj = os.environ.get("CLAUDE_PROJECT_DIR")
        buf = io.StringIO()
        try:
            cpd = env.get("CLAUDE_PROJECT_DIR", "")
            if cpd:
                os.environ["CLAUDE_PROJECT_DIR"] = cpd
            else:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            remind._stdin_cache = payload
            remind._session_id = ""
            sys.argv = ["remind", hook_type]
            with contextlib.redirect_stdout(buf):
                try:
                    remind.main()
                except SystemExit:
                    pass
        except Exception as e:
            return {"error": str(e)[:200]}
        finally:
            sys.argv = old_argv
            if old_proj is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = old_proj
            remind._stdin_cache = None
            remind._session_id = ""
        return {"output": buf.getvalue()}


def _handle_client(conn, holder):
    """Handle a single client connection."""
    try:
        conn.settimeout(5.0)
        data = b""
        while b"\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk

        if not data:
            return

        request = json.loads(data.decode("utf-8").strip())

        if "hook_event" in request:
            response = json.dumps(_serve_hook_event(request)) + "\n"
            conn.sendall(response.encode("utf-8"))
            return

        # Everything below needs the model; wait out a still-loading one.
        if not holder.wait():
            conn.sendall(b'{"error": "model unavailable"}\n')
            return
        model = holder.model
        decision_embs = holder.decision_embs
        non_decision_embs = holder.non_decision_embs

        if "embed_batch" in request:
            # Batch embedding: encode all texts in one model call. GPU takes
            # much larger batches without breaking a sweat; CPU keeps 64.
            texts = request["embed_batch"]
            if texts:
                on_gpu = str(getattr(model, "device", "cpu")).startswith(
                    ("cuda", "mps")
                )
                embs = model.encode(
                    texts,
                    normalize_embeddings=True,
                    batch_size=256 if on_gpu else 64,
                )
                response = json.dumps({"embeddings": embs.tolist()}) + "\n"
            else:
                response = json.dumps({"embeddings": []}) + "\n"
            conn.sendall(response.encode("utf-8"))
        elif "embed" in request:
            # Single embedding request: return raw vector
            text = request["embed"]
            emb = model.encode([text], normalize_embeddings=True)
            response = json.dumps({"embedding": emb[0].tolist()}) + "\n"
            conn.sendall(response.encode("utf-8"))
        else:
            # Decision scoring request
            text = request.get("text", "")
            score, extracted = _score_text(
                text, model, decision_embs, non_decision_embs
            )
            response = json.dumps({"score": score, "text": extracted}) + "\n"
            conn.sendall(response.encode("utf-8"))
    except Exception:
        try:
            conn.sendall(json.dumps({"score": 0.0, "text": ""}).encode("utf-8") + b"\n")
        except Exception:
            pass
    finally:
        conn.close()


def serve():
    """Run the scorer/hook server. Blocks until idle timeout.

    Binds and announces itself BEFORE loading the model: hook events are
    served from the first millisecond, while embedding/scoring requests wait
    on the background model load (and degrade to their callers' fallbacks
    until it finishes)."""
    sig = embed_signature()

    # Single-instance check: two sessions racing to spawn used to leave an
    # orphan daemon (last PORT_FILE writer wins, the loser idles 30 min
    # holding a loaded model). If a live server with our exact signature
    # already owns PORT_FILE, this process has nothing to add.
    if _another_server_alive():
        print("Matching scorer already running - exiting.", file=sys.stderr)
        return

    # Bind to any available port on localhost
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    port = server_sock.getsockname()[1]
    server_sock.listen(8)

    # Write port, PID, and model signature so hooks can find and validate us
    PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PORT_FILE.write_text(str(port))
    PID_FILE.write_text(str(os.getpid()))
    MODEL_FILE.write_text(sig)
    # Clear the hook_client nudge marker: we're up, nudges may flow again
    (_storage_root() / "scorer_starting").unlink(missing_ok=True)

    holder = _ModelHolder()
    print(f"Loading embedding model {sig} in background...", file=sys.stderr)
    threading.Thread(target=holder.load, daemon=True).start()

    def _warm_hook_imports():
        # Pre-import the hook dispatcher so the first hook_event doesn't pay
        # (or race) the import under the dispatch lock.
        try:
            with _HOOK_LOCK:
                from claude_engram.hooks import remind  # noqa: F401
        except Exception:
            pass

    threading.Thread(target=_warm_hook_imports, daemon=True).start()

    print(
        f"Scorer server listening on 127.0.0.1:{port} (PID {os.getpid()})",
        file=sys.stderr,
    )

    last_activity = time.time()

    # Handle SIGTERM gracefully
    def _shutdown(signum, frame):
        server_sock.close()
        _cleanup()
        sys.exit(0)

    try:
        signal.signal(signal.SIGTERM, _shutdown)
    except (OSError, ValueError):
        pass  # Windows doesn't support SIGTERM in all contexts

    try:
        while True:
            server_sock.settimeout(60.0)  # Check idle every 60s
            try:
                conn, addr = server_sock.accept()
                last_activity = time.time()
                # Handle in thread for concurrency
                t = threading.Thread(
                    target=_handle_client,
                    args=(conn, holder),
                    daemon=True,
                )
                t.start()
            except socket.timeout:
                if time.time() - last_activity > IDLE_TIMEOUT:
                    print("Idle timeout — shutting down.", file=sys.stderr)
                    break
    finally:
        server_sock.close()
        _cleanup()


def _cleanup():
    """Remove port/pid/model/device files on shutdown."""
    for f in (PORT_FILE, PID_FILE, MODEL_FILE, DEVICE_FILE):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass


def _another_server_alive() -> bool:
    """A live, connectable server with our exact signature owns PORT_FILE."""
    try:
        if not (PORT_FILE.exists() and _server_model_matches()):
            return False
        port = int(PORT_FILE.read_text().strip())
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except Exception:
        return False


def _server_model_matches() -> bool:
    """Does the running server's embedding model match the configured one?
    A missing MODEL_FILE means a pre-stamping server, which always ran the
    original encoder — so it only counts as a match when that legacy model
    is still the configured one."""
    from claude_engram.embed_config import LEGACY_SIGNATURE

    current = embed_signature()
    if MODEL_FILE.exists():
        try:
            return MODEL_FILE.read_text().strip() == current
        except Exception:
            return False
    return current == LEGACY_SIGNATURE


def _stop_running_server():
    """Terminate a running scorer server (used when the model config changed).
    Best-effort: on failure the stale files are removed so a new server starts
    and the old one dies at its idle timeout."""
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.2)
    except Exception:
        pass
    _cleanup()


def is_server_running() -> bool:
    """Check if the scorer server is running WITH the configured model.
    A reachable server loaded with a different model is replaced — using it
    would mix vector spaces."""
    if not PORT_FILE.exists() or not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        port = int(PORT_FILE.read_text().strip())
        # Try to connect
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        sock.connect(("127.0.0.1", port))
        sock.close()
    except Exception:
        # Stale files — clean up
        _cleanup()
        return False
    if not _server_model_matches():
        _stop_running_server()
        return False
    return True


def start_server_background():
    """
    Start the scorer server as a detached background process.

    Fire-and-forget: spawns the process and returns immediately.
    Does NOT wait for the server to be ready — the first hook call
    that tries the server will either connect (ready) or fall back
    to regex scoring (still loading). This avoids blocking the
    SessionStart hook (2s timeout budget).
    """
    if is_server_running():
        return True

    import subprocess
    import platform

    try:
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if platform.system() == "Windows":
            # CREATE_NO_WINDOW prevents any console window from appearing
            CREATE_NO_WINDOW = 0x08000000
            kwargs["creationflags"] = CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen(
            [sys.executable, "-m", "claude_engram.hooks.scorer_server"],
            **kwargs,
        )
        return True  # Fire-and-forget — don't wait
    except Exception:
        return False


def score_via_server(text: str) -> tuple[float, str]:
    """
    Score text by connecting to the persistent server.
    Auto-starts server if not running. Returns (score, extracted_text) or (0.0, "") if unavailable.
    """
    if not _ensure_server():
        return 0.0, ""

    try:
        port = int(PORT_FILE.read_text().strip())
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(("127.0.0.1", port))

        request = json.dumps({"text": text}) + "\n"
        sock.sendall(request.encode("utf-8"))

        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        sock.close()
        result = json.loads(data.decode("utf-8").strip())
        return result.get("score", 0.0), result.get("text", "")
    except Exception:
        return 0.0, ""


_auto_start_attempted = False


def _ensure_server() -> bool:
    """Auto-start scorer server if not running. Returns True if server is available."""
    global _auto_start_attempted
    if PORT_FILE.exists():
        if _server_model_matches():
            _auto_start_attempted = False
            return True
        # Config changed under a running server: replace it.
        _stop_running_server()
    if _auto_start_attempted:
        return False
    _auto_start_attempted = True
    start_server_background()
    for _ in range(20):
        if PORT_FILE.exists():
            return True
        time.sleep(0.5)
    return False


def embed_via_server(text: str) -> list[float]:
    """
    Get embedding vector for text from the persistent server.
    Auto-starts server if not running. Returns a model-dim list or empty list.
    """
    if not _ensure_server():
        return []

    try:
        port = int(PORT_FILE.read_text().strip())
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(("127.0.0.1", port))

        request = json.dumps({"embed": text}) + "\n"
        sock.sendall(request.encode("utf-8"))

        data = b""
        while b"\n" not in data:
            chunk = sock.recv(8192)
            if not chunk:
                break
            data += chunk

        sock.close()
        result = json.loads(data.decode("utf-8").strip())
        return result.get("embedding", [])
    except Exception:
        return []


def embed_batch_via_server(texts: list[str]) -> list[list[float]]:
    """
    Get embeddings for multiple texts in a single TCP call.

    The server encodes all texts in one model.encode() call with batch_size=64,
    which is much faster than individual calls (1 roundtrip vs N roundtrips).
    Returns list of model-dim vectors. Empty list entries for failures.
    """
    if not texts:
        return []
    if not _ensure_server():
        return [[] for _ in texts]

    try:
        port = int(PORT_FILE.read_text().strip())
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30.0)  # Batch can take longer
        sock.connect(("127.0.0.1", port))

        request = json.dumps({"embed_batch": [t[:500] for t in texts]}) + "\n"
        sock.sendall(request.encode("utf-8"))

        # Batch responses can be large (~3KB * N texts)
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk

        sock.close()
        result = json.loads(data.decode("utf-8").strip())
        return result.get("embeddings", [[] for _ in texts])
    except Exception:
        return [[] for _ in texts]


if __name__ == "__main__":
    serve()
