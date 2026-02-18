from typing import List, Optional, Dict, Any
import pandas as pd
from datasets import Dataset

from ragas import evaluate
from ragas.metrics import (
    answer_correctness,
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)

from evaluation.evaluation_schemas import (
    MultiHopTestCase,
    SystemResponse,
    EvaluationResult,
    RetrievedContext,
)
from evaluation.evaluation_metrics import (
    evaluate_multi_hop_retrieval,
    calculate_aggregate_metrics,
)
from rag_agent.models import get_llm_model


class MultiHopEvaluator:
    """Evaluator for multi-hop RAG system using custom metrics + Ragas."""
    
    def __init__(self, llm=None):
        """
        Initialize evaluator.
        
        Args:
            llm: Optional LLM model for Ragas evaluation. If None, uses default.
        """
        self.llm = llm or get_llm_model()
    
    def evaluate_single(
        self,
        test_case: MultiHopTestCase,
        system_response: SystemResponse,
        use_ragas: bool = True
    ) -> EvaluationResult:
        """
        Evaluate a single test case.
        
        Args:
            test_case: The test case with gold standard
            system_response: System's response to evaluate
            use_ragas: Whether to also compute Ragas metrics
        
        Returns:
            Complete evaluation result
        """
        result = evaluate_multi_hop_retrieval(test_case, system_response)
        
        if use_ragas:
            ragas_scores = self._compute_ragas_metrics(
                question=test_case.question,
                answer=system_response.answer,
                contexts=[chunk.content for chunk in system_response.retrieved_chunks],
                ground_truth=test_case.gold_answer,
            )
            
            result.answer_correctness = ragas_scores.get("answer_correctness")
            result.faithfulness = ragas_scores.get("faithfulness")
            result.answer_relevancy = ragas_scores.get("answer_relevancy")
            result.context_precision = ragas_scores.get("context_precision")
            result.context_recall = ragas_scores.get("context_recall")
        
        return result
    
    def evaluate_batch(
        self,
        test_cases: List[MultiHopTestCase],
        system_responses: List[SystemResponse],
        use_ragas: bool = True
    ) -> List[EvaluationResult]:
        """
        Evaluate multiple test cases.
        
        Args:
            test_cases: List of test cases
            system_responses: Corresponding system responses
            use_ragas: Whether to compute Ragas metrics
        
        Returns:
            List of evaluation results
        """
        if len(test_cases) != len(system_responses):
            raise ValueError("Number of test cases and responses must match")
        
        results = []
        for test_case, response in zip(test_cases, system_responses):
            result = self.evaluate_single(test_case, response, use_ragas=use_ragas)
            results.append(result)
        
        return results
    
    def _compute_ragas_metrics(
        self,
        question: str,
        answer: str,
        contexts: List[str],
        ground_truth: str
    ) -> Dict[str, float]:
        """
        Compute Ragas metrics for a single Q&A pair.
        
        Args:
            question: The question
            answer: System's answer
            contexts: Retrieved context chunks
            ground_truth: Gold standard answer
        
        Returns:
            Dictionary of Ragas metric scores
        """
        try:
            data = {
                "question": [question],
                "answer": [answer],
                "contexts": [contexts],
                "ground_truth": [ground_truth],
            }
            
            dataset = Dataset.from_dict(data)
            
            result = evaluate(
                dataset,
                metrics=[
                    answer_correctness,
                    faithfulness,
                    answer_relevancy,
                    context_precision,
                    context_recall,
                ],
                llm=self.llm,
            )
            
            return result.to_pandas().iloc[0].to_dict()
        
        except Exception as e:
            print(f"Warning: Ragas evaluation failed: {e}")
            return {}
    
    def generate_report(
        self,
        results: List[EvaluationResult],
        output_path: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Generate evaluation report.
        
        Args:
            results: List of evaluation results
            output_path: Optional path to save CSV report
        
        Returns:
            DataFrame with evaluation results
        """
        records = []
        for result in results:
            record = {
                "test_case_id": result.test_case_id,
                "question": result.question,
                "chain_coverage": result.chain_coverage_score,
                "step_coverage": result.step_coverage_score,
                "answer_correctness": result.answer_correctness,
                "faithfulness": result.faithfulness,
                "answer_relevancy": result.answer_relevancy,
                "context_precision": result.context_precision,
                "context_recall": result.context_recall,
                "num_missing_chunks": len(result.missing_chunks),
                "num_extra_chunks": len(result.extra_chunks),
            }
            records.append(record)
        
        df = pd.DataFrame(records)
        
        aggregate = calculate_aggregate_metrics(results)
        print("\n" + "="*60)
        print("AGGREGATE METRICS")
        print("="*60)
        for key, value in aggregate.items():
            print(f"{key}: {value:.4f}" if isinstance(value, float) else f"{key}: {value}")
        print("="*60 + "\n")
        
        if output_path:
            df.to_csv(output_path, index=False)
            print(f"Report saved to: {output_path}")
        
        return df
    
    def print_detailed_result(self, result: EvaluationResult) -> None:
        """Print detailed evaluation result for a single test case."""
        print("\n" + "="*60)
        print(f"Question: {result.question}")
        print("-"*60)
        print(f"Chain Coverage Score: {result.chain_coverage_score:.2f}")
        print(f"Step Coverage Score: {result.step_coverage_score:.2f}")
        
        if result.answer_correctness is not None:
            print(f"Answer Correctness: {result.answer_correctness:.2f}")
        if result.faithfulness is not None:
            print(f"Faithfulness: {result.faithfulness:.2f}")
        if result.answer_relevancy is not None:
            print(f"Answer Relevancy: {result.answer_relevancy:.2f}")
        
        if result.missing_chunks:
            print(f"\nMissing Chunks ({len(result.missing_chunks)}): {result.missing_chunks}")
        if result.extra_chunks:
            print(f"Extra Chunks ({len(result.extra_chunks)}): {result.extra_chunks}")
        
        print("="*60 + "\n")
