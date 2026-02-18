"""
KG-Aware Testset Generator for Multi-Hop RAG Evaluation.

This module generates test cases that track which knowledge graph nodes
are needed to answer each query, enabling evaluation of logical chain coverage.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from ragas.testset import TestsetGenerator
from ragas.testset.synthesizers import (
    MultiHopAbstractQuerySynthesizer,
    MultiHopSpecificQuerySynthesizer,
    default_query_distribution,
)
from langchain_core.documents import Document

from evaluation.evaluation_schemas import (
    MultiHopTestCase,
    LogicalChain,
    ChunkReference,
)
from rag_agent.models import get_llm_model, get_embeddings_model


class KGNodeReference(BaseModel):
    """Reference to a knowledge graph node."""
    node_id: str
    node_type: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    content: str


class KGAwareTestsetSample(BaseModel):
    """Test sample with KG node tracking."""
    question: str
    answer: str
    reasoning_steps: List[str] = Field(default_factory=list)
    required_nodes: List[KGNodeReference] = Field(default_factory=list)
    source_documents: List[str] = Field(default_factory=list)
    query_type: str = "multi_hop"
    
    def to_multi_hop_test_case(self) -> MultiHopTestCase:
        """Convert to MultiHopTestCase format for evaluation."""
        
        # Convert KG nodes to ChunkReferences
        chunk_refs = []
        for i, node in enumerate(self.required_nodes):
            # Map reasoning steps to nodes
            step_idx = min(i, len(self.reasoning_steps) - 1)
            reasoning_step = (
                self.reasoning_steps[step_idx] 
                if self.reasoning_steps 
                else f"Step {i+1}"
            )
            
            chunk_refs.append(
                ChunkReference(
                    chunk_id=node.node_id,
                    content=node.content,
                    source=node.properties.get("source", "knowledge_graph"),
                    reasoning_step=reasoning_step
                )
            )
        
        logical_chain = LogicalChain(
            steps=self.reasoning_steps if self.reasoning_steps else ["Retrieve and synthesize information"],
            required_chunks=chunk_refs
        )
        
        return MultiHopTestCase(
            question=self.question,
            gold_answer=self.answer,
            logical_chain=logical_chain,
            difficulty="medium"
        )


class KGAwareTestsetGenerator:
    """
    Generates test cases with knowledge graph node tracking.
    
    This generator extends Ragas testset generation to track which KG nodes
    are required to answer each multi-hop query, enabling evaluation of
    whether the RAG system retrieves the complete logical chain.
    """
    
    def __init__(
        self,
        llm=None,
        embeddings=None,
        query_distribution=None
    ):
        """
        Initialize the generator.
        
        Args:
            llm: Language model for generation
            embeddings: Embedding model
            query_distribution: List of (synthesizer, proportion) tuples or None for default
        """
        self.llm = llm or get_llm_model()
        self.embeddings = embeddings or get_embeddings_model()
        
        # Use default distribution or provided one
        if query_distribution is None:
            # Create multi-hop focused distribution
            self.query_distribution = [
                (MultiHopAbstractQuerySynthesizer(llm=self.llm), 0.4),
                (MultiHopSpecificQuerySynthesizer(llm=self.llm), 0.4),
            ]
        else:
            self.query_distribution = query_distribution
        
        self.generator = TestsetGenerator(
            llm=self.llm,
            embedding_model=self.embeddings,
        )
    
    def generate_from_documents(
        self,
        documents: List[Document],
        num_samples: int = 10,
        track_nodes: bool = True,
    ) -> List[KGAwareTestsetSample]:
        """
        Generate test cases from documents with KG node tracking.
        
        Args:
            documents: Source documents
            num_samples: Number of test samples to generate
            track_nodes: Whether to track KG nodes
        
        Returns:
            List of test samples with node tracking
        """
        # Generate testset using Ragas
        testset = self.generator.generate_with_langchain_docs(
            documents=documents,
            testset_size=num_samples,
            query_distribution=self.query_distribution,
        )
        
        # Convert to KG-aware samples
        kg_samples = []
        for sample in testset.samples:
            kg_sample = self._create_kg_aware_sample(sample, documents)
            kg_samples.append(kg_sample)
        
        return kg_samples
    
    def _create_kg_aware_sample(
        self,
        ragas_sample: Any,
        documents: List[Document]
    ) -> KGAwareTestsetSample:
        """
        Create KG-aware sample from Ragas sample.
        
        Extracts which nodes/chunks support the query and tracks them.
        """
        # Extract basic fields
        question = getattr(ragas_sample, 'question', '') or getattr(ragas_sample, 'user_input', '')
        answer = getattr(ragas_sample, 'answer', '') or getattr(ragas_sample, 'reference', '')
        
        # Extract reasoning steps if available
        reasoning_steps = []
        if hasattr(ragas_sample, 'reasoning_steps'):
            reasoning_steps = ragas_sample.reasoning_steps
        elif hasattr(ragas_sample, 'reference_contexts'):
            # Infer steps from contexts
            contexts = ragas_sample.reference_contexts
            for i, _ in enumerate(contexts):
                reasoning_steps.append(f"Step {i+1}: Extract information from context")
        
        # Track required nodes
        required_nodes = []
        source_docs = []
        
        # Get reference contexts
        contexts = []
        if hasattr(ragas_sample, 'reference_contexts'):
            contexts = ragas_sample.reference_contexts
        elif hasattr(ragas_sample, 'contexts'):
            contexts = ragas_sample.contexts
        
        # Map contexts to document nodes
        for i, context in enumerate(contexts):
            # Find matching document
            matching_doc = self._find_matching_document(context, documents)
            
            if matching_doc:
                node = KGNodeReference(
                    node_id=f"node_{matching_doc.metadata.get('chunk_id', i)}",
                    node_type="document_chunk",
                    properties={
                        "source": matching_doc.metadata.get("source", "unknown"),
                        "chunk_index": i,
                        **matching_doc.metadata
                    },
                    content=context
                )
                required_nodes.append(node)
                
                source = matching_doc.metadata.get("source", "unknown")
                if source not in source_docs:
                    source_docs.append(source)
        
        # Infer query type
        query_type = "multi_hop" if len(required_nodes) > 1 else "single_hop"
        
        return KGAwareTestsetSample(
            question=question,
            answer=answer,
            reasoning_steps=reasoning_steps if reasoning_steps else [f"Synthesize information from {len(required_nodes)} sources"],
            required_nodes=required_nodes,
            source_documents=source_docs,
            query_type=query_type
        )
    
    def _find_matching_document(
        self,
        context: str,
        documents: List[Document]
    ) -> Optional[Document]:
        """Find document that contains the given context."""
        context_clean = context.strip().lower()
        
        for doc in documents:
            doc_content = doc.page_content.strip().lower()
            # Check for substantial overlap
            if context_clean in doc_content or doc_content in context_clean:
                return doc
            # Check for partial match (>80% overlap)
            overlap = len(set(context_clean.split()) & set(doc_content.split()))
            total = len(set(context_clean.split()))
            if total > 0 and overlap / total > 0.8:
                return doc
        
        return None
    
    def generate_evaluation_dataset(
        self,
        documents: List[Document],
        num_samples: int = 10,
        output_path: Optional[str] = None
    ) -> List[MultiHopTestCase]:
        """
        Generate complete evaluation dataset.
        
        Args:
            documents: Source documents
            num_samples: Number of samples
            output_path: Optional path to save dataset
        
        Returns:
            List of MultiHopTestCase ready for evaluation
        """
        kg_samples = self.generate_from_documents(
            documents=documents,
            num_samples=num_samples,
            track_nodes=True
        )
        
        test_cases = [sample.to_multi_hop_test_case() for sample in kg_samples]
        
        if output_path:
            import json
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(
                    [tc.model_dump() for tc in test_cases],
                    f,
                    indent=2,
                    ensure_ascii=False
                )
            print(f"Saved {len(test_cases)} test cases to {output_path}")
        
        return test_cases
    
    def print_sample_info(self, sample: KGAwareTestsetSample) -> None:
        """Print detailed information about a test sample."""
        print("\n" + "="*70)
        print(f"Question: {sample.question}")
        print("-"*70)
        print(f"Answer: {sample.answer}")
        print("-"*70)
        print(f"Query Type: {sample.query_type}")
        print(f"Reasoning Steps: {len(sample.reasoning_steps)}")
        for i, step in enumerate(sample.reasoning_steps, 1):
            print(f"  {i}. {step}")
        print(f"\nRequired Nodes: {len(sample.required_nodes)}")
        for i, node in enumerate(sample.required_nodes, 1):
            print(f"  Node {i}: {node.node_id}")
            print(f"    Type: {node.node_type}")
            print(f"    Source: {node.properties.get('source', 'unknown')}")
            print(f"    Content preview: {node.content[:100]}...")
        print("="*70)
