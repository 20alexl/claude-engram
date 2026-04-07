#!/usr/bin/env python3
"""
Claude Engram × LongMemEval Benchmark

Evaluates claude-engram's retrieval against the LongMemEval benchmark.
Direct comparison with MemPalace results.

For each question:
1. Store all haystack sessions as memories in MemoryStore
2. Query using search_memories (keyword) and score_and_rank (scored)
3. Score retrieval against ground-truth answer sessions

Usage:
    python tests/bench_longmemeval.py <path_to_longmemeval_s_cleaned.json> [--limit 20]
"""
import json
import math
import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.tools.memory import MemoryStore


def dcg(relevances, k):
    score = 0.0
    for i, rel in enumerate(relevances[:k]):
        score += rel / math.log2(i + 2)
    return score


def ndcg(retrieved_ids, correct_ids, k):
    relevances = [1.0 if rid in correct_ids else 0.0 for rid in retrieved_ids[:k]]
    ideal = sorted(relevances, reverse=True)
    idcg = dcg(ideal, k)
    if idcg == 0:
        return 0.0
    return dcg(relevances, k) / idcg


def recall_at_k(retrieved_ids, correct_ids, k):
    top_k = set(retrieved_ids[:k])
    return float(any(cid in top_k for cid in correct_ids))


def run_benchmark(data_path, limit=None, granularity="session"):
    with open(data_path) as f:
        dataset = json.load(f)

    if limit:
        dataset = dataset[:limit]

    print(f"Running LongMemEval: {len(dataset)} questions, granularity={granularity}")
    print()

    m = MemoryStore()
    project = "/tmp/longmemeval"

    results = {"recall@5": [], "recall@10": [], "ndcg@10": []}
    total_time = 0

    for qi, entry in enumerate(dataset):
        question = entry["question"]
        correct_ids = set(entry["answer_session_ids"])
        sessions = entry["haystack_sessions"]
        session_ids = entry["haystack_session_ids"]

        # Clean slate for each question
        m.forget_project(project)

        # Store all haystack sessions as memories (bulk, no per-item embedding)
        for sess_idx, (session, sess_id) in enumerate(zip(sessions, session_ids)):
            user_turns = [t["content"] for t in session if t["role"] == "user"]
            if user_turns:
                content = "\n".join(user_turns)[:500]
                m.remember_discovery(
                    project, content,
                    relevance=5,
                    tags=[f"sess_{sess_id}"],
                    source=sess_id,
                    auto_embed=False,  # Batch embed after all stored
                )

        # Batch embed all memories at once
        m.embed_all_memories(project)

        # Query using keyword search
        t0 = time.time()

        # Strategy: extract key terms from question for keyword search
        query_words = set(question.lower().split())
        # Remove stop words
        stop = {"what", "who", "where", "when", "how", "did", "does", "is", "was", "the",
                "a", "an", "in", "on", "at", "to", "for", "of", "with", "and", "or", "that",
                "this", "it", "from", "by", "about", "which", "do", "has", "have", "had",
                "be", "been", "being", "are", "were", "will", "would", "could", "should",
                "can", "may", "might", "shall", "must", "my", "your", "their", "our", "me",
                "i", "you", "he", "she", "they", "we", "him", "her", "them", "us"}
        keywords = [w for w in query_words if w not in stop and len(w) > 2]

        # Strategy 1: Keyword search (exact term matching — strong baseline)
        search_results = m.search_memories(project, query=" ".join(keywords[:5]), limit=50)

        # Strategy 2: Score-based ranking
        scored_results = m.score_and_rank(
            project, {"file_path": "", "tags": [], "command": question}, limit=50)

        # Strategy 3: Vector search (semantic — catches what keywords miss)
        vector_results = m.vector_search(project, question, limit=50)

        elapsed = time.time() - t0
        total_time += elapsed

        # Combine: keyword first (strongest for exact matches), then vector (new),
        # then scored (weakest for this task)
        retrieved_session_ids = []
        seen = set()

        for entry_obj in search_results:
            sid = entry_obj.source
            if sid and sid not in seen:
                retrieved_session_ids.append(sid)
                seen.add(sid)

        for entry_obj, score in vector_results:
            sid = entry_obj.source
            if sid and sid not in seen:
                retrieved_session_ids.append(sid)
                seen.add(sid)

        for entry_obj, score in scored_results:
            sid = entry_obj.source
            if sid and sid not in seen:
                retrieved_session_ids.append(sid)
                seen.add(sid)

        # Evaluate
        r5 = recall_at_k(retrieved_session_ids, correct_ids, 5)
        r10 = recall_at_k(retrieved_session_ids, correct_ids, 10)
        n10 = ndcg(retrieved_session_ids, correct_ids, 10)

        results["recall@5"].append(r5)
        results["recall@10"].append(r10)
        results["ndcg@10"].append(n10)

        if (qi + 1) % 10 == 0 or (qi + 1) == len(dataset):
            avg_r5 = sum(results["recall@5"]) / len(results["recall@5"])
            avg_r10 = sum(results["recall@10"]) / len(results["recall@10"])
            print(f"  [{qi+1}/{len(dataset)}] R@5={avg_r5:.3f} R@10={avg_r10:.3f} ({elapsed*1000:.0f}ms)")

    # Cleanup
    m.forget_project(project)

    # Final results
    avg_r5 = sum(results["recall@5"]) / len(results["recall@5"])
    avg_r10 = sum(results["recall@10"]) / len(results["recall@10"])
    avg_n10 = sum(results["ndcg@10"]) / len(results["ndcg@10"])

    print()
    print("=" * 50)
    print(f"LongMemEval Results ({len(dataset)} questions)")
    print("=" * 50)
    print(f"  Recall@5:  {avg_r5:.3f}")
    print(f"  Recall@10: {avg_r10:.3f}")
    print(f"  NDCG@10:   {avg_n10:.3f}")
    print(f"  Avg time:  {total_time/len(dataset)*1000:.0f}ms per question")
    print()
    print("Comparison with MemPalace (raw mode):")
    print(f"  {'Metric':<12} {'Claude Engram':>15} {'MemPalace':>12}")
    print(f"  {'Recall@5':<12} {avg_r5:>14.3f} {'0.966':>12}")
    print(f"  {'Recall@10':<12} {avg_r10:>14.3f} {'0.982':>12}")
    print(f"  {'NDCG@10':<12} {avg_n10:>14.3f} {'0.889':>12}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_path", help="Path to longmemeval_s_cleaned.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--granularity", default="session", choices=["session", "turn"])
    args = parser.parse_args()

    run_benchmark(args.data_path, args.limit, args.granularity)
