#!/usr/bin/env python3
"""
Benchmark: Decision capture precision and recall (expanded).

Tests the two-tier scoring system (regex + semantic AllMiniLM)
against 220+ realistic coding prompts labeled as decision/not-decision,
organized by difficulty category.

Usage:
    python tests/bench_decision_capture_v2.py [--threshold 0.45] [--sweep]
"""
import sys
import os
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claude_engram.hooks.remind import _score_decision_intent


# ============================================================================
# Test corpus: (prompt, is_decision, category, description)
# ============================================================================

CORPUS = [
    # ========================================================================
    # DECISIONS (120+) — should be captured
    # ========================================================================

    # --- Clear switches (20) ---
    ("let's use PostgreSQL instead of SQLite for the database", True, "clear_switch", "classic switch"),
    ("switch to TypeScript for the frontend", True, "clear_switch", "switch to"),
    ("let's use pnpm instead of yarn for package management", True, "clear_switch", "pnpm over yarn"),
    ("switch to Vitest instead of Jest for the test runner", True, "clear_switch", "vitest over jest"),
    ("let's move to FastAPI instead of Flask", True, "clear_switch", "fastapi over flask"),
    ("replace moment.js with date-fns for date handling", True, "clear_switch", "replace X with Y"),
    ("swap the YAML config for TOML", True, "clear_switch", "swap to"),
    ("migrate from REST to GraphQL for the API", True, "clear_switch", "migrate"),
    ("convert the class components to hooks", True, "clear_switch", "convert to"),
    ("upgrade from Node 16 to Node 20", True, "clear_switch", "upgrade to"),
    ("move to Docker Compose instead of manual scripts", True, "clear_switch", "move to"),
    ("change to using async/await instead of callbacks", True, "clear_switch", "change to"),
    ("rewrite the CLI in Rust instead of Python", True, "clear_switch", "rewrite in"),
    ("let's go with SQLAlchemy over raw SQL", True, "clear_switch", "go with X over Y"),
    ("switch the cache from Redis to Memcached", True, "clear_switch", "switch cache"),
    ("adopt Tailwind instead of CSS modules", True, "clear_switch", "adopt"),
    ("replace the custom ORM with Prisma", True, "clear_switch", "replace custom"),
    ("let's use uv instead of pip for dependency management", True, "clear_switch", "uv over pip"),
    ("migrate the test suite from unittest to pytest", True, "clear_switch", "migrate tests"),
    ("switch to using pathlib instead of os.path", True, "clear_switch", "pathlib over os.path"),

    # --- Convention/rule declarations (20) ---
    ("from now on always use strict mode in TypeScript files", True, "convention", "from now on always"),
    ("going forward prefer composition over inheritance", True, "convention", "going forward prefer"),
    ("always validate user input at the API boundary", True, "convention", "always validate"),
    ("from now on use named exports in TypeScript", True, "convention", "named exports"),
    ("going forward prefer early returns over nested ifs", True, "convention", "early returns"),
    ("always add type hints to public functions", True, "convention", "type hints"),
    ("from now on every PR needs a test", True, "convention", "PR tests"),
    ("always use structured logging, not print statements", True, "convention", "structured logging"),
    ("going forward all errors must include a stack trace", True, "convention", "stack traces"),
    ("always wrap database calls in transactions", True, "convention", "transactions"),
    ("from now on use dataclasses instead of plain dicts", True, "convention", "dataclasses"),
    ("always pin dependency versions in requirements.txt", True, "convention", "pin deps"),
    ("going forward put business logic in services not routes", True, "convention", "service layer"),
    ("always use UTC for timestamps", True, "convention", "UTC timestamps"),
    ("from now on commit messages follow conventional commits", True, "convention", "commit messages"),
    ("always use constants instead of magic numbers", True, "convention", "constants"),
    ("going forward all configs should come from environment variables", True, "convention", "env config"),
    ("always write docstrings for public APIs", True, "convention", "docstrings"),
    ("from now on use snake_case for Python file names", True, "convention", "naming"),
    ("always check return values, don't ignore errors", True, "convention", "error checking"),

    # --- Negation constraints (20) ---
    ("don't use var anymore, use const and let instead", True, "negation", "don't use var"),
    ("stop using console.log for debugging, use the logger", True, "negation", "stop console.log"),
    ("never import from the internal package directly", True, "negation", "never import"),
    ("avoid using any in TypeScript, use proper types", True, "negation", "avoid any"),
    ("don't use global state, pass dependencies explicitly", True, "negation", "no global state"),
    ("stop doing inline SQL, use the query builder", True, "negation", "no inline SQL"),
    ("never commit secrets to the repo", True, "negation", "no secrets"),
    ("don't use sleep in tests, use proper waits", True, "negation", "no sleep"),
    ("avoid mutable default arguments in Python", True, "negation", "no mutable defaults"),
    ("stop importing everything with wildcard imports", True, "negation", "no wildcard"),
    ("don't use bare except clauses", True, "negation", "no bare except"),
    ("never hardcode URLs, use config", True, "negation", "no hardcoded URLs"),
    ("stop using string concatenation for SQL", True, "negation", "no SQL concat"),
    ("don't add type: ignore without a comment explaining why", True, "negation", "typed ignore"),
    ("avoid circular imports by restructuring", True, "negation", "no circular"),
    ("never use eval() on user input", True, "negation", "no eval"),
    ("don't catch exceptions and silently pass", True, "negation", "no silent catch"),
    ("stop using os.system, use subprocess", True, "negation", "no os.system"),
    ("get rid of the old jQuery code and use vanilla JS", True, "negation", "get rid of"),
    ("remove the deprecated API endpoints", True, "negation", "remove deprecated"),

    # --- Architecture decisions (15) ---
    ("use the repository pattern for data access", True, "architecture", "repository pattern"),
    ("implement event sourcing for the order service", True, "architecture", "event sourcing"),
    ("use the saga pattern for the checkout flow", True, "architecture", "saga pattern"),
    ("implement CQRS for the reporting module", True, "architecture", "CQRS"),
    ("use dependency injection for all service classes", True, "architecture", "DI"),
    ("implement a message queue between the services", True, "architecture", "message queue"),
    ("use the adapter pattern for third-party integrations", True, "architecture", "adapter pattern"),
    ("refactor the auth module to use the strategy pattern", True, "architecture", "strategy pattern"),
    ("keep the monorepo structure, don't split into separate repos", True, "architecture", "monorepo"),
    ("implement a circuit breaker for external API calls", True, "architecture", "circuit breaker"),
    ("use the mediator pattern for component communication", True, "architecture", "mediator"),
    ("implement caching at the service layer not the route", True, "architecture", "cache layer"),
    ("use a factory for creating database connections", True, "architecture", "factory"),
    ("implement the outbox pattern for reliable messaging", True, "architecture", "outbox"),
    ("use a gateway API instead of direct service calls", True, "architecture", "gateway"),

    # --- Implicit decisions (15) ---
    ("the API should return 404 not 400 for missing resources", True, "implicit", "status code"),
    ("errors go to stderr, not stdout", True, "implicit", "stderr"),
    ("the default timeout should be 30 seconds", True, "implicit", "timeout"),
    ("passwords need at least 12 characters", True, "implicit", "password policy"),
    ("retries should use exponential backoff", True, "implicit", "backoff"),
    ("the batch size should be 1000 rows", True, "implicit", "batch size"),
    ("the log format should be JSON", True, "implicit", "log format"),
    ("only admin users can delete records", True, "implicit", "permissions"),
    ("the response needs to include pagination metadata", True, "implicit", "pagination"),
    ("rate limit at 100 requests per minute per user", True, "implicit", "rate limit"),
    ("cache TTL should be 5 minutes for user data", True, "implicit", "cache TTL"),
    ("the health check endpoint should be at /health", True, "implicit", "health check"),
    ("connection pool size should be 20", True, "implicit", "pool size"),
    ("all timestamps in the API should be ISO 8601", True, "implicit", "timestamp format"),
    ("keep the token expiry at 1 hour", True, "implicit", "token expiry"),

    # --- Multi-sentence with embedded decision (15) ---
    ("I've been looking at the performance and the current approach is too slow. Replace the N+1 queries with a batch loader.", True, "multi_sentence", "perf fix"),
    ("After thinking about it, I want to use Redis for caching. The in-memory approach won't scale.", True, "multi_sentence", "redis caching"),
    ("The team discussed it yesterday. Let's go with microservices for the payment module.", True, "multi_sentence", "microservices"),
    ("I read the Flask vs FastAPI comparison. Switch to FastAPI for the new endpoints.", True, "multi_sentence", "flask to fastapi"),
    ("SQLite is fine for dev but production needs Postgres. Use PostgreSQL going forward.", True, "multi_sentence", "postgres for prod"),
    ("The old auth is a security risk. Rewrite it using the passport.js middleware.", True, "multi_sentence", "auth rewrite"),
    ("We've been fighting with webpack for weeks. Move to Vite for the build system.", True, "multi_sentence", "vite"),
    ("After benchmarking both options, adopt Rust for the hot path. Python stays for orchestration.", True, "multi_sentence", "rust hot path"),
    ("The monolith is getting unmaintainable. Let's split the user service out first.", True, "multi_sentence", "service split"),
    ("I checked with ops and they can support it. Use Kubernetes for the deployment.", True, "multi_sentence", "kubernetes"),
    ("The current setup leaks memory under load. Replace the custom pool with pgbouncer.", True, "multi_sentence", "pgbouncer"),
    ("Tests are too slow at 15 minutes. Switch to parallel test execution with pytest-xdist.", True, "multi_sentence", "parallel tests"),
    ("The REST API is getting bloated with versions. Move to GraphQL for the mobile clients.", True, "multi_sentence", "graphql mobile"),
    ("Docker images are 2GB. Use multi-stage builds to get them under 200MB.", True, "multi_sentence", "multi-stage"),
    ("After reviewing the options, implement OpenTelemetry for distributed tracing.", True, "multi_sentence", "otel"),

    # --- Edge cases (15) ---
    ("use postgres", True, "edge_case", "ultra short"),
    ("nuke the old cache layer and use Redis", True, "edge_case", "slang nuke"),
    ("just yeet the jQuery and go native", True, "edge_case", "slang yeet"),
    ("please use `pydantic` for all models", True, "edge_case", "backtick code"),
    ("use:\n- FastAPI for routes\n- SQLAlchemy for ORM\n- Alembic for migrations", True, "edge_case", "markdown list"),
    ("I want you to use black for formatting", True, "edge_case", "I want you to"),
    ("go ahead and use ruff instead of flake8", True, "edge_case", "go ahead"),
    ("let's just stick with the current database", True, "edge_case", "stick with"),
    ("drop Python 3.8 support, only support 3.10+", True, "edge_case", "drop support"),
    ("please adopt conventional commits for this repo", True, "edge_case", "please adopt"),
    ("we're going with Option B from the RFC", True, "edge_case", "going with option"),
    ("lock in React 18 for the frontend stack", True, "edge_case", "lock in"),
    ("pick Celery over RQ for the task queue", True, "edge_case", "pick X over Y"),
    ("commit to using TypeScript for all new files", True, "edge_case", "commit to"),
    ("prefer functional components, no more class components", True, "edge_case", "prefer X no more Y"),

    # ========================================================================
    # NON-DECISIONS (100+) — should NOT be captured
    # ========================================================================

    # --- Tasks/instructions (15) ---
    ("fix the bug in auth.py", False, "task", "fix bug"),
    ("add error handling to the parser", False, "task", "add error handling"),
    ("refactor this function to be shorter", False, "task", "refactor"),
    ("write a test for the login endpoint", False, "task", "write test"),
    ("update the documentation for the API", False, "task", "update docs"),
    ("delete the unused imports", False, "task", "delete imports"),
    ("clean up the TODO comments", False, "task", "cleanup"),
    ("add logging to the payment service", False, "task", "add logging"),
    ("create a migration for the new column", False, "task", "create migration"),
    ("move this file to the utils directory", False, "task", "move file"),
    ("rename this variable to something clearer", False, "task", "rename"),
    ("add a retry mechanism to the API client", False, "task", "add retry"),
    ("split this file into smaller modules", False, "task", "split file"),
    ("increase the test coverage for auth", False, "task", "coverage"),
    ("update the error messages to be more helpful", False, "task", "update messages"),

    # --- Questions (15) ---
    ("what does this function do?", False, "question", "what does"),
    ("should we use Redis or Memcached?", False, "question", "should we"),
    ("how does the auth middleware work?", False, "question", "how does"),
    ("where is the config file located?", False, "question", "where is"),
    ("why is this test failing?", False, "question", "why is"),
    ("can you explain the caching strategy?", False, "question", "can you explain"),
    ("what's the best way to handle this error?", False, "question", "what's best"),
    ("is there a rate limiter in place?", False, "question", "is there"),
    ("how do I set up the dev environment?", False, "question", "how do I"),
    ("what are the dependencies for this project?", False, "question", "what are"),
    ("which database does this service use?", False, "question", "which"),
    ("do we have monitoring set up?", False, "question", "do we have"),
    ("is this the right approach?", False, "question", "is this right"),
    ("would GraphQL be better here?", False, "question", "would X be"),
    ("are there any known issues with this library?", False, "question", "are there"),

    # --- Exploratory/tentative (15) ---
    ("how about we try a different approach?", False, "exploratory", "how about"),
    ("maybe we could use GraphQL instead?", False, "exploratory", "maybe we could"),
    ("what if we switched to MongoDB?", False, "exploratory", "what if"),
    ("I wonder if Redis would be faster here", False, "exploratory", "I wonder"),
    ("it might be worth trying a different approach", False, "exploratory", "might be worth"),
    ("we could potentially use WebSockets for this", False, "exploratory", "could potentially"),
    ("I'm thinking about whether to use Rust for this", False, "exploratory", "thinking about"),
    ("perhaps a queue would help with the load", False, "exploratory", "perhaps"),
    ("what do you think about using gRPC?", False, "exploratory", "what do you think"),
    ("we should think about whether to split this", False, "exploratory", "should think about"),
    ("it's worth considering a cache layer", False, "exploratory", "worth considering"),
    ("have you considered using Kafka?", False, "exploratory", "have you considered"),
    ("not sure if we need a service mesh yet", False, "exploratory", "not sure if"),
    ("I'm torn between Redis and Memcached", False, "exploratory", "torn between"),
    ("there are a few options we could explore", False, "exploratory", "options to explore"),

    # --- Status/praise/approval (10) ---
    ("looks good, ship it", False, "praise_status", "approval"),
    ("nice work on the refactor", False, "praise_status", "praise"),
    ("the CI pipeline is green", False, "praise_status", "CI status"),
    ("all tests pass now", False, "praise_status", "tests pass"),
    ("the deploy went smoothly", False, "praise_status", "deploy status"),
    ("great catch on that bug", False, "praise_status", "praise catch"),
    ("LGTM, merge when ready", False, "praise_status", "LGTM"),
    ("the performance numbers look good", False, "praise_status", "perf status"),
    ("that fixed the memory leak", False, "praise_status", "fix status"),
    ("everything is working in staging", False, "praise_status", "staging status"),

    # --- Commands (10) ---
    ("/commit", False, "command", "slash command"),
    ("run the tests please", False, "command", "run tests"),
    ("git push origin main", False, "command", "git push"),
    ("deploy to staging", False, "command", "deploy"),
    ("show me the git log", False, "command", "show log"),
    ("build the docker image", False, "command", "build"),
    ("restart the server", False, "command", "restart"),
    ("check the error logs", False, "command", "check logs"),
    ("revert the last commit", False, "command", "revert"),
    ("open a PR for this", False, "command", "open PR"),

    # --- Bug reports/info (15) ---
    ("I'm getting a TypeError on line 42", False, "bug_report", "type error"),
    ("the API returns 500 when the body is empty", False, "bug_report", "500 error"),
    ("there's a memory leak in the connection pool", False, "bug_report", "memory leak"),
    ("the import fails with ModuleNotFoundError", False, "bug_report", "import error"),
    ("users are seeing stale data after updates", False, "bug_report", "stale data"),
    ("the response time jumped to 3 seconds", False, "bug_report", "slow response"),
    ("the migration is timing out on large tables", False, "bug_report", "migration timeout"),
    ("the login page crashes on mobile", False, "bug_report", "crash report"),
    ("there's a race condition in the queue processor", False, "bug_report", "race condition"),
    ("the websocket connection drops after 30 seconds", False, "bug_report", "ws disconnect"),
    ("the test is flaky, passes sometimes fails sometimes", False, "bug_report", "flaky test"),
    ("CSS is broken on the checkout page", False, "bug_report", "CSS broken"),
    ("the cron job didn't run last night", False, "bug_report", "cron failure"),
    ("the search endpoint returns wrong results", False, "bug_report", "wrong results"),
    ("I noticed the disk usage is at 90%", False, "bug_report", "disk usage"),

    # --- Ambiguous near-misses (20) ---
    ("I used PostgreSQL for the last project", False, "ambiguous", "past tense"),
    ("we should think about whether to use Redis", False, "ambiguous", "think about"),
    ("can you switch to the other branch?", False, "ambiguous", "git switch"),
    ("I prefer Python for scripting personally", False, "ambiguous", "personal opinion"),
    ("some teams use microservices for this", False, "ambiguous", "others use"),
    ("the old code used to use Flask", False, "ambiguous", "used to use"),
    ("Redis is faster than Memcached for this use case", False, "ambiguous", "fact statement"),
    ("TypeScript has better tooling than JavaScript", False, "ambiguous", "comparison fact"),
    ("we talked about using GraphQL last week", False, "ambiguous", "talked about"),
    ("the docs recommend using async/await", False, "ambiguous", "docs recommend"),
    ("some people prefer tabs over spaces", False, "ambiguous", "some prefer"),
    ("I heard good things about Bun", False, "ambiguous", "heard about"),
    ("the benchmarks show Rust is faster", False, "ambiguous", "benchmarks show"),
    ("most projects use Docker these days", False, "ambiguous", "most use"),
    ("the industry is moving toward serverless", False, "ambiguous", "industry trend"),
    ("we were going to use Kafka but ran out of time", False, "ambiguous", "were going to"),
    ("I tried using Redis but it was overkill", False, "ambiguous", "tried using"),
    ("React is the most popular framework", False, "ambiguous", "popularity"),
    ("our competitors use GraphQL", False, "ambiguous", "competitors use"),
    ("the previous team chose MongoDB for this", False, "ambiguous", "previous team"),
]


def run_scorer(scorer_fn, name, threshold=0.45):
    """Run a scorer against the full corpus and report metrics."""
    print(f"\n=== {name} (threshold={threshold}) ===\n")

    # Per-category tracking
    cat_tp, cat_fp, cat_fn, cat_tn = {}, {}, {}, {}
    total_tp = total_fp = total_fn = total_tn = 0
    total_time = 0

    for prompt, is_decision, category, desc in CORPUS:
        t0 = time.time()
        score, _ = scorer_fn(prompt)
        total_time += time.time() - t0

        captured = score >= threshold

        if category not in cat_tp:
            cat_tp[category] = cat_fp[category] = cat_fn[category] = cat_tn[category] = 0

        if is_decision and captured:
            total_tp += 1
            cat_tp[category] += 1
        elif is_decision and not captured:
            total_fn += 1
            cat_fn[category] += 1
            print(f"  MISS [{score:.2f}] ({category}) {desc}: {prompt[:65]}")
        elif not is_decision and captured:
            total_fp += 1
            cat_fp[category] += 1
            print(f"  FALSE+ [{score:.2f}] ({category}) {desc}: {prompt[:65]}")
        else:
            total_tn += 1
            cat_tn[category] += 1

    n_decisions = sum(1 for _, d, _, _ in CORPUS if d)
    n_non = sum(1 for _, d, _, _ in CORPUS if not d)
    recall = total_tp / n_decisions * 100 if n_decisions else 0
    precision = total_tp / (total_tp + total_fp) * 100 if (total_tp + total_fp) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print(f"\n  Corpus: {n_decisions} decisions, {n_non} non-decisions")
    print(f"  TP={total_tp} FN={total_fn} FP={total_fp} TN={total_tn}")
    print(f"  Recall:    {recall:.1f}%")
    print(f"  Precision: {precision:.1f}%")
    print(f"  F1:        {f1:.1f}%")
    print(f"  Avg time:  {total_time/len(CORPUS)*1000:.1f}ms per prompt")

    # Per-category breakdown
    print(f"\n  {'Category':<20} {'Recall':>8} {'FP Rate':>8} {'Count':>6}")
    print(f"  {'-'*44}")

    categories = sorted(set(c for _, _, c, _ in CORPUS))
    for cat in categories:
        cat_total_pos = cat_tp.get(cat, 0) + cat_fn.get(cat, 0)
        cat_total_neg = cat_fp.get(cat, 0) + cat_tn.get(cat, 0)
        cat_recall = cat_tp.get(cat, 0) / cat_total_pos * 100 if cat_total_pos else 0
        cat_fpr = cat_fp.get(cat, 0) / cat_total_neg * 100 if cat_total_neg else 0
        count = cat_total_pos + cat_total_neg
        indicator = "+" if cat_total_pos > 0 else "-"
        print(f"  {indicator} {cat:<18} {cat_recall:>7.0f}% {cat_fpr:>7.0f}% {count:>5}")

    return recall, precision, f1


def threshold_sweep(scorer_fn, name):
    """Sweep thresholds to find optimal F1."""
    print(f"\n=== Threshold Sweep: {name} ===\n")
    best_f1 = 0
    best_t = 0

    print(f"  {'Threshold':>10} {'Recall':>8} {'Precision':>10} {'F1':>8}")
    print(f"  {'-'*40}")

    for t in [x / 100 for x in range(30, 71, 5)]:
        tp = fp = fn = 0
        for prompt, is_decision, _, _ in CORPUS:
            score, _ = scorer_fn(prompt)
            captured = score >= t
            if is_decision and captured: tp += 1
            elif is_decision and not captured: fn += 1
            elif not is_decision and captured: fp += 1

        n_dec = sum(1 for _, d, _, _ in CORPUS if d)
        recall = tp / n_dec * 100 if n_dec else 0
        precision = tp / (tp + fp) * 100 if (tp + fp) else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

        marker = " <--" if f1 > best_f1 else ""
        print(f"  {t:>10.2f} {recall:>7.1f}% {precision:>9.1f}% {f1:>7.1f}%{marker}")

        if f1 > best_f1:
            best_f1 = f1
            best_t = t

    print(f"\n  Best: threshold={best_t:.2f}, F1={best_f1:.1f}%")
    return best_t, best_f1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.45)
    parser.add_argument("--sweep", action="store_true", help="Run threshold sweep")
    args = parser.parse_args()

    n_dec = sum(1 for _, d, _, _ in CORPUS if d)
    n_non = sum(1 for _, d, _, _ in CORPUS if not d)

    print("=" * 60)
    print("Decision Capture Benchmark v2 (Expanded)")
    print(f"Corpus: {len(CORPUS)} prompts ({n_dec} decisions, {n_non} non-decisions)")
    print("=" * 60)

    # Regex scorer
    r1, p1, f1_r = run_scorer(_score_decision_intent, "Regex Scorer", args.threshold)

    # Semantic scorer (optional)
    r2 = p2 = f1_s = None
    try:
        from claude_engram.hooks.intent import score_decision_semantic
        test_score, _ = score_decision_semantic("let's use PostgreSQL")
        if test_score > 0:
            r2, p2, f1_s = run_scorer(score_decision_semantic, "Semantic Scorer (AllMiniLM)", args.threshold)
    except ImportError:
        print("\n=== Semantic Scorer: SKIPPED (not installed) ===")

    # Combined scorer
    r3 = p3 = f1_c = None
    try:
        from claude_engram.hooks.intent import score_decision_semantic
        has_semantic = True
    except ImportError:
        has_semantic = False

    def combined_scorer(text):
        best = 0.0
        best_text = ""
        if has_semantic:
            s, t = score_decision_semantic(text)
            if s > best:
                best, best_text = s, t
        s, t = _score_decision_intent(text)
        if s > best:
            best, best_text = s, t
        return best, best_text

    r3, p3, f1_c = run_scorer(combined_scorer, "Combined (Semantic + Regex)", args.threshold)

    # Threshold sweep
    if args.sweep:
        threshold_sweep(_score_decision_intent, "Regex")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  {'Scorer':<30} {'Recall':>8} {'Prec':>8} {'F1':>8}")
    print(f"  {'-'*56}")
    print(f"  {'Regex':<30} {r1:>7.1f}% {p1:>7.1f}% {f1_r:>7.1f}%")
    if r2 is not None:
        print(f"  {'Semantic (AllMiniLM)':<30} {r2:>7.1f}% {p2:>7.1f}% {f1_s:>7.1f}%")
    print(f"  {'Combined':<30} {r3:>7.1f}% {p3:>7.1f}% {f1_c:>7.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
