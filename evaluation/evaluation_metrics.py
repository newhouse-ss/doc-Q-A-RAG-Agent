from typing import List, Set, Dict, Tuple
from evaluation.evaluation_schemas import (
    MultiHopTestCase,
    SystemResponse,
    EvaluationResult,
    LogicalChain,
)


def calculate_chain_coverage(
    required_chunk_ids: Set[str],
    retrieved_chunk_ids: Set[str]
) -> Tuple[float, List[str], List[str]]:
    """
    Calculate how well the retrieved chunks cover the required logical chain.
    
    Args:
        required_chunk_ids: Set of chunk IDs needed to answer the query
        retrieved_chunk_ids: Set of chunk IDs retrieved by the system
    
    Returns:
        Tuple of (coverage_score, missing_chunks, extra_chunks)
    """
    if not required_chunk_ids:
        return 1.0, [], list(retrieved_chunk_ids)
    
    covered = required_chunk_ids.intersection(retrieved_chunk_ids)
    coverage_score = len(covered) / len(required_chunk_ids)
    
    missing_chunks = list(required_chunk_ids - retrieved_chunk_ids)
    extra_chunks = list(retrieved_chunk_ids - required_chunk_ids)
    
    return coverage_score, missing_chunks, extra_chunks


def calculate_step_coverage(
    logical_chain: LogicalChain,
    retrieved_chunk_ids: Set[str]
) -> float:
    """
    Calculate what proportion of reasoning steps are covered by retrieved chunks.
    
    This checks if at least one required chunk for each reasoning step was retrieved.
    
    Args:
        logical_chain: The gold standard logical chain
        retrieved_chunk_ids: Set of retrieved chunk IDs
    
    Returns:
        Proportion of steps that have at least one supporting chunk retrieved (0.0-1.0)
    """
    if not logical_chain.steps:
        return 1.0
    
    steps_to_chunks: Dict[str, Set[str]] = {}
    for chunk in logical_chain.required_chunks:
        step = chunk.reasoning_step
        if step not in steps_to_chunks:
            steps_to_chunks[step] = set()
        steps_to_chunks[step].add(chunk.chunk_id)
    
    covered_steps = 0
    for step, required_chunks in steps_to_chunks.items():
        if required_chunks.intersection(retrieved_chunk_ids):
            covered_steps += 1
    
    return covered_steps / len(steps_to_chunks) if steps_to_chunks else 1.0


def evaluate_multi_hop_retrieval(
    test_case: MultiHopTestCase,
    system_response: SystemResponse
) -> EvaluationResult:
    """
    Evaluate a system's performance on a multi-hop query.
    
    This is the core custom metric that measures logical chain coverage.
    
    Args:
        test_case: The test case with gold standard logical chain
        system_response: The system's response to evaluate
    
    Returns:
        EvaluationResult with chain coverage and step coverage scores
    """
    required_chunk_ids = test_case.logical_chain.get_chunk_ids()
    retrieved_chunk_ids = system_response.get_retrieved_chunk_ids()
    
    chain_coverage, missing, extra = calculate_chain_coverage(
        required_chunk_ids,
        retrieved_chunk_ids
    )
    
    step_coverage = calculate_step_coverage(
        test_case.logical_chain,
        retrieved_chunk_ids
    )
    
    return EvaluationResult(
        test_case_id=f"test_{hash(test_case.question) % 10000}",
        question=test_case.question,
        chain_coverage_score=chain_coverage,
        step_coverage_score=step_coverage,
        missing_chunks=missing,
        extra_chunks=extra
    )


def calculate_aggregate_metrics(results: List[EvaluationResult]) -> Dict[str, float]:
    """
    Calculate aggregate metrics across multiple evaluation results.
    
    Args:
        results: List of evaluation results
    
    Returns:
        Dictionary of aggregate metrics
    """
    if not results:
        return {}
    
    total_chain_coverage = sum(r.chain_coverage_score for r in results)
    total_step_coverage = sum(r.step_coverage_score for r in results)
    
    metrics = {
        "avg_chain_coverage": total_chain_coverage / len(results),
        "avg_step_coverage": total_step_coverage / len(results),
        "num_test_cases": len(results),
        "perfect_coverage_count": sum(1 for r in results if r.chain_coverage_score == 1.0),
        "perfect_coverage_rate": sum(1 for r in results if r.chain_coverage_score == 1.0) / len(results),
    }
    
    if any(r.answer_correctness is not None for r in results):
        valid_correctness = [r.answer_correctness for r in results if r.answer_correctness is not None]
        if valid_correctness:
            metrics["avg_answer_correctness"] = sum(valid_correctness) / len(valid_correctness)
    
    if any(r.faithfulness is not None for r in results):
        valid_faithfulness = [r.faithfulness for r in results if r.faithfulness is not None]
        if valid_faithfulness:
            metrics["avg_faithfulness"] = sum(valid_faithfulness) / len(valid_faithfulness)
    
    return metrics
