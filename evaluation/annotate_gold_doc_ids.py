"""
Interactive Gold Doc IDs Annotation Tool

This script helps you annotate gold_doc_ids for evaluation:
1. Runs your RAG pipeline on each question
2. Shows you the retrieved chunks with their IDs
3. Lets you manually mark which chunks are relevant
4. Updates eval_dataset.json with gold_doc_ids

Usage:
    python annotate_gold_doc_ids.py
    
    For each question:
    - Review the retrieved chunks
    - Enter the relevant chunk IDs (comma-separated)
    - Script will update eval_dataset.json
"""

import json
import re
from pathlib import Path
from typing import List, Dict

from langchain_core.messages import HumanMessage
from rag_agent.graph_builder import build_graph
from rag_agent.config import ensure_google_api_key


def extract_chunk_info(context: str) -> List[Dict]:
    """
    Extract citation info from retriever tool output.
    Returns list of dicts with: citation_num, chunk_id, source, snippet
    """
    citations = []
    
    # Split by citation blocks
    blocks = re.split(r'\[CITATION \d+\]', context)
    
    for i, block in enumerate(blocks[1:], start=1):  # Skip first empty split
        chunk_match = re.search(r'CHUNK:\s*(\S+)', block)
        source_match = re.search(r'SOURCE:\s*(.+)', block)
        snippet_match = re.search(r'SNIPPET:\s*(.+)', block)
        
        if chunk_match:
            citations.append({
                'citation_num': i,
                'chunk_id': chunk_match.group(1),
                'source': source_match.group(1).strip() if source_match else 'N/A',
                'snippet': snippet_match.group(1).strip()[:200] + '...' if snippet_match else 'N/A'
            })
    
    return citations


def run_rag_on_question(question: str, graph) -> List[Dict]:
    """Run RAG and return citation info."""
    result = graph.invoke({"messages": [HumanMessage(content=question)]})
    
    messages = result.get("messages", [])
    
    for msg in messages:
        if hasattr(msg, 'type') and msg.type == 'tool' and hasattr(msg, 'content'):
            return extract_chunk_info(msg.content)
    
    return []


def interactive_annotation():
    """Interactive annotation workflow."""
    ensure_google_api_key()
    
    # Load dataset
    dataset_path = Path("eval_dataset.json")
    if not dataset_path.exists():
        print(f"Error: {dataset_path} not found!")
        return
    
    with open(dataset_path, 'r', encoding='utf-8') as f:
        dataset = json.load(f)
    
    print("="*70)
    print("GOLD DOC IDs ANNOTATION TOOL")
    print("="*70)
    print(f"\nLoaded {len(dataset)} questions from {dataset_path}")
    print("\nBuilding RAG pipeline...")
    
    graph = build_graph()
    print("✓ Ready!\n")
    
    # Process each question
    for i, item in enumerate(dataset, 1):
        question = item['question']
        existing_gold = item.get('gold_doc_ids', [])
        
        print("\n" + "="*70)
        print(f"Question {i}/{len(dataset)}")
        print("="*70)
        print(f"\nQ: {question}")
        
        if existing_gold:
            print(f"\nExisting gold_doc_ids: {existing_gold}")
            skip = input("\nSkip this question? (y/n, default=n): ").strip().lower()
            if skip == 'y':
                print("Skipped.")
                continue
        
        print("\nRetrieving documents...")
        citations = run_rag_on_question(question, graph)
        
        if not citations:
            print("⚠️  No citations retrieved!")
            continue
        
        print(f"\n{'='*70}")
        print("RETRIEVED CHUNKS:")
        print("="*70)
        
        for cite in citations:
            print(f"\n[{cite['citation_num']}] Chunk ID: {cite['chunk_id']}")
            print(f"    Source: {cite['source']}")
            print(f"    Snippet: {cite['snippet']}")
        
        print("\n" + "="*70)
        print("ANNOTATION")
        print("="*70)
        print("\nWhich chunks are RELEVANT to answer this question?")
        print("(Consider: Does the chunk contain information needed for the ground truth?)")
        print("\nOptions:")
        print("  - Enter chunk IDs (comma-separated): e.g., 42,108,215")
        print("  - Enter citation numbers: e.g., 1,2")
        print("  - Enter 'all' to mark all chunks as relevant")
        print("  - Enter 'none' or press Enter to skip")
        
        user_input = input("\nYour selection: ").strip()
        
        if not user_input or user_input.lower() == 'none':
            print("No gold_doc_ids added.")
            continue
        
        if user_input.lower() == 'all':
            gold_ids = [cite['chunk_id'] for cite in citations]
        elif ',' in user_input:
            # Check if input is citation numbers or chunk IDs
            parts = [p.strip() for p in user_input.split(',')]
            if all(p.isdigit() and int(p) <= len(citations) for p in parts):
                # Citation numbers
                gold_ids = [citations[int(p)-1]['chunk_id'] for p in parts]
            else:
                # Direct chunk IDs
                gold_ids = parts
        else:
            # Single input
            if user_input.isdigit() and int(user_input) <= len(citations):
                gold_ids = [citations[int(user_input)-1]['chunk_id']]
            else:
                gold_ids = [user_input]
        
        # Update dataset
        item['gold_doc_ids'] = gold_ids
        print(f"\n✓ Added gold_doc_ids: {gold_ids}")
    
    # Save updated dataset
    backup_path = dataset_path.with_suffix('.backup.json')
    print(f"\n{'='*70}")
    print("SAVING RESULTS")
    print("="*70)
    print(f"\nCreating backup: {backup_path}")
    with open(backup_path, 'w', encoding='utf-8') as f:
        with open(dataset_path, 'r', encoding='utf-8') as orig:
            f.write(orig.read())
    
    print(f"Saving updated dataset: {dataset_path}")
    with open(dataset_path, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)
    
    print("\n✓ Done!")
    print(f"\nAnnotated {sum(1 for item in dataset if item.get('gold_doc_ids'))} questions")
    print(f"Backup saved to: {backup_path}")
    print(f"\nNext step: Run `python run_evaluation.py` to see retrieval metrics!")


if __name__ == "__main__":
    import sys
    import os
    
    if "GOOGLE_API_KEY" not in os.environ:
        print("ERROR: GOOGLE_API_KEY not set")
        print("\nSet it with:")
        print("  Windows: $env:GOOGLE_API_KEY='your_key'")
        print("  Mac/Linux: export GOOGLE_API_KEY='your_key'")
        sys.exit(1)
    
    try:
        interactive_annotation()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
