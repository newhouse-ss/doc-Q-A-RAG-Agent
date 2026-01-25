"""
RAG Evaluation with Retrieval Hard Metrics + System Performance Metrics

Comprehensive evaluation including:
1. RAGAS metrics: Faithfulness, Answer Relevancy, Context Precision/Recall
2. System Performance: Latency (p50/p95), Tokens, Success rate
3. Retrieval Hard Metrics: Hit@k, Recall@k, MRR (requires gold_doc_ids)
"""

import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)

import logging
logging.getLogger("asyncio").setLevel(logging.ERROR)

import json
import os
import time
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import pandas as pd
import numpy as np

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall
)

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from rag_agent.config import ensure_google_api_key, EMBEDDING_MODEL_NAME, LLM_MODEL_NAME
from rag_agent.graph_builder import build_graph


# ==================== Retrieval Metrics ====================

def calculate_hit_at_k(retrieved_ids: List[str], gold_ids: List[str], k: int) -> float:
    """Hit@k: 1 if any gold document appears in top-k retrieved, 0 otherwise"""
    if not gold_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    return 1.0 if any(gid in top_k for gid in gold_ids) else 0.0


def calculate_recall_at_k(retrieved_ids: List[str], gold_ids: List[str], k: int) -> float:
    """Recall@k: proportion of gold documents that appear in top-k retrieved"""
    if not gold_ids:
        return 0.0
    top_k = set(retrieved_ids[:k])
    hits = sum(1 for gid in gold_ids if gid in top_k)
    return hits / len(gold_ids)


def calculate_mrr(retrieved_ids: List[str], gold_ids: List[str]) -> float:
    """MRR: 1 / rank of first gold document (0 if no gold found)"""
    if not gold_ids:
        return 0.0
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in gold_ids:
            return 1.0 / rank
    return 0.0


# ==================== Data Loading ====================

def load_evaluation_dataset(dataset_path: str = "eval_dataset.json") -> List[Dict]:
    """Load the evaluation dataset from JSON file."""
    with open(dataset_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ==================== RAG Pipeline with Metrics ====================

def extract_chunk_ids_from_context(context: str) -> List[str]:
    """Extract chunk_ids from retriever tool output (format: CHUNK: <id>)"""
    pattern = r'CHUNK:\s*(\S+)'
    matches = re.findall(pattern, context)
    return matches if matches else []


def run_rag_pipeline_with_metrics(question: str, graph) -> Dict:
    """
    Run RAG pipeline and collect:
    - answer, contexts, retrieved_doc_ids
    - latency, tokens, success status
    """
    from langchain_core.messages import HumanMessage
    
    start_time = time.time()
    
    # Run the graph
    result = graph.invoke({"messages": [HumanMessage(content=question)]})
    
    total_latency = time.time() - start_time
    
    # Extract data from messages
    messages = result.get("messages", [])
    answer = ""
    contexts = []
    retrieved_doc_ids = []
    
    for msg in messages:
        if hasattr(msg, 'content') and msg.content:
            if hasattr(msg, 'type') and msg.type == 'ai':
                answer = msg.content
            if hasattr(msg, 'type') and msg.type == 'tool':
                contexts.append(msg.content)
                # Extract chunk_ids from tool output
                chunk_ids = extract_chunk_ids_from_context(msg.content)
                retrieved_doc_ids.extend(chunk_ids)
    
    # Estimate tokens (rough approximation: 1 token ≈ 4 chars)
    total_chars = len(question) + len(answer) + sum(len(c) for c in contexts)
    estimated_tokens = total_chars // 4
    
    return {
        'answer': answer if answer else "No answer generated",
        'contexts': contexts if contexts else ["No context retrieved"],
        'retrieved_doc_ids': retrieved_doc_ids,
        'total_latency': total_latency,
        'estimated_tokens': estimated_tokens,
        'success': bool(answer and contexts)
    }


# ==================== Enhanced Evaluation ====================

def prepare_evaluation_data_enhanced(eval_dataset: List[Dict], graph) -> Tuple[Dict, List[Dict]]:
    """
    Run RAG pipeline on all questions and collect both RAGAS data and performance metrics.
    
    Returns:
        - ragas_data: dict for RAGAS evaluation
        - performance_data: list of dicts with latency, tokens, retrieval metrics
    """
    questions = []
    answers = []
    contexts = []
    ground_truths = []
    performance_data = []
    
    print("\n" + "="*60)
    print("RUNNING RAG PIPELINE ON EVALUATION DATASET")
    print("="*60)
    
    for i, item in enumerate(eval_dataset, 1):
        question = item['question']
        ground_truth = item['ground_truth']
        gold_doc_ids = item.get('gold_doc_ids', [])
        
        print(f"\n[{i}/{len(eval_dataset)}] Processing question...")
        print(f"Q: {question[:80]}...")
        
        try:
            # Run RAG pipeline with metrics
            metrics = run_rag_pipeline_with_metrics(question, graph)
            
            # Store for RAGAS
            questions.append(question)
            answers.append(metrics['answer'])
            contexts.append(metrics['contexts'])
            ground_truths.append(ground_truth)
            
            # Calculate retrieval metrics (if gold_doc_ids provided)
            retrieval_metrics = {}
            if gold_doc_ids and metrics['retrieved_doc_ids']:
                for k in [1, 3, 5]:
                    retrieval_metrics[f'hit@{k}'] = calculate_hit_at_k(
                        metrics['retrieved_doc_ids'], gold_doc_ids, k
                    )
                    retrieval_metrics[f'recall@{k}'] = calculate_recall_at_k(
                        metrics['retrieved_doc_ids'], gold_doc_ids, k
                    )
                retrieval_metrics['mrr'] = calculate_mrr(
                    metrics['retrieved_doc_ids'], gold_doc_ids
                )
            
            # Store performance data
            perf = {
                'question_id': i,
                'question': question[:100],
                'total_latency': metrics['total_latency'],
                'estimated_tokens': metrics['estimated_tokens'],
                'success': metrics['success'],
                **retrieval_metrics
            }
            performance_data.append(perf)
            
            print(f"✓ Latency: {metrics['total_latency']:.2f}s")
            print(f"✓ Tokens: ~{metrics['estimated_tokens']}")
            if retrieval_metrics:
                print(f"✓ MRR: {retrieval_metrics.get('mrr', 0):.3f}")
            
        except Exception as e:
            print(f"✗ Error: {e}")
            questions.append(question)
            answers.append(f"Error: {str(e)}")
            contexts.append(["Error retrieving context"])
            ground_truths.append(ground_truth)
            performance_data.append({
                'question_id': i,
                'question': question[:100],
                'total_latency': 0,
                'estimated_tokens': 0,
                'success': False
            })
    
    ragas_data = {
        'question': questions,
        'answer': answers,
        'contexts': contexts,
        'ground_truth': ground_truths
    }
    
    return ragas_data, performance_data


# ==================== Performance Analysis ====================

def analyze_performance(performance_data: List[Dict]) -> Dict:
    """Calculate system performance metrics."""
    if not performance_data:
        return {}
    
    df = pd.DataFrame(performance_data)
    
    latencies = df['total_latency'].values
    tokens = df['estimated_tokens'].values
    successes = df['success'].values
    
    metrics = {
        'latency_p50': float(np.percentile(latencies, 50)),
        'latency_p95': float(np.percentile(latencies, 95)),
        'latency_mean': float(np.mean(latencies)),
        'tokens_mean': float(np.mean(tokens)),
        'tokens_p95': float(np.percentile(tokens, 95)),
        'success_rate': float(np.mean(successes)),
        'failure_rate': float(1 - np.mean(successes)),
    }
    
    # Retrieval metrics (if available)
    retrieval_cols = [col for col in df.columns if '@' in col or col == 'mrr']
    for col in retrieval_cols:
        if col in df.columns:
            metrics[f'{col}_mean'] = float(df[col].mean())
    
    return metrics


# ==================== Main Evaluation ====================

def run_enhanced_evaluation(dataset_path: str = "eval_dataset.json", 
                           output_dir: str = "eval_results") -> Dict:
    """Main evaluation function with all metrics."""
    ensure_google_api_key()
    Path(output_dir).mkdir(exist_ok=True)
    
    # Load dataset
    print("Loading evaluation dataset...")
    eval_dataset = load_evaluation_dataset(dataset_path)
    print(f"✓ Loaded {len(eval_dataset)} evaluation samples")
    
    # Build RAG pipeline
    print("\nBuilding RAG pipeline...")
    graph = build_graph()
    print("✓ RAG pipeline ready")
    
    # Run pipeline with enhanced metrics
    ragas_data, performance_data = prepare_evaluation_data_enhanced(eval_dataset, graph)
    
    # ========== RAGAS Evaluation ==========
    print("\n" + "="*60)
    print("RUNNING RAGAS EVALUATION")
    print("="*60)
    
    dataset = Dataset.from_dict(ragas_data)
    llm = ChatGoogleGenerativeAI(model=LLM_MODEL_NAME, temperature=0)
    embeddings = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME)
    
    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]
    
    print("\nEvaluating with 4 RAGAS metrics...")
    print("This may take a few minutes...\n")
    
    results = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
    )
    
    # ========== Save Results ==========
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # RAGAS results
    results_df = results.to_pandas()
    csv_path = Path(output_dir) / f"ragas_results_{timestamp}.csv"
    results_df.to_csv(csv_path, index=False)
    print(f"\n✓ RAGAS results saved to: {csv_path}")
    
    # Performance results
    perf_df = pd.DataFrame(performance_data)
    perf_csv_path = Path(output_dir) / f"performance_results_{timestamp}.csv"
    perf_df.to_csv(perf_csv_path, index=False)
    print(f"✓ Performance results saved to: {perf_csv_path}")
    
    # Calculate aggregated metrics
    metric_cols = ['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall']
    ragas_metrics = {}
    for metric in metric_cols:
        if metric in results_df.columns:
            ragas_metrics[metric] = float(results_df[metric].mean())
        else:
            ragas_metrics[metric] = 0.0
    
    perf_metrics = analyze_performance(performance_data)
    
    # Combined summary
    summary = {
        'timestamp': timestamp,
        'num_samples': len(eval_dataset),
        'ragas_metrics': ragas_metrics,
        'ragas_average': float(sum(ragas_metrics.values()) / len(ragas_metrics)),
        'performance_metrics': perf_metrics,
    }
    
    # Save summary
    json_path = Path(output_dir) / f"evaluation_summary_{timestamp}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    print(f"✓ Summary saved to: {json_path}")
    
    # ========== Print Summary ==========
    print("\n" + "="*60)
    print("EVALUATION SUMMARY")
    print("="*60)
    print(f"Samples: {summary['num_samples']}")
    
    print("\n【RAGAS Metrics】(0-1, higher better)")
    for metric, value in ragas_metrics.items():
        print(f"  {metric:20s}: {value:.4f}")
    print(f"  {'Average':20s}: {summary['ragas_average']:.4f}")
    
    print("\n【System Performance】")
    print(f"  Latency (p50/p95/mean): {perf_metrics['latency_p50']:.2f}s / "
          f"{perf_metrics['latency_p95']:.2f}s / {perf_metrics['latency_mean']:.2f}s")
    print(f"  Tokens (mean/p95):      {perf_metrics['tokens_mean']:.0f} / "
          f"{perf_metrics['tokens_p95']:.0f}")
    print(f"  Success Rate:           {perf_metrics['success_rate']:.1%}")
    
    if any('@' in k or k == 'mrr_mean' for k in perf_metrics):
        print("\n【Retrieval Hard Metrics】(requires gold_doc_ids)")
        for k, v in perf_metrics.items():
            if '@' in k or 'mrr' in k:
                print(f"  {k:20s}: {v:.4f}")
    
    print("\n" + "="*60)
    print("✓ Evaluation complete! Check eval_results/ for detailed outputs")
    print("="*60 + "\n")
    
    return summary


if __name__ == "__main__":
    import sys
    
    if "GOOGLE_API_KEY" not in os.environ:
        print("ERROR: GOOGLE_API_KEY environment variable not set")
        print("\nSet it with:")
        print("  Windows: $env:GOOGLE_API_KEY='your_key'")
        print("  Mac/Linux: export GOOGLE_API_KEY='your_key'")
        sys.exit(1)
    
    try:
        results = run_enhanced_evaluation()
    except Exception as e:
        print(f"\nEvaluation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
