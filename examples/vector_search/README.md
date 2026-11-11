# Vector Search Examples for IncidentForge

This directory contains examples demonstrating how to use vector databases to store and search IncidentForge-generated incidents using semantic similarity.

## Examples

### 1. ChromaDB Example (`chroma/`)

ChromaDB is a lightweight, open-source vector database that's easy to set up and use.

**Requirements:**
```bash
pip install chromadb sentence-transformers
```

**Run:**
```bash
cd chroma
python search_example.py
```

**Features:**
- Local file-based persistence
- Cosine similarity search
- Metadata filtering (service, severity, category)
- No external dependencies

### 2. pgvector Example (`pgvector/`)

pgvector is a PostgreSQL extension for vector similarity search, ideal for production deployments.

**Requirements:**
```bash
pip install asyncpg sentence-transformers
```

**Prerequisites:**
- PostgreSQL with pgvector extension
- Or use the provided Docker Compose file

**Run with Docker:**
```bash
# Start PostgreSQL with pgvector
docker-compose up -d postgres

# Run the example
cd pgvector
POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/incidentforge python search_example.py
```

**Features:**
- Production-ready PostgreSQL backend
- IVFFlat index for fast approximate nearest neighbor search
- Full SQL querying capabilities
- Metadata filtering with standard SQL WHERE clauses
- ACID compliance

## Quick Start

1. **Generate incidents first:**
   ```bash
   incidentforge init
   incidentforge generate --concurrency 4
   ```

2. **Start vector database (choose one):**
   ```bash
   # Option A: ChromaDB (simplest)
   docker-compose up -d chroma

   # Option B: pgvector (production)
   docker-compose up -d postgres
   ```

3. **Run search example:**
   ```bash
   # ChromaDB
   cd chroma
   python search_example.py

   # pgvector
   cd pgvector
   POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/incidentforge python search_example.py
   ```

## Search Capabilities

Both examples support:

- **Semantic search**: Find incidents by natural language queries
- **Metadata filtering**: Filter by service, severity, category, duration
- **Hybrid search**: Combine semantic similarity with exact metadata filters
- **Similarity scores**: Cosine similarity (0-1) for ranking results

## Example Queries

```python
# Find connection leak incidents
search("connection leak database pool exhaustion")

# Find high-severity outages
search("SEV-1 critical outage")

# Find cache-related issues
search("cache stampede thundering herd")

# Filter by service
search("memory pressure", filter_service="auth-service")

# Filter by severity
search("timeout", filter_severity="SEV-2")

# Filter by category
search("deadlock", filter_category="Deadlock")
```

## Architecture

```
IncidentForge Incidents (JSONL)
         │
         ▼
┌─────────────────────────────────────┐
│  Text Representation                │
│  (service + category + root_cause   │
│   + timeline + actions)             │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Embedding Model                    │
│  (sentence-transformers/            │
│   paraphrase-multilingual-          │
│   MiniLM-L12-v2)                    │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Vector Database                    │
│  (ChromaDB or pgvector)             │
│  - Vector index (HNSW/IVFFlat)      │
│  - Metadata indexes                 │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Semantic Search                    │
│  - Query embedding                  │
│  - Cosine similarity                │
│  - Metadata filtering               │
└─────────────────────────────────────┘
```

## Embedding Model

The examples use `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` which:
- Supports 50+ languages (including Portuguese)
- 384-dimensional embeddings
- Fast inference (~2000 sentences/second on CPU)
- Good quality for semantic similarity tasks

## Production Considerations

### ChromaDB
- Good for development, testing, small datasets (<100k vectors)
- Single-node only
- No built-in replication or HA

### pgvector
- Production-ready with PostgreSQL ecosystem
- Supports replication, backup, monitoring
- Can scale with read replicas
- Integrates with existing PostgreSQL tooling
- Supports exact (HNSW) and approximate (IVFFlat) indexes

## Customization

To use a different embedding model:

```python
model = SentenceTransformer("your-model-name")
# Update embedding_dim in pgvector setup if dimension changes
```

To add custom metadata fields:

```python
metadata = {
    "service": incident.service,
    "severity": incident.severity.value,
    "category": incident.failure_category.value,
    "duration_minutes": incident.outage_duration_minutes,
    "custom_field": "your_value",  # Add custom fields
}
```

## Troubleshooting

### ChromaDB connection issues
- Ensure port 8000 is available
- Check `docker-compose logs chroma`

### pgvector connection issues
- Ensure PostgreSQL is running: `docker-compose logs postgres`
- Verify pgvector extension: `SELECT * FROM pg_extension WHERE extname = 'vector'`
- Check DSN format: `postgresql://user:pass@host:port/dbname`

### Out of memory during embedding
- Reduce batch_size in `index_incidents()`
- Use smaller embedding model
- Process in smaller chunks