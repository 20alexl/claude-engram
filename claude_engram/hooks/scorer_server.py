"""
Persistent AllMiniLM scorer server.

Keeps the model loaded in memory and serves scoring requests via TCP localhost.
Auto-starts on first hook call, auto-exits after 30 min idle.

Memory: ~90MB (AllMiniLM model)
Latency: ~5ms per request (vs ~500ms cold start without server)

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

# How long to stay alive without requests (seconds)
IDLE_TIMEOUT = int(
    os.environ.get("CLAUDE_ENGRAM_SCORER_TIMEOUT", "1800")
)  # 30 min default

# Where to store the port number so hooks can find us
PORT_FILE = Path.home() / ".claude_engram" / "scorer_port"
PID_FILE = Path.home() / ".claude_engram" / "scorer_pid"


def _load_model_and_templates():
    """Load AllMiniLM and pre-computed template embeddings."""
    import numpy as np
    from sentence_transformers import SentenceTransformer

    cache_file = (
        Path.home() / ".claude_engram" / "embeddings" / "decision_templates.json"
    )

    model = SentenceTransformer("all-MiniLM-L6-v2")

    if cache_file.exists():
        cache = json.loads(cache_file.read_text())
        decision_embs = np.array(cache["decision_embeddings"])
        non_decision_embs = np.array(cache["non_decision_embeddings"])
    else:
        # Build cache on the fly
        from claude_engram.hooks.intent import (
            DECISION_TEMPLATES,
            NON_DECISION_TEMPLATES,
            build_template_cache,
        )

        build_template_cache()
        cache = json.loads(cache_file.read_text())
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


def _handle_client(conn, model, decision_embs, non_decision_embs):
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

        if "embed_batch" in request:
            # Batch embedding: encode all texts in one model call
            texts = request["embed_batch"]
            if texts:
                embs = model.encode(texts, normalize_embeddings=True, batch_size=64)
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
    """Run the scorer server. Blocks until idle timeout."""
    # Load model (the expensive part — only done once)
    print("Loading AllMiniLM model...", file=sys.stderr)
    model, decision_embs, non_decision_embs = _load_model_and_templates()
    print("Model loaded.", file=sys.stderr)

    # Bind to any available port on localhost
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    port = server_sock.getsockname()[1]
    server_sock.listen(8)

    # Write port and PID so hooks can find us
    PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PORT_FILE.write_text(str(port))
    PID_FILE.write_text(str(os.getpid()))

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
                    args=(conn, model, decision_embs, non_decision_embs),
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
    """Remove port/pid files on shutdown."""
    try:
        PORT_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def is_server_running() -> bool:
    """Check if the scorer server is running."""
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
        return True
    except Exception:
        # Stale files — clean up
        _cleanup()
        return False


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
    Returns (score, extracted_text) or (0.0, "") if server unavailable.
    """
    if not PORT_FILE.exists():
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


def embed_via_server(text: str) -> list[float]:
    """
    Get embedding vector for text from the persistent server.
    Returns 384-dim list or empty list if server unavailable.
    """
    if not PORT_FILE.exists():
        return []

    try:
        port = int(PORT_FILE.read_text().strip())
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(("127.0.0.1", port))

        request = json.dumps({"embed": text}) + "\n"
        sock.sendall(request.encode("utf-8"))

        # Embedding responses are larger (~3KB for 384 floats)
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
    Returns list of 384-dim vectors. Empty list entries for failures.
    """
    if not texts:
        return []
    if not PORT_FILE.exists():
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
