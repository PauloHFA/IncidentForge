"""
pgvector Vector Search Example for IncidentForge.

This example demonstrates how to use PostgreSQL with pgvector extension
to store and search IncidentForge-generated incidents using semantic similarity.

Requirements:
- PostgreSQL with pgvector extension installed
- psycopg2 or asyncpg for database connectivity
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import asyncpg
from sentence_transformers import SentenceTransformer

from incidentforge.models import Incident


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


async def setup_database(
    dsn: str,
    embedding_dim: int = 384,  # paraphrase-multilingual-MiniLM-L12-v2 dimension
) -> asyncpg.Connection:
    """Set up database with pgvector extension and incidents table."""
    conn = await asyncpg.connect(dsn)

    # Enable pgvector extension
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create incidents table
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY,
            service TEXT NOT NULL,
            severity TEXT NOT NULL,
            category TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL,
            document TEXT NOT NULL,
            metadata JSONB NOT NULL,
            embedding VECTOR({embedding_dim})
        )
    """)

    # Create index for vector similarity search
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS incidents_embedding_idx
        ON incidents USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)

    # Create indexes for metadata filtering
    await conn.execute("CREATE INDEX IF NOT EXISTS incidents_service_idx ON incidents (service)")
    await conn.execute("CREATE INDEX IF NOT EXISTS incidents_severity_idx ON incidents (severity)")
    await conn.execute("CREATE INDEX IF NOT EXISTS incidents_category_idx ON incidents (category)")

    print("Database schema created/verified")
    return conn


async def index_incidents(
    conn: asyncpg.Connection,
    incidents: list[Incident],
    embedding_model: SentenceTransformer,
    batch_size: int = 100,
) -> None:
    """Index incidents in PostgreSQL with pgvector."""
    print(f"Generating embeddings for {len(incidents)} incidents...")

    # Prepare data
    documents = [incident_to_text(incident) for incident in incidents]
    embeddings = embedding_model.encode(documents, show_progress_bar=True, batch_size=batch_size)

    # Insert in batches
    for i in range(0, len(incidents), batch_size):
        batch_incidents = incidents[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size]

        # Prepare values for batch insert
        values = []
        for incident, embedding in zip(batch_incidents, batch_embeddings):
            metadata = {
                "service": incident.service,
                "severity": incident.severity.value,
                "category": incident.failure_category.value,
                "duration_minutes": incident.outage_duration_minutes,
                "generated_at": incident.metadata.generated_at,
                "model": incident.metadata.model,
                "prompt_version": incident.metadata.prompt_version,
                "seed": incident.metadata.seed,
            }

            values.append((
                incident.id,
                incident.service,
                incident.severity.value,
                incident.failure_category.value,
                incident.outage_duration_minutes,
                incident.metadata.generated_at,
                documents[i + batch_incidents.index(incident)],
                json.dumps(metadata),
                embedding.tolist(),
            ))

        # Batch insert
        await conn.executemany("""
            INSERT INTO incidents (id, service, severity, category, duration_minutes, generated_at, document, metadata, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (id) DO UPDATE SET
                service = EXCLUDED.service,
                severity = EXCLUDED.severity,
                category = EXCLUDED.category,
                duration_minutes = EXCLUDED.duration_minutes,
                generated_at = EXCLUDED.generated_at,
                document = EXCLUDED.document,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding
        """, values)

        print(f"  Indexed batch {i // batch_size + 1}/{(len(incidents) + batch_size - 1) // batch_size}")

    print(f"Indexed {len(incidents)} incidents in PostgreSQL")


async def search_incidents(
    conn: asyncpg.Connection,
    query: str,
    embedding_model: SentenceTransformer,
    n_results: int = 5,
    filter_service: str | None = None,
    filter_severity: str | None = None,
    filter_category: str | None = None,
) -> list[dict[str, Any]]:
    """Search incidents by semantic similarity with optional metadata filters."""
    query_embedding = embedding_model.encode([query]).tolist()[0]

    # Build query with optional filters
    where_clauses = []
    params = [query_embedding, n_results]
    param_idx = 3

    if filter_service:
        where_clauses.append(f"service = ${param_idx}")
        params.append(filter_service)
        param_idx += 1

    if filter_severity:
        where_clauses.append(f"severity = ${param_idx}")
        params.append(filter_severity)
        param_idx += 1

    if filter_category:
        where_clauses.append(f"category = ${param_idx}")
        params.append(filter_category)
        param_idx += 1

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query_sql = f"""
        SELECT id, service, severity, category, duration_minutes, generated_at, document, metadata,
               1 - (embedding <=> $1) AS similarity
        FROM incidents
        {where_sql}
        ORDER BY embedding <=> $1
        LIMIT $2
    """

    rows = await conn.fetch(query_sql, *params)

    results = []
    for row in rows:
        results.append({
            "id": row["id"],
            "service": row["service"],
            "severity": row["severity"],
            "category": row["category"],
            "duration_minutes": row["duration_minutes"],
            "generated_at": row["generated_at"],
            "document": row["document"],
            "metadata": row["metadata"],
            "similarity": float(row["similarity"]),
        })

    return results


def print_search_results(results: list[dict[str, Any]]) -> None:
    """Print search results in a readable format."""
    if not results:
        print("No results found.")
        return

    print(f"\nFound {len(results)} results:")
    print("-" * 80)

    for i, result in enumerate(results):
        print(f"\n{i+1}. {result['id']} (similarity: {result['similarity']:.3f})")
        print(f"   Service: {result['service']}")
        print(f"   Severity: {result['severity']}")
        print(f"   Category: {result['category']}")
        print(f"   Duration: {result['duration_minutes']} min")
        print(f"   Preview: {result['document'][:200]}...")


async def main():
    """Main example function."""
    # Configuration
    input_dir = Path("output")  # Directory with generated incidents
    dsn = os.environ.get("POSTGRES_DSN", "postgresql://postgres:postgres@localhost:5432/incidentforge")

    # Load incidents
    print("Loading incidents...")
    incidents = await load_incidents(input_dir)
    print(f"Loaded {len(incidents)} incidents")

    if not incidents:
        print("No incidents found. Run 'incidentforge generate' first.")
        return

    # Load embedding model
    model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

    # Connect to database
    print("\nConnecting to PostgreSQL...")
    conn = await setup_database(dsn)

    try:
        # Index incidents
        print("\nIndexing incidents in PostgreSQL with pgvector...")
        await index_incidents(conn, incidents, model)

        # Example searches
        print("\n" + "=" * 80)
        print("EXAMPLE SEARCHES")
        print("=" * 80)

        # Search 1: Connection leak incidents
        print("\n1. Searching for 'connection leak database pool exhaustion'")
        results = await search_incidents(
            conn,
            "connection leak database pool exhaustion",
            model,
            n_results=3,
        )
        print_search_results(results)

        # Search 2: High severity incidents
        print("\n2. Searching for 'SEV-1 critical outage'")
        results = await search_incidents(
            conn,
            "SEV-1 critical outage",
            model,
            n_results=3,
        )
        print_search_results(results)

        # Search 3: Cache related incidents
        print("\n3. Searching for 'cache stampede thundering herd'")
        results = await search_incidents(
            conn,
            "cache stampede thundering herd",
            model,
            n_results=3,
        )
        print_search_results(results)

        # Search 4: Filter by service
        print("\n4. Searching for 'memory pressure' in auth-service")
        results = await search_incidents(
            conn,
            "memory pressure",
            model,
            n_results=3,
            filter_service="auth-service",
        )
        print_search_results(results)

        # Search 5: Filter by severity
        print("\n5. Searching for 'timeout' in SEV-2 incidents")
        results = await search_incidents(
            conn,
            "timeout",
            model,
            n_results=3,
            filter_severity="SEV-2",
        )
        print_search_results(results)

        # Search 6: Filter by category
        print("\n6. Searching for 'deadlock' in database category")
        results = await search_incidents(
            conn,
            "deadlock",
            model,
            n_results=3,
            filter_category="Deadlock",
        )
        print_search_results(results)

        print("\n" + "=" * 80)
        print("Example complete!")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())