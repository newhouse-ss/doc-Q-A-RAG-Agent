"""
Evaluation module for multi-hop RAG systems.

Provides schemas, metrics, an orchestrator, and a KG-aware test-set generator.
"""

from evaluation.evaluation_schemas import (
    ChunkReference,
    LogicalChain,
    MultiHopTestCase,
    RetrievedContext,
    SystemResponse,
    EvaluationResult,
)

from evaluation.evaluation_metrics import (
    calculate_chain_coverage,
    calculate_step_coverage,
    evaluate_multi_hop_retrieval,
    calculate_aggregate_metrics,
)

from evaluation.evaluator import MultiHopEvaluator

from evaluation.kg_testset_generator import (
    KGAwareTestsetGenerator,
    KGNodeReference,
    KGAwareTestsetSample,
)
