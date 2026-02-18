"""
Evaluation Runner

Runs comprehensive RAG evaluation including:
- RAGAS metrics (faithfulness, answer relevancy, context precision/recall)
- System performance metrics (latency, tokens, success rate)
- Retrieval hard metrics (Hit@k, Recall@k, MRR - if gold_doc_ids provided)

Usage:
    python run_evaluation.py                  # full 30-sample run
    python run_evaluation.py --max-samples 10 # quick CI run
    
Make sure GOOGLE_API_KEY is set:
    Windows: $env:GOOGLE_API_KEY="your_key"
    Mac/Linux: export GOOGLE_API_KEY="your_key"
"""

import argparse
from evaluation import run_enhanced_evaluation

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG Evaluation Runner")
    parser.add_argument("--max-samples", type=int, default=None,
                        help="Evaluate only the first N samples (useful for CI)")
    parser.add_argument("--dataset", default="eval_dataset.json",
                        help="Path to evaluation dataset JSON")
    parser.add_argument("--output-dir", default="eval_results",
                        help="Directory for result files")
    args = parser.parse_args()

    print("Starting RAG Evaluation...")
    print("="*60)
    print("This includes:")
    print("  • RAGAS metrics (generation quality)")
    print("  • System performance (latency, tokens, success rate)")
    print("  • Retrieval metrics (if gold_doc_ids provided)")
    if args.max_samples:
        print(f"  • Limited to {args.max_samples} samples")
    print("="*60 + "\n")

    results = run_enhanced_evaluation(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        max_samples=args.max_samples,
    )

    print("\n✓ Evaluation complete!")
    print("\nNext steps:")
    print("  1. Check eval_results/ for detailed CSV files")
    print("  2. Review docs/ENHANCED_EVALUATION_GUIDE.md for details")
