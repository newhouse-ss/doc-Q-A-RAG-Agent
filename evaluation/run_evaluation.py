"""
Evaluation Runner

Runs comprehensive RAG evaluation including:
- RAGAS metrics (faithfulness, answer relevancy, context precision/recall)
- System performance metrics (latency, tokens, success rate)
- Retrieval hard metrics (Hit@k, Recall@k, MRR - if gold_doc_ids provided)

Usage:
    python run_evaluation.py
    
Make sure GOOGLE_API_KEY is set:
    Windows: $env:GOOGLE_API_KEY="your_key"
    Mac/Linux: export GOOGLE_API_KEY="your_key"
"""

from evaluation import run_enhanced_evaluation

if __name__ == "__main__":
    print("Starting RAG Evaluation...")
    print("="*60)
    print("This includes:")
    print("  • RAGAS metrics (generation quality)")
    print("  • System performance (latency, tokens, success rate)")
    print("  • Retrieval metrics (if gold_doc_ids provided)")
    print("="*60 + "\n")
    
    results = run_enhanced_evaluation(
        dataset_path="eval_dataset.json",
        output_dir="eval_results"
    )
    
    print("\n✓ Evaluation complete!")
    print("\nNext steps:")
    print("  1. Check eval_results/ for detailed CSV files")
    print("  2. Review docs/ENHANCED_EVALUATION_GUIDE.md for details")
