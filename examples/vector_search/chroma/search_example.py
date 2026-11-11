"""
Chroma Vector Search Example for IncidentForge.

This example demonstrates how to use ChromaDB to store and search
IncidentForge-generated incidents using semantic similarity.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from incidentforge.models import Incident
from incidentforge.exporter import export_incidents


async def load_incidents(input_dir: Path) -> list[Incident]:
    """Load incidents from JSONL files."""
    incidents = []
    jsonl_files = list(input_dir.rglob("*.jsonl"))

    for file_path in jsonl_files:
        with file_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        incidents.append(Incident.model_validate(data))
                    except Exception as e:
                        print(f"Warning: Failed to parse line in {file_path}: {e}")

    return incidents


def create_chroma_client(persist_dir: Path) -> chromadb.Client:
    """Create ChromaDB client with persistence."""
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.Client(Settings(
        persist_directory=str(persist_dir),
        anonymized_telemetry=False,
    ))


def get_embedding_model(model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2") -> SentenceTransformer:
    """Load sentence transformer model for embeddings."""
    return SentenceTransformer(model_name)


def incident_to_text(incident: Incident) -> str:
    """Convert incident to searchable text."""
    parts = [
        f"Service: {incident.service}",
        f"Category: {incident.failure_category.value}",
        f"Severity: {incident.severity.value}",
        f"Root Cause: {incident.root_cause_analysis}",
        f"Timeline: {' '.join(e.event for e in incident.timeline)}",
        f"Actions: {' '.join(item.action for item in incident.action_items)}",
    ]
    return " | ".join(parts)


async def index_incidents(
    incidents: list[Incident],
    collection_name: str = "incidents",
    persist_dir: Path = Path("./chroma_db"),
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
) -> chromadb.Collection:
    """Index incidents in ChromaDB."""
    client = create_chroma_client(persist_dir)
    model = get_embedding_model(embedding_model)

    # Create or get collection
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # Prepare data
    ids = [incident.id for incident in incidents]
    documents = [incident_to_text(incident) for incident in incidents]
    metadatas = [
        {
            "service": incident.service,
            "severity": incident.severity.value,
            "category": incident.failure_category.value,
            "duration_minutes": incident.outage_duration_minutes,
            "generated_at": incident.metadata.generated_at,
        }
        for incident in incidents
    ]

    # Generate embeddings
    print(f"Generating embeddings for {len(incidents)} incidents...")
    embeddings = model.encode(documents, show_progress_bar=True).tolist()

    # Add to collection
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )

    print(f"Indexed {len(incidents)} incidents in collection '{collection_name}'")
    return collection


def search_incidents(
    query: str,
    collection: chromadb.Collection,
    embedding_model: SentenceTransformer,
    n_results: int = 5,
    filter_metadata: dict | None = None,
) -> dict[str, Any]:
    """Search incidents by semantic similarity."""
    query_embedding = embedding_model.encode([query]).tolist()[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=filter_metadata,
        include=["documents", "metadatas", "distances"],
    )

    return results


def print_search_results(results: dict[str, Any]) -> None:
    """Print search results in a readable format."""
    if not results["ids"] or not results["ids"][0]:
        print("No results found.")
        return

    print(f"\nFound {len(results['ids'][0])} results:")
    print("-" * 80)

    for i, (doc_id, document, metadata, distance) in enumerate(zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    )):
        similarity = 1 - distance
        print(f"\n{i+1}. {doc_id} (similarity: {similarity:.3f})")
        print(f"   Service: {metadata['service']}")
        print(f"   Severity: {metadata['severity']}")
        print(f"   Category: {metadata['category']}")
        print(f"   Duration: {metadata['duration_minutes']} min")
        print(f"   Preview: {document[:200]}...")


async def main():
    """Main example function."""
    # Configuration
    input_dir = Path("output")  # Directory with generated incidents
    persist_dir = Path("./chroma_db")
    collection_name = "incidents"

    # Load incidents
    print("Loading incidents...")
    incidents = await load_incidents(input_dir)
    print(f"Loaded {len(incidents)} incidents")

    if not incidents:
        print("No incidents found. Run 'incidentforge generate' first.")
        return

    # Index incidents
    print("\nIndexing incidents in ChromaDB...")
    collection = await index_incidents(incidents, collection_name, persist_dir)

    # Load embedding model for queries
    model = get_embedding_model()

    # Example searches
    print("\n" + "=" * 80)
    print("EXAMPLE SEARCHES")
    print("=" * 80)

    # Search 1: Connection leak incidents
    print("\n1. Searching for 'connection leak database pool exhaustion'")
    results = search_incidents(
        "connection leak database pool exhaustion",
        collection,
        model,
        n_results=3,
    )
    print_search_results(results)

    # Search 2: High severity incidents
    print("\n2. Searching for 'SEV-1 critical outage'")
    results = search_incidents(
        "SEV-1 critical outage",
        collection,
        model,
        n_results=3,
    )
    print_search_results(results)

    # Search 3: Cache related incidents
    print("\n3. Searching for 'cache stampede thundering herd'")
    results = search_incidents(
        "cache stampede thundering herd",
        collection,
        model,
        n_results=3,
    )
    print_search_results(results)

    # Search 4: Filter by service
    print("\n4. Searching for 'memory pressure' in auth-service")
    results = search_incidents(
        "memory pressure",
        collection,
        model,
        n_results=3,
        filter_metadata={"service": "auth-service"},
    )
    print_search_results(results)

    # Search 5: Filter by severity
    print("\n5. Searching for 'timeout' in SEV-2 incidents")
    results = search_incidents(
        "timeout",
        collection,
        model,
        n_results=3,
        filter_metadata={"severity": "SEV-2"},
    )
    print_search_results(results)

    print("\n" + "=" * 80)
    print("Example complete!")
    print(f"ChromaDB persisted to: {persist_dir.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())