"""
Manual Spot-Check Tool for Citation Correctness

Randomly samples k evaluation results for human verification.
Helps validate LLM-as-Judge accuracy.

Usage:
    python manual_spot_check.py --k 5
"""

import json
import random
from pathlib import Path
from typing import List, Dict
import argparse


def load_latest_results(results_dir: str = "eval_results") -> tuple:
    """Load the most recent evaluation results."""
    results_path = Path(results_dir)
    
    # Find latest files
    ragas_files = sorted(results_path.glob("ragas_results_*.csv"), reverse=True)
    perf_files = sorted(results_path.glob("performance_results_*.csv"), reverse=True)
    
    if not ragas_files or not perf_files:
        raise FileNotFoundError("No evaluation results found!")
    
    # Load CSV files
    import pandas as pd
    ragas_df = pd.read_csv(ragas_files[0])
    perf_df = pd.read_csv(perf_files[0])
    
    return ragas_df, perf_df


def sample_for_spot_check(ragas_df, perf_df, k: int = 5, seed: int = 42) -> List[Dict]:
    """Randomly sample k questions for manual verification."""
    random.seed(seed)
    
    # Merge dataframes
    n = min(len(ragas_df), len(perf_df))
    indices = random.sample(range(n), min(k, n))
    
    samples = []
    for idx in indices:
        sample = {
            'question_id': idx + 1,
            'question': ragas_df.iloc[idx]['user_input'],
            'answer': ragas_df.iloc[idx]['response'],
            'contexts': ragas_df.iloc[idx]['retrieved_contexts'],
            'auto_faithfulness': ragas_df.iloc[idx]['faithfulness'],
            'auto_answer_relevancy': ragas_df.iloc[idx]['answer_relevancy'],
        }
        samples.append(sample)
    
    return samples


def extract_citations(contexts_str: str) -> List[Dict]:
    """Extract citation info from context string."""
    import re
    citations = []
    
    # Split by [CITATION n]
    blocks = re.split(r'\[CITATION \d+\]', contexts_str)
    
    for i, block in enumerate(blocks[1:], start=1):
        source_match = re.search(r'SOURCE:\s*(.+)', block)
        chunk_match = re.search(r'CHUNK:\s*(\S+)', block)
        snippet_match = re.search(r'SNIPPET:\s*(.+)', block)
        
        citations.append({
            'num': i,
            'source': source_match.group(1).strip() if source_match else 'N/A',
            'chunk_id': chunk_match.group(1).strip() if chunk_match else 'N/A',
            'snippet': snippet_match.group(1).strip()[:200] + '...' if snippet_match else 'N/A'
        })
    
    return citations


def display_sample(sample: Dict, idx: int):
    """Display a sample for manual review."""
    print("\n" + "="*80)
    print(f"SAMPLE {idx} - Question ID: {sample['question_id']}")
    print("="*80)
    
    print(f"\n📝 QUESTION:")
    print(f"  {sample['question']}")
    
    print(f"\n🤖 GENERATED ANSWER:")
    print(f"  {sample['answer'][:500]}...")
    
    print(f"\n📊 AUTO-EVAL SCORES:")
    print(f"  Faithfulness: {sample['auto_faithfulness']:.3f}")
    print(f"  Answer Relevancy: {sample['auto_answer_relevancy']:.3f}")
    
    print(f"\n📚 RETRIEVED CITATIONS:")
    citations = extract_citations(sample['contexts'])
    for cite in citations[:3]:  # Show first 3
        print(f"\n  [{cite['num']}] Chunk ID: {cite['chunk_id']}")
        print(f"      Source: {cite['source']}")
        print(f"      Snippet: {cite['snippet']}")


def collect_manual_judgment(sample: Dict) -> Dict:
    """Collect human judgment on citation correctness."""
    print("\n" + "-"*80)
    print("MANUAL VERIFICATION")
    print("-"*80)
    
    print("\nPlease evaluate:")
    print("1. Citation Coverage: Are all key facts in the answer supported by citations?")
    print("2. Citation Accuracy: Do the citations actually support what they claim?")
    print("3. No Hallucination: Is there any unsupported claim in the answer?")
    
    while True:
        coverage = input("\nCitation Coverage (1-5, 5=excellent): ").strip()
        accuracy = input("Citation Accuracy (1-5, 5=excellent): ").strip()
        no_hallucination = input("No Hallucination? (y/n): ").strip().lower()
        
        if coverage.isdigit() and accuracy.isdigit() and no_hallucination in ['y', 'n']:
            break
        print("Invalid input. Please try again.")
    
    notes = input("\nOptional notes: ").strip()
    
    return {
        'question_id': sample['question_id'],
        'auto_faithfulness': sample['auto_faithfulness'],
        'manual_coverage': int(coverage),
        'manual_accuracy': int(accuracy),
        'manual_no_hallucination': no_hallucination == 'y',
        'manual_notes': notes,
        'manual_overall_correct': int(coverage) >= 4 and int(accuracy) >= 4 and no_hallucination == 'y'
    }


def analyze_agreement(judgments: List[Dict]):
    """Analyze agreement between auto and manual evaluation."""
    print("\n" + "="*80)
    print("AGREEMENT ANALYSIS")
    print("="*80)
    
    # Calculate correlation
    auto_scores = [j['auto_faithfulness'] for j in judgments]
    manual_scores = [(j['manual_coverage'] + j['manual_accuracy']) / 10 for j in judgments]
    
    import numpy as np
    correlation = np.corrcoef(auto_scores, manual_scores)[0, 1]
    
    print(f"\nCorrelation (Auto Faithfulness vs Manual Score): {correlation:.3f}")
    
    # Binary agreement
    auto_correct = [f >= 0.9 for f in auto_scores]
    manual_correct = [j['manual_overall_correct'] for j in judgments]
    
    agreement = sum(a == m for a, m in zip(auto_correct, manual_correct)) / len(judgments)
    print(f"Binary Agreement (Auto vs Manual): {agreement:.1%}")
    
    print(f"\nDetailed Results:")
    for j in judgments:
        status = "✓" if j['manual_overall_correct'] else "✗"
        print(f"  Q{j['question_id']}: Auto={j['auto_faithfulness']:.2f}, "
              f"Manual={j['manual_coverage']}/5, {j['manual_accuracy']}/5 {status}")
        if j['manual_notes']:
            print(f"    Note: {j['manual_notes']}")


def save_results(judgments: List[Dict], output_path: str = "manual_spot_check_results.json"):
    """Save manual verification results."""
    output_file = Path(output_path)
    
    # Load existing results if any
    if output_file.exists():
        with open(output_file, 'r', encoding='utf-8') as f:
            existing = json.load(f)
    else:
        existing = []
    
    # Append new results
    existing.extend(judgments)
    
    # Save
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Results saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Manual spot-check for citation correctness")
    parser.add_argument('--k', type=int, default=5, help="Number of samples to check")
    parser.add_argument('--seed', type=int, default=42, help="Random seed")
    parser.add_argument('--results-dir', type=str, default="../eval_results", help="Evaluation results directory")
    args = parser.parse_args()
    
    print("="*80)
    print("MANUAL SPOT-CHECK FOR CITATION CORRECTNESS")
    print("="*80)
    print(f"\nSampling {args.k} questions for manual verification...")
    
    # Load results
    ragas_df, perf_df = load_latest_results(args.results_dir)
    print(f"✓ Loaded evaluation results ({len(ragas_df)} questions)")
    
    # Sample
    samples = sample_for_spot_check(ragas_df, perf_df, k=args.k, seed=args.seed)
    print(f"✓ Randomly sampled {len(samples)} questions (seed={args.seed})")
    
    # Collect judgments
    judgments = []
    for i, sample in enumerate(samples, 1):
        display_sample(sample, i)
        judgment = collect_manual_judgment(sample)
        judgments.append(judgment)
    
    # Analyze
    analyze_agreement(judgments)
    
    # Save
    save_results(judgments)
    
    print("\n" + "="*80)
    print("SPOT-CHECK COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
