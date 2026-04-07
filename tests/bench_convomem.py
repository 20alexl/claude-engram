#!/usr/bin/env python3
"""
Claude Engram × ConvoMem Benchmark (Salesforce)

Tests conversational memory across six categories.
Direct comparison with MemPalace results.

Usage:
    python tests/bench_convomem.py [--category all] [--limit 50]
"""
import json
import sys
import os
import ssl
import argparse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claude_engram.tools.memory import MemoryStore

# Bypass SSL for restricted environments
ssl._create_default_https_context = ssl._create_unverified_context

HF_BASE = "https://huggingface.co/datasets/Salesforce/ConvoMem/resolve/main/core_benchmark/evidence_questions"

CATEGORIES = {
    "user_evidence": "User Facts",
    "assistant_facts_evidence": "Assistant Facts",
    "changing_evidence": "Changing Facts",
    "abstention_evidence": "Abstention",
    "preference_evidence": "Preferences",
    "implicit_connection_evidence": "Implicit Connections",
}


def discover_files(category, cache_dir):
    api_url = f"https://huggingface.co/api/datasets/Salesforce/ConvoMem/tree/main/core_benchmark/evidence_questions/{category}/1_evidence"
    cache_path = os.path.join(cache_dir, f"{category}_filelist.json")

    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    try:
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            files = json.loads(resp.read())
            paths = [f["path"].split(f"{category}/")[1] for f in files if f["path"].endswith(".json")]
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w") as f:
                json.dump(paths, f)
            return paths
    except Exception as e:
        print(f"    Failed to list files for {category}: {e}")
        return []


def download_file(category, subpath, cache_dir):
    url = f"{HF_BASE}/{category}/{subpath}"
    cache_path = os.path.join(cache_dir, category, subpath.replace("/", "_"))
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    print(f"    Downloading: {category}/{subpath}...")
    try:
        urllib.request.urlretrieve(url, cache_path)
        with open(cache_path) as f:
            return json.load(f)
    except Exception as e:
        print(f"    Failed: {e}")
        return None


def load_items(categories, limit, cache_dir):
    all_items = []
    for category in categories:
        files = discover_files(category, cache_dir)
        if not files:
            print(f"  Skipping {category} — no files found")
            continue

        items = []
        for fpath in files:
            if len(items) >= limit:
                break
            data = download_file(category, fpath, cache_dir)
            if data and "evidence_items" in data:
                for item in data["evidence_items"]:
                    item["_category"] = category
                    items.append(item)

        all_items.extend(items[:limit])
        print(f"  {CATEGORIES.get(category, category)}: {len(items[:limit])} items")

    return all_items


def run_benchmark(category="all", limit=50, top_k=10):
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "convomem")

    categories = list(CATEGORIES.keys()) if category == "all" else [category]

    print("Loading ConvoMem data...")
    items = load_items(categories, limit, cache_dir)

    if not items:
        print("No data loaded. Check network connection.")
        return

    print(f"\nRunning ConvoMem: {len(items)} items, top-k={top_k}\n")

    m = MemoryStore()
    project = "/tmp/convomem_bench"

    cat_recalls = {c: [] for c in CATEGORIES}

    for ii, item in enumerate(items):
        conversations = item.get("conversations", [])
        question = item.get("question", "")
        evidence_messages = item.get("message_evidences", [])
        evidence_texts = set(e["text"].strip().lower() for e in evidence_messages)
        cat = item.get("_category", "unknown")

        if not conversations or not question or not evidence_texts:
            continue

        # Clean slate
        m.forget_project(project)

        # Store all messages as memories
        msg_idx = 0
        for conv in conversations:
            for msg in conv.get("messages", []):
                text = msg.get("text", "")
                if text:
                    m.remember_discovery(
                        project, text[:300],
                        relevance=5,
                        source=f"msg_{msg_idx}",
                        auto_embed=False,
                    )
                    msg_idx += 1

        # Batch embed
        m.embed_all_memories(project)

        # Query
        query_words = question.lower().split()
        stop = {"what","who","where","when","how","did","does","is","was","the",
                "a","an","in","on","at","to","for","of","with","and","or","that",
                "this","it","from","by","about","do","has","have","had","i","you",
                "me","my","your","they","we","she","he","her","him","us","our"}
        keywords = [w for w in query_words if w not in stop and len(w) > 2]

        results = m.search_memories(project, query=" ".join(keywords[:5]), limit=top_k)
        vector_results = m.vector_search(project, question, limit=top_k)
        scored = m.score_and_rank(project, {"file_path": "", "tags": keywords[:3]}, limit=top_k)

        # Combine retrieved texts from all three strategies
        retrieved_texts = set()
        for entry in results:
            retrieved_texts.add(entry.content.strip().lower())
        for entry, score in vector_results:
            retrieved_texts.add(entry.content.strip().lower())
        for entry, score in scored:
            retrieved_texts.add(entry.content.strip().lower())

        # Check if any evidence message was retrieved
        found = any(ev in retrieved_texts for ev in evidence_texts)
        # Also check substring match (evidence might be truncated)
        if not found:
            for ev in evidence_texts:
                for ret in retrieved_texts:
                    if ev[:50] in ret or ret[:50] in ev:
                        found = True
                        break
                if found:
                    break

        cat_recalls[cat].append(float(found))

        if (ii + 1) % 20 == 0:
            overall = sum(r for rs in cat_recalls.values() for r in rs)
            total = sum(len(rs) for rs in cat_recalls.values())
            print(f"  [{ii+1}/{len(items)}] Running avg: {overall/total:.3f}")

    m.forget_project(project)

    # Results
    print()
    print("=" * 50)
    print("ConvoMem Results")
    print("=" * 50)

    overall_recalls = []
    for cat, recalls in cat_recalls.items():
        if recalls:
            avg = sum(recalls) / len(recalls)
            overall_recalls.extend(recalls)
            short = CATEGORIES.get(cat, cat)
            print(f"  {short:<25} {avg:.3f} ({len(recalls)} items)")

    overall = sum(overall_recalls) / len(overall_recalls) if overall_recalls else 0
    print(f"  {'Overall':<25} {overall:.3f}")
    print()
    print("Comparison with MemPalace:")
    print(f"  {'Metric':<25} {'Claude Engram':>15} {'MemPalace':>12}")
    print(f"  {'Overall':<25} {overall:>14.3f} {'0.929':>12}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="all")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    run_benchmark(args.category, args.limit, args.top_k)
