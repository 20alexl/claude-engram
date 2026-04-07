#!/usr/bin/env python3
"""
Claude Engram × LoCoMo Benchmark

Tests multi-hop reasoning across 10 long conversations.
Direct comparison with MemPalace results.

Usage:
    python tests/bench_locomo.py <locomo10.json> [--limit 1] [--top-k 10]
"""
import json
import sys
import os
import argparse
import time
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claude_engram.tools.memory import MemoryStore


def recall_at_k(retrieved, correct, k):
    top_k = set(retrieved[:k])
    return float(any(c in top_k for c in correct))


def run_benchmark(data_path, limit=None, top_k=10):
    with open(data_path) as f:
        data = json.load(f)

    if limit:
        data = data[:limit]

    total_questions = sum(len(conv["qa"]) for conv in data)
    print(f"Running LoCoMo: {len(data)} conversations, {total_questions} questions, top-k={top_k}")
    print()

    m = MemoryStore()
    project = "/tmp/locomo_bench"

    all_recall = []
    total_time = 0

    for ci, conv in enumerate(data):
        conversation = conv["conversation"]
        questions = conv["qa"]

        # Clean slate
        m.forget_project(project)

        # Extract sessions and store as memories
        session_keys = sorted([k for k in conversation.keys() if k.startswith("session_") and not k.endswith("_date_time")])

        for sess_key in session_keys:
            sess_content = conversation[sess_key]
            if isinstance(sess_content, str):
                # Single string — store directly
                content = sess_content[:2000]
            elif isinstance(sess_content, list):
                # List of turns
                content = "\n".join(str(t) for t in sess_content)[:2000]
            else:
                continue

            date_key = f"{sess_key}_date_time"
            date = conversation.get(date_key, "")

            m.remember_discovery(
                project, f"[{date}] {content}",
                relevance=5,
                tags=[sess_key],
                source=sess_key,
                auto_embed=False,
            )

        # Batch embed
        m.embed_all_memories(project)

        # Query each question
        for qi, qa in enumerate(questions):
            question = qa["question"]
            evidence = qa.get("evidence", [])

            # Parse evidence to session IDs: "D1:3" -> session_1
            correct_sessions = set()
            for ev in evidence:
                match = re.match(r"D(\d+)", str(ev))
                if match:
                    correct_sessions.add(f"session_{match.group(1)}")

            if not correct_sessions:
                continue

            t0 = time.time()

            # Search
            query_words = question.lower().split()
            stop = {"what","who","where","when","how","did","does","is","was","the",
                    "a","an","in","on","at","to","for","of","with","and","or","that",
                    "this","it","from","by","about","do","has","have","had","i","you",
                    "me","my","your","they","we","she","he","her","him"}
            keywords = [w for w in query_words if w not in stop and len(w) > 2]

            results = m.search_memories(project, query=" ".join(keywords[:5]), limit=top_k)
            vector_results = m.vector_search(project, question, limit=top_k)
            scored = m.score_and_rank(project, {"file_path": "", "tags": keywords[:3]}, limit=top_k)

            # Combine: keyword first, then vector, then scored
            retrieved = []
            seen = set()
            for entry in results:
                if entry.source and entry.source not in seen:
                    retrieved.append(entry.source)
                    seen.add(entry.source)
            for entry, score in vector_results:
                if entry.source and entry.source not in seen:
                    retrieved.append(entry.source)
                    seen.add(entry.source)
            for entry, score in scored:
                if entry.source and entry.source not in seen:
                    retrieved.append(entry.source)
                    seen.add(entry.source)

            elapsed = time.time() - t0
            total_time += elapsed

            r = recall_at_k(retrieved, correct_sessions, top_k)
            all_recall.append(r)

        avg_so_far = sum(all_recall) / len(all_recall) if all_recall else 0
        print(f"  Conv {ci+1}/{len(data)}: {len(questions)} questions, running avg R@{top_k}={avg_so_far:.3f}")

    m.forget_project(project)

    avg_recall = sum(all_recall) / len(all_recall) if all_recall else 0

    print()
    print("=" * 50)
    print(f"LoCoMo Results ({len(all_recall)} questions)")
    print("=" * 50)
    print(f"  Avg Recall@{top_k}: {avg_recall:.3f}")
    print(f"  Avg time: {total_time/len(all_recall)*1000:.0f}ms per question")
    print()
    print(f"Comparison with MemPalace (session, top-{top_k}):")
    mp_recall = "0.603" if top_k == 10 else "0.778" if top_k == 50 else "~"
    print(f"  {'Metric':<20} {'Claude Engram':>15} {'MemPalace':>12}")
    print(f"  {'Avg Recall@'+str(top_k):<20} {avg_recall:>14.3f} {mp_recall:>12}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_path")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    run_benchmark(args.data_path, args.limit, args.top_k)
