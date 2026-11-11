# IncidentForge

**Synthetic post-mortem and chaos scenario generator for observability testing, RAG pipelines, and incident response training.**

IncidentForge generates realistic incident reports from system topology YAML, producing JSONL datasets and Markdown reports without exposing real production data.

## Features

- **Schema-first development** — Pydantic v2 models with JSON Schema export
- **Provider-agnostic LLM abstraction** — Supports OpenAI, vLLM, Ollama, NVIDIA NIM, OpenRouter via `base_url`
- **Deterministic task planning** — Cartesian product with seed-based reproducibility
- **Multi-layer validation** — Schema (Pydantic), Semantic (chronology, duration, topology), Security (PII/secrets)
- **Semantic deduplication** — Embeddings (sentence-transformers) + MinHash (datasketch) with category balance
- **Multi-format export** — JSONL, Markdown, Parquet with async I/O
- **Quality reporting** — Statistics, diversity metrics, Hugging Face dataset card
- **State persistence** — Resume capability via `.incidentforge/state.jsonl`
- **Security** — API keys via env vars only, PII scanning, gitleaks in CI

## Installation

```bash
# Using uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

## Quick Start

```bash
# 1. Create sample configuration files
incidentforge init configs

# 2. Preview generation plan
incidentforge plan -t configs/topology.yaml -f configs/failures.yaml --dry-run

# 3. Generate incidents (requires LLM API key)
export INCIDENTFORGE_API_KEY="your-api-key"
incidentforge generate -t configs/topology.yaml -f configs/failures.yaml -o output

# 4. Validate generated incidents
incidentforge validate output

# 5. Deduplicate incidents
incidentforge dedup output

# 6. Export to multiple formats
incidentforge export output --formats jsonl,markdown,parquet

# 7. Generate quality report
incidentforge report output
```

## Configuration

### Topology YAML

Defines your system architecture:

```yaml
version: "1.0"
services:
  - name: "api-gateway"
    technology:
      - name: "nginx"
        category: "network"
      - name: "Go"
        category: "compute"
    slo:
      availability_target: 0.9995
      latency_p99_ms: 100
    dependencies:
      - target: "auth-service"
        traffic_percentage: 90.0
    team: "platform-team"
```

### Failure Catalog YAML

Defines failure categories and their characteristics:

```yaml
version: "1.0"
failures:
  - category: "Connection Leak"
    name: "Database Connection Leak"
    description: "Application fails to return database connections to the pool"
    applicable_technologies: ["PostgreSQL", "MySQL", "HikariCP", "pgBouncer"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 10
    max_duration_minutes: 120
    tags: ["database", "resource-exhaustion"]
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `init` | Create sample topology and failure catalog configuration files |
| `plan` | Preview generation plan without executing |
| `generate` | Generate synthetic incident reports |
| `validate` | Validate generated incidents (schema, semantic, security) |
| `dedup` | Deduplicate incidents using semantic similarity |
| `export` | Export incidents to multiple formats (JSONL, Markdown, Parquet) |
| `report` | Generate quality report and dataset card |
| `schema` | Export JSON schema for Incident model |

## LLM Configuration

IncidentForge supports any OpenAI-compatible API:

```bash
# OpenAI
export INCIDENTFORGE_API_KEY="sk-..."
incidentforge generate --model gpt-4o-mini

# vLLM / Ollama / NIM / OpenRouter
incidentforge generate --model llama-3.1-70b --base-url http://localhost:8000/v1
```

## Output Formats

### JSONL (default)
One incident per line, ideal for ML pipelines:
```json
{"incident_id": "inc-abc123", "title": "Database Connection Leak in auth-service", ...}
```

### Markdown
Human-readable post-mortem reports:
```markdown
# Incident Report: inc-abc123

## Summary
Database Connection Leak in auth-service caused 45min outage...

## Timeline
- 2024-01-15T10:00:00Z - Connection pool exhaustion detected
- 2024-01-15T10:15:00Z - Alert fired, on-call paged
...
```

### Parquet
Columnar format for analytics:
```bash
incidentforge export output --formats parquet
```

## Quality Report

Generates a comprehensive quality report with:
- Incident count and distribution statistics
- Severity, style, language diversity metrics
- Category balance analysis
- Hugging Face dataset card (YAML frontmatter)

## Vector Search Examples

Ready-to-use semantic search demos:
- `examples/vector_search/chroma/` — ChromaDB example
- `examples/vector_search/pgvector/` — pgvector example
- `examples/vector_search/docker-compose.yml` — Start both databases

```bash
cd examples/vector_search
docker-compose up -d
python chroma/search_example.py
python pgvector/search_example.py
```

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=incidentforge --cov-report=html

# Lint
ruff check .

# Type check
mypy incidentforge
```

## Project Structure

```
incidentforge/
├── cli.py              # Typer CLI interface
├── models.py           # Pydantic schemas (Topology, FailureCatalog, Incident)
├── topology.py         # Topology loader & validator
├── failures.py         # Failure catalog loader
├── planner.py          # Deterministic task planner
├── client.py           # LLM client abstraction
├── retry.py            # Retry policies
├── generator.py        # Async generation orchestrator
├── prompts.py          # Jinja2 prompt templates
├── validators.py       # Multi-layer validation
├── dedup.py            # Semantic deduplication
├── exporter.py         # Multi-format exporters
├── report.py           # Quality reporting
└── __init__.py         # Package exports
```

## Requirements

- Python 3.11+
- Dependencies: typer, rich, pydantic, pyyaml, jinja2, openai, httpx, tenacity, aiofiles, structlog, faker, sentence-transformers, datasketch, numpy, pandas, pyarrow

## License

MIT License — see [LICENSE](LICENSE) for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest tests/`
5. Submit a pull request

## Citation

If you use IncidentForge in your research, please cite:

```bibtex
@software{incidentforge,
  title = {IncidentForge: Synthetic Post-Mortem Generator},
  author = {IncidentForge Contributors},
  year = {2024},
  url = {https://github.com/PauloHFA/IncidentForge}
}
```