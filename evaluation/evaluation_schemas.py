from typing import List, Dict, Optional
from pydantic import BaseModel, Field


class ChunkReference(BaseModel):
    """Represents a chunk of information needed to answer the multi-hop query."""
    chunk_id: str = Field(description="Unique identifier for the chunk")
    content: str = Field(description="Content of the chunk")
    source: str = Field(description="Source URL or document")
    reasoning_step: str = Field(
        description="Which part of the multi-hop reasoning this chunk supports"
    )
    node_type: Optional[str] = Field(
        default=None,
        description="Type of knowledge graph node if applicable"
    )


class LogicalChain(BaseModel):
    """Represents the logical chain of reasoning for a multi-hop query."""
    steps: List[str] = Field(
        description="Ordered list of reasoning steps (sub-questions)"
    )
    required_chunks: List[ChunkReference] = Field(
        description="Chunks needed to answer each step"
    )
    
    def get_chunk_ids(self) -> set[str]:
        """Returns set of all required chunk IDs."""
        return {chunk.chunk_id for chunk in self.required_chunks}


class MultiHopTestCase(BaseModel):
    """Test case for multi-hop query evaluation."""
    question: str = Field(description="The multi-hop query to evaluate")
    gold_answer: str = Field(description="Expected answer")
    logical_chain: LogicalChain = Field(
        description="Gold standard logical chain for answering"
    )
    difficulty: str = Field(
        default="medium",
        description="Difficulty level: easy, medium, hard"
    )


class RetrievedContext(BaseModel):
    """Context retrieved by the RAG system."""
    chunk_id: str
    content: str
    source: str
    relevance_score: Optional[float] = None


class SystemResponse(BaseModel):
    """Response from the RAG system being evaluated."""
    question: str
    answer: str
    retrieved_chunks: List[RetrievedContext]
    reasoning_trace: Optional[List[str]] = Field(
        default=None,
        description="Optional trace of reasoning steps taken"
    )
    
    def get_retrieved_chunk_ids(self) -> set[str]:
        """Returns set of retrieved chunk IDs."""
        return {chunk.chunk_id for chunk in self.retrieved_chunks}


class EvaluationResult(BaseModel):
    """Result of evaluating a system response."""
    test_case_id: str
    question: str
    chain_coverage_score: float = Field(
        ge=0.0, le=1.0,
        description="Proportion of required chunks retrieved"
    )
    step_coverage_score: float = Field(
        ge=0.0, le=1.0,
        description="Proportion of reasoning steps covered"
    )
    answer_correctness: Optional[float] = Field(
        default=None,
        description="Ragas answer correctness score"
    )
    answer_relevancy: Optional[float] = Field(
        default=None,
        description="Ragas answer relevancy score"
    )
    faithfulness: Optional[float] = Field(
        default=None,
        description="Ragas faithfulness score"
    )
    context_precision: Optional[float] = Field(
        default=None,
        description="Ragas context precision score"
    )
    context_recall: Optional[float] = Field(
        default=None,
        description="Ragas context recall score"
    )
    missing_chunks: List[str] = Field(
        default_factory=list,
        description="Required chunk IDs that were not retrieved"
    )
    extra_chunks: List[str] = Field(
        default_factory=list,
        description="Retrieved chunk IDs that were not required"
    )
