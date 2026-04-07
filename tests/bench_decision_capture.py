"""
Benchmark: Decision capture recall and precision.

Tests the two-tier scoring system (semantic AllMiniLM + regex fallback)
against a diverse set of decision and non-decision prompts.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.hooks.remind import _score_decision_intent


# Test corpus: (prompt, is_decision, description)
DECISION_PROMPTS = [
    # Clear decisions — SHOULD capture
    ("let's use PostgreSQL instead of SQLite for the database", True, "classic switch"),
    ("switch to TypeScript for the frontend components", True, "switch to"),
    ("from now on, always use strict mode in TypeScript files", True, "from now on"),
    ("don't use var anymore, use const and let instead", True, "negation"),
    ("please replace the old auth middleware with passport.js", True, "please replace"),
    ("we should adopt the repository pattern for data access", True, "we should"),
    ("going forward prefer composition over inheritance", True, "going forward"),
    ("I want to rewrite the API layer in Go instead of Python", True, "I want to rewrite"),
    ("stop using console.log for debugging, use the logger", True, "stop using"),
    ("just use redis for caching, it is simpler", True, "just use"),
    ("get rid of the old jQuery code and use vanilla JS", True, "get rid of"),
    ("never import from the internal package directly", True, "never"),
    ("we should migrate from REST to GraphQL for the API", True, "migrate"),
    ("always validate user input at the API boundary", True, "always validate"),
    ("drop Python 3.8 support, only support 3.10+", True, "drop support"),
    ("use dependency injection for all service classes", True, "use DI"),
    ("keep the monorepo structure, don't split into separate repos", True, "keep/stick with"),
    ("refactor the auth module to use the strategy pattern", True, "refactor to"),
    ("avoid using any in TypeScript, use proper types", True, "avoid using"),
    ("replace moment.js with date-fns for date handling", True, "replace X with Y"),

    # NOT decisions — should NOT capture
    ("fix the bug in auth.py", False, "task"),
    ("what does this function do?", False, "question"),
    ("can you explain how the router works?", False, "request for info"),
    ("hello", False, "greeting"),
    ("looks good, ship it", False, "approval"),
    ("should we use Redis or Memcached?", False, "question about options"),
    ("how about we try a different approach?", False, "exploratory"),
    ("maybe we could use GraphQL instead?", False, "tentative"),
    ("what if we switched to MongoDB?", False, "hypothetical"),
    ("/commit", False, "command"),
    ("run the tests please", False, "instruction"),
    ("check the error logs for me", False, "instruction"),
    ("I'm getting a TypeError on line 42", False, "bug report"),
    ("the CI pipeline is broken again", False, "status report"),
    ("nice work on the refactor", False, "praise"),
    ("can you review this pull request?", False, "request"),
    ("where is the config file located?", False, "location question"),
    ("how do I set up the dev environment?", False, "how-to question"),
    ("what are the dependencies for this project?", False, "info request"),
    ("could you clean up the imports in this file?", False, "polite instruction"),
]


def test_regex_scorer():
    """Test the regex-based decision scorer."""
    print("=== Regex Decision Scorer ===\n")

    true_pos = 0
    false_pos = 0
    false_neg = 0
    true_neg = 0

    threshold = 0.45

    for prompt, is_decision, desc in DECISION_PROMPTS:
        score, text = _score_decision_intent(prompt)
        captured = score >= threshold

        if is_decision and captured:
            true_pos += 1
        elif is_decision and not captured:
            false_neg += 1
            print(f"  MISS [{score:.2f}] {desc}: {prompt[:60]}")
        elif not is_decision and captured:
            false_pos += 1
            print(f"  FALSE+ [{score:.2f}] {desc}: {prompt[:60]}")
        else:
            true_neg += 1

    total_decisions = sum(1 for _, d, _ in DECISION_PROMPTS if d)
    total_non = sum(1 for _, d, _ in DECISION_PROMPTS if not d)

    recall = true_pos / total_decisions * 100 if total_decisions else 0
    precision = true_pos / (true_pos + false_pos) * 100 if (true_pos + false_pos) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print(f"\n  Decisions: {total_decisions} | Non-decisions: {total_non}")
    print(f"  True pos: {true_pos} | False neg: {false_neg} | False pos: {false_pos} | True neg: {true_neg}")
    print(f"  Recall:    {recall:.1f}%")
    print(f"  Precision: {precision:.1f}%")
    print(f"  F1 Score:  {f1:.1f}%")

    return recall, precision, f1


def test_semantic_scorer():
    """Test the semantic AllMiniLM scorer if available."""
    try:
        from claude_engram.hooks.intent import score_decision_semantic
        # Try a quick score to see if model is available
        test_score, _ = score_decision_semantic("let's use PostgreSQL")
        if test_score == 0.0:
            # Check if it's genuinely 0 or server not available
            from claude_engram.hooks.scorer_server import PORT_FILE
            if not PORT_FILE.exists():
                print("\n=== Semantic Scorer: SKIPPED (scorer server not running) ===")
                return None, None, None
    except ImportError:
        print("\n=== Semantic Scorer: SKIPPED (sentence-transformers not installed) ===")
        return None, None, None

    print("\n=== Semantic Decision Scorer (AllMiniLM) ===\n")

    true_pos = 0
    false_pos = 0
    false_neg = 0
    true_neg = 0

    threshold = 0.45

    for prompt, is_decision, desc in DECISION_PROMPTS:
        score, text = score_decision_semantic(prompt)
        captured = score >= threshold

        if is_decision and captured:
            true_pos += 1
        elif is_decision and not captured:
            false_neg += 1
            print(f"  MISS [{score:.2f}] {desc}: {prompt[:60]}")
        elif not is_decision and captured:
            false_pos += 1
            print(f"  FALSE+ [{score:.2f}] {desc}: {prompt[:60]}")
        else:
            true_neg += 1

    total_decisions = sum(1 for _, d, _ in DECISION_PROMPTS if d)
    total_non = sum(1 for _, d, _ in DECISION_PROMPTS if not d)

    recall = true_pos / total_decisions * 100 if total_decisions else 0
    precision = true_pos / (true_pos + false_pos) * 100 if (true_pos + false_pos) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print(f"\n  Decisions: {total_decisions} | Non-decisions: {total_non}")
    print(f"  True pos: {true_pos} | False neg: {false_neg} | False pos: {false_pos} | True neg: {true_neg}")
    print(f"  Recall:    {recall:.1f}%")
    print(f"  Precision: {precision:.1f}%")
    print(f"  F1 Score:  {f1:.1f}%")

    return recall, precision, f1


def test_combined_scorer():
    """Test the combined two-tier scorer (semantic + regex fallback)."""
    print("\n=== Combined Scorer (Semantic + Regex) ===\n")

    try:
        from claude_engram.hooks.intent import score_decision_semantic
        has_semantic = True
    except ImportError:
        has_semantic = False

    true_pos = 0
    false_pos = 0
    false_neg = 0
    true_neg = 0

    threshold = 0.45

    for prompt, is_decision, desc in DECISION_PROMPTS:
        # Tier 1: Semantic
        best_score = 0.0
        if has_semantic:
            sem_score, _ = score_decision_semantic(prompt)
            best_score = sem_score

        # Tier 2: Regex (may upgrade)
        regex_score, _ = _score_decision_intent(prompt)
        best_score = max(best_score, regex_score)

        captured = best_score >= threshold

        if is_decision and captured:
            true_pos += 1
        elif is_decision and not captured:
            false_neg += 1
            print(f"  MISS [{best_score:.2f}] {desc}: {prompt[:60]}")
        elif not is_decision and captured:
            false_pos += 1
            print(f"  FALSE+ [{best_score:.2f}] {desc}: {prompt[:60]}")
        else:
            true_neg += 1

    total_decisions = sum(1 for _, d, _ in DECISION_PROMPTS if d)
    total_non = sum(1 for _, d, _ in DECISION_PROMPTS if not d)

    recall = true_pos / total_decisions * 100 if total_decisions else 0
    precision = true_pos / (true_pos + false_pos) * 100 if (true_pos + false_pos) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print(f"\n  Decisions: {total_decisions} | Non-decisions: {total_non}")
    print(f"  True pos: {true_pos} | False neg: {false_neg} | False pos: {false_pos} | True neg: {true_neg}")
    print(f"  Recall:    {recall:.1f}%")
    print(f"  Precision: {precision:.1f}%")
    print(f"  F1 Score:  {f1:.1f}%")

    return recall, precision, f1


if __name__ == "__main__":
    print("=" * 60)
    print("Decision Capture Benchmark")
    print(f"Test corpus: {len(DECISION_PROMPTS)} prompts")
    print(f"  Decisions: {sum(1 for _,d,_ in DECISION_PROMPTS if d)}")
    print(f"  Non-decisions: {sum(1 for _,d,_ in DECISION_PROMPTS if not d)}")
    print("=" * 60)

    r1, p1, f1 = test_regex_scorer()
    r2, p2, f2 = test_semantic_scorer()
    r3, p3, f3 = test_combined_scorer()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"{'Scorer':<25} {'Recall':>8} {'Precision':>10} {'F1':>8}")
    print("-" * 55)
    print(f"{'Regex':<25} {r1:>7.1f}% {p1:>9.1f}% {f1:>7.1f}%")
    if r2 is not None:
        print(f"{'Semantic (AllMiniLM)':<25} {r2:>7.1f}% {p2:>9.1f}% {f2:>7.1f}%")
    if r3 is not None:
        print(f"{'Combined':<25} {r3:>7.1f}% {p3:>9.1f}% {f3:>7.1f}%")
    print("=" * 60)
