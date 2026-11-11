"""Quality reporting and dataset card generation for IncidentForge."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .models import Incident, Language, Severity, FailureCategory, Style
from .dedup import DiversityController


class QualityReporter:
    """Generates quality reports for incident datasets."""

    def __init__(self, incidents: list[Incident]):
        self.incidents = incidents
        self.controller = DiversityController.from_incidents(incidents) if incidents else None

    @classmethod
    def from_incidents(cls, incidents: list[Incident]) -> QualityReporter:
        """Create reporter from incidents."""
        return cls(incidents)

    def generate_report(self) -> dict[str, Any]:
        """Generate comprehensive quality report."""
        if not self.incidents:
            return {"error": "No incidents to report on"}

        report = {
            "summary": self._generate_summary(),
            "distributions": self._generate_distributions(),
            "quality_metrics": self._generate_quality_metrics(),
            "diversity_metrics": self._generate_diversity_metrics(),
            "validation_metrics": self._generate_validation_metrics(),
        }

        return report

    def _generate_summary(self) -> dict[str, Any]:
        """Generate summary statistics."""
        total = len(self.incidents)
        durations = [i.outage_duration_minutes for i in self.incidents]
        timeline_lengths = [len(i.timeline) for i in self.incidents]
        action_counts = [len(i.action_items) for i in self.incidents]
        root_cause_lengths = [len(i.root_cause_analysis) for i in self.incidents]

        return {
            "total_incidents": total,
            "unique_services": len(set(i.service for i in self.incidents)),
            "unique_categories": len(set(i.failure_category for i in self.incidents)),
            "date_range": {
                "earliest": min(i.metadata.generated_at for i in self.incidents),
                "latest": max(i.metadata.generated_at for i in self.incidents),
            },
            "duration_stats": {
                "mean": statistics.mean(durations),
                "median": statistics.median(durations),
                "stdev": statistics.stdev(durations) if len(durations) > 1 else 0,
                "min": min(durations),
                "max": max(durations),
            },
            "timeline_stats": {
                "mean": statistics.mean(timeline_lengths),
                "median": statistics.median(timeline_lengths),
                "min": min(timeline_lengths),
                "max": max(timeline_lengths),
            },
            "action_items_stats": {
                "mean": statistics.mean(action_counts),
                "median": statistics.median(action_counts),
                "min": min(action_counts),
                "max": max(action_counts),
            },
            "root_cause_length_stats": {
                "mean": statistics.mean(root_cause_lengths),
                "median": statistics.median(root_cause_lengths),
                "min": min(root_cause_lengths),
                "max": max(root_cause_lengths),
            },
        }

    def _generate_distributions(self) -> dict[str, Any]:
        """Generate distribution statistics."""
        severity_dist = Counter(i.severity.value for i in self.incidents)
        category_dist = Counter(i.failure_category.value for i in self.incidents)
        service_dist = Counter(i.service for i in self.incidents)
        language_dist = Counter(i.metadata.prompt_version for i in self.incidents)
        style_dist = Counter()

        for i in self.incidents:
            if hasattr(i.metadata, 'style'):
                style_dist[i.metadata.style] += 1

        return {
            "by_severity": dict(severity_dist),
            "by_category": dict(category_dist),
            "by_service": dict(service_dist.most_common(20)),
            "by_language": dict(language_dist),
            "by_style": dict(style_dist),
        }

    def _generate_quality_metrics(self) -> dict[str, Any]:
        """Generate quality metrics."""
        rejection_rate = 0.0
        first_pass_rate = 0.0

        schema_valid = sum(1 for i in self.incidents if self._validate_schema(i))
        schema_rate = schema_valid / len(self.incidents) if self.incidents else 0

        return {
            "rejection_rate": rejection_rate,
            "first_pass_validation_rate": first_pass_rate,
            "schema_validation_rate": schema_rate,
            "total_tokens_estimate": sum(
                (i.metadata.tokens_input or 0) + (i.metadata.tokens_output or 0)
                for i in self.incidents
            ),
        }

    def _generate_diversity_metrics(self) -> dict[str, Any]:
        """Generate diversity metrics."""
        if not self.controller:
            return {}

        stats = self.controller.get_stats()

        all_text = " ".join(
            i.root_cause_analysis + " " + " ".join(e.event for e in i.timeline)
            for i in self.incidents
        )
        words = all_text.split()
        unique_words = set(words)
        lexical_diversity = len(unique_words) / len(words) if words else 0

        cat_dist = stats.get("category_distribution", {})
        if cat_dist:
            probs = list(cat_dist.values())
            entropy = -sum(p * np.log2(p) for p in probs if p > 0)
            max_entropy = np.log2(len(probs))
            balance = entropy / max_entropy if max_entropy > 0 else 0
        else:
            balance = 0

        return {
            "lexical_diversity": lexical_diversity,
            "category_balance": balance,
            "category_distribution": cat_dist,
            "deduplication_stats": {
                "embedding_index_size": stats.get("embedding_index_size", 0),
                "minhash_index_size": stats.get("minhash_index_size", 0),
            },
        }

    def _generate_validation_metrics(self) -> dict[str, Any]:
        """Generate validation metrics."""
        return {
            "schema_valid": 0,
            "semantic_valid": 0,
            "security_valid": 0,
            "total_validated": len(self.incidents),
        }

    def _validate_schema(self, incident: Incident) -> bool:
        """Quick schema validation."""
        try:
            incident.model_dump()
            return True
        except Exception:
            return False

    def to_markdown(self) -> str:
        """Generate Markdown report."""
        report = self.generate_report()

        lines = []
        lines.append("# IncidentForge Dataset Quality Report")
        lines.append("")
        lines.append("Generated: {0}Z".format(datetime.utcnow().isoformat()))
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        lines.append("- **Total Incidents:** {0}".format(report['summary']['total_incidents']))
        lines.append("- **Unique Services:** {0}".format(report['summary']['unique_services']))
        lines.append("- **Unique Categories:** {0}".format(report['summary']['unique_categories']))
        lines.append("- **Date Range:** {0} to {1}".format(
            report['summary']['date_range']['earliest'],
            report['summary']['date_range']['latest']
        ))
        lines.append("")
        lines.append("### Duration Statistics (minutes)")
        lines.append("")
        lines.append("- **Mean:** {0:.1f}".format(report['summary']['duration_stats']['mean']))
        lines.append("- **Median:** {0:.1f}".format(report['summary']['duration_stats']['median']))
        lines.append("- **Std Dev:** {0:.1f}".format(report['summary']['duration_stats']['stdev']))
        lines.append("- **Range:** {0} - {1}".format(
            report['summary']['duration_stats']['min'],
            report['summary']['duration_stats']['max']
        ))
        lines.append("")
        lines.append("### Timeline Statistics")
        lines.append("")
        lines.append("- **Mean Events:** {0:.1f}".format(report['summary']['timeline_stats']['mean']))
        lines.append("- **Median Events:** {0:.1f}".format(report['summary']['timeline_stats']['median']))
        lines.append("- **Range:** {0} - {1}".format(
            report['summary']['timeline_stats']['min'],
            report['summary']['timeline_stats']['max']
        ))
        lines.append("")
        lines.append("### Action Items Statistics")
        lines.append("")
        lines.append("- **Mean:** {0:.1f}".format(report['summary']['action_items_stats']['mean']))
        lines.append("- **Median:** {0:.1f}".format(report['summary']['action_items_stats']['median']))
        lines.append("- **Range:** {0} - {1}".format(
            report['summary']['action_items_stats']['min'],
            report['summary']['action_items_stats']['max']
        ))
        lines.append("")
        lines.append("### Root Cause Length Statistics")
        lines.append("")
        lines.append("- **Mean:** {0:.0f} chars".format(report['summary']['root_cause_length_stats']['mean']))
        lines.append("- **Median:** {0:.0f} chars".format(report['summary']['root_cause_length_stats']['median']))
        lines.append("- **Range:** {0} - {1}".format(
            report['summary']['root_cause_length_stats']['min'],
            report['summary']['root_cause_length_stats']['max']
        ))
        lines.append("")
        lines.append("## Distributions")
        lines.append("")
        lines.append("### By Severity")
        lines.append("")

        for sev, count in sorted(report['distributions']['by_severity'].items()):
            pct = count / report['summary']['total_incidents'] * 100
            lines.append("- **{0}:** {1} ({2:.1f}%)".format(sev, count, pct))

        lines.append("")
        lines.append("### By Failure Category (Top 15)")
        lines.append("")

        for cat, count in sorted(report['distributions']['by_category'].items(), key=lambda x: -x[1])[:15]:
            pct = count / report['summary']['total_incidents'] * 100
            lines.append("- **{0}:** {1} ({2:.1f}%)".format(cat, count, pct))

        lines.append("")
        lines.append("### By Service (Top 15)")
        lines.append("")

        for svc, count in sorted(report['distributions']['by_service'].items(), key=lambda x: -x[1])[:15]:
            pct = count / report['summary']['total_incidents'] * 100
            lines.append("- **{0}:** {1} ({2:.1f}%)".format(svc, count, pct))

        lines.append("")
        lines.append("## Quality Metrics")
        lines.append("")
        lines.append("- **Schema Validation Rate:** {0:.1%}".format(report['quality_metrics']['schema_validation_rate']))
        lines.append("- **First-Pass Validation Rate:** {0:.1%}".format(report['quality_metrics']['first_pass_validation_rate']))
        lines.append("- **Rejection Rate:** {0:.1%}".format(report['quality_metrics']['rejection_rate']))
        lines.append("- **Estimated Total Tokens:** {0:,}".format(report['quality_metrics']['total_tokens_estimate']))
        lines.append("")
        lines.append("## Diversity Metrics")
        lines.append("")
        lines.append("- **Lexical Diversity:** {0:.3f}".format(report['diversity_metrics']['lexical_diversity']))
        lines.append("- **Category Balance (Entropy):** {0:.3f}".format(report['diversity_metrics']['category_balance']))
        lines.append("")
        lines.append("### Category Distribution")
        lines.append("")

        # Sort categories by percentage descending
        cat_items = list(report['diversity_metrics']['category_distribution'].items())
        cat_items.sort(key=lambda x: x[1], reverse=True)
        for cat, pct in cat_items:
            lines.append("- **{0}:** {1:.1%}".format(cat, pct))

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("*Report generated by IncidentForge*")

        return "\n".join(lines)

    def to_json(self) -> str:
        """Generate JSON report."""
        return json.dumps(self.generate_report(), indent=2, default=str, ensure_ascii=False)


class DatasetCardGenerator:
    """Generates Hugging Face dataset card."""

    def __init__(
        self,
        incidents: list[Incident],
        model_name: str = "incidentforge",
        license: str = "MIT",
    ):
        self.incidents = incidents
        self.model_name = model_name
        self.license = license
        self.reporter = QualityReporter.from_incidents(incidents)

    def generate_card(self) -> str:
        """Generate dataset card in Markdown."""
        report = self.reporter.generate_report()
        summary = report["summary"]
        distributions = report["distributions"]
        diversity = report["diversity_metrics"]

        lines = []
        lines.append("---")
        lines.append("license: {0}".format(self.license))
        lines.append("tags:")
        lines.append("  - synthetic-data")
        lines.append("  - incident-postmortem")
        lines.append("  - site-reliability-engineering")
        lines.append("  - chaos-engineering")
        lines.append("  - observability")
        lines.append("  - rag")
        lines.append("  - llm-training")
        lines.append("language:")
        lines.append("  - en")
        lines.append("  - pt")
        lines.append("task_categories:")
        lines.append("  - text-generation")
        lines.append("  - conditional-text-generation")
        lines.append("pretty_name: IncidentForge Synthetic Incidents")
        lines.append("---")
        lines.append("")
        lines.append("# {0} Synthetic Incident Dataset".format(self.model_name))
        lines.append("")
        lines.append("## Dataset Description")
        lines.append("")
        lines.append("This dataset contains synthetically generated production incident post-mortems ")
        lines.append("created by [IncidentForge](https://github.com/incidentforge/incidentforge). ")
        lines.append("The incidents are generated from system topology descriptions using LLMs, ")
        lines.append("and are designed for:")
        lines.append("")
        lines.append("- Training and evaluating RAG systems for incident response")
        lines.append("- Testing observability platforms and alerting systems")
        lines.append("- Incident response team training and tabletop exercises")
        lines.append("- Chaos engineering scenario planning")
        lines.append("- Fine-tuning LLMs for technical incident analysis")
        lines.append("")
        lines.append("**Important:** All incidents in this dataset are 100% synthetic and do not represent ")
        lines.append("real production incidents. They should not be used as factual references for ")
        lines.append("real system failures.")
        lines.append("")
        lines.append("## Dataset Statistics")
        lines.append("")
        lines.append("- **Total Incidents:** {0:,}".format(summary['total_incidents']))
        lines.append("- **Unique Services:** {0}".format(summary['unique_services']))
        lines.append("- **Unique Failure Categories:** {0}".format(summary['unique_categories']))
        lines.append("- **Languages:** English, Portuguese (Brazil)")
        lines.append("- **Styles:** Blameless Formal, Terse, Detailed")
        lines.append("- **Architecture Profiles:** Microservices, Monolith Legacy, Serverless")
        lines.append("")
        lines.append("### Severity Distribution")
        lines.append("")

        for sev, count in sorted(distributions["by_severity"].items()):
            pct = count / summary['total_incidents'] * 100
            lines.append("- **{0}:** {1} ({2:.1f}%)".format(sev, count, pct))

        lines.append("")
        lines.append("### Failure Category Distribution (Top 10)")
        lines.append("")

        for cat, count in sorted(distributions["by_category"].items(), key=lambda x: -x[1])[:10]:
            pct = count / summary['total_incidents'] * 100
            lines.append("- **{0}:** {1} ({2:.1f}%)".format(cat, count, pct))

        lines.append("")
        lines.append("### Service Distribution (Top 10)")
        lines.append("")

        for svc, count in sorted(distributions["by_service"].items(), key=lambda x: -x[1])[:10]:
            pct = count / summary['total_incidents'] * 100
            lines.append("- **{0}:** {1} ({2:.1f}%)".format(svc, count, pct))

        lines.append("")
        lines.append("## Data Fields")
        lines.append("")
        lines.append("| Field | Type | Description |")
        lines.append("|-------|------|-------------|")
        lines.append("| `id` | string | Unique incident ID (INC-YYYY-NNNN) |")
        lines.append("| `service` | string | Affected service name |")
        lines.append("| `severity` | string | SEV-1, SEV-2, SEV-3, or SEV-4 |")
        lines.append("| `outage_duration_minutes` | integer | Outage duration in minutes |")
        lines.append("| `failure_category` | string | Failure category from catalog |")
        lines.append("| `sla_impact` | object | Availability before/after, P99 latency |")
        lines.append("| `root_cause_analysis` | string | Root cause analysis (min 150 chars) |")
        lines.append("| `timeline` | array | Chronological events (min 5) |")
        lines.append("| `action_items` | array | 2-8 action items with owner/priority |")
        lines.append("| `metadata` | object | Generation metadata (model, seed, etc.) |")
        lines.append("")
        lines.append("## Data Splits")
        lines.append("")
        lines.append("The dataset is provided as a single split (`train`) containing all incidents. ")
        lines.append("Users can create their own splits based on severity, category, service, or other criteria.")
        lines.append("")
        lines.append("## Generation Method")
        lines.append("")
        lines.append("Incidents are generated using a multi-stage pipeline:")
        lines.append("")
        lines.append("1. **Topology Definition**: System topology described in YAML (services, technologies, dependencies, SLOs)")
        lines.append("2. **Failure Catalog**: 30+ failure categories across database, network, messaging, compute, cache, deploy")
        lines.append("3. **Task Planning**: Deterministic cartesian product of services x failures x severities with seed-based reproducibility")
        lines.append("4. **LLM Generation**: Structured output via JSON schema with provider-agnostic client (OpenAI, vLLM, Ollama, NIM)")
        lines.append("5. **Multi-Layer Validation**: Schema (Pydantic), Semantic (chronology, topology consistency), Security (PII/secrets)")
        lines.append("6. **Deduplication**: Semantic similarity (embeddings + MinHash) with category balance enforcement")
        lines.append("7. **Export**: Markdown, JSONL, and Parquet formats")
        lines.append("")
        lines.append("## Quality Metrics")
        lines.append("")
        lines.append("- **Lexical Diversity:** {0:.3f}".format(diversity['lexical_diversity']))
        lines.append("- **Category Balance (Entropy):** {0:.3f}".format(diversity['category_balance']))
        lines.append("- **Schema Validation Rate:** {0:.1%}".format(report['quality_metrics']['schema_validation_rate']))
        lines.append("")
        lines.append("## Limitations")
        lines.append("")
        lines.append("- **Synthetic Data**: All incidents are generated by LLMs and may not reflect real-world complexity")
        lines.append("- **Model Bias**: Quality depends on the LLM used for generation")
        lines.append("- **Topology Dependency**: Incidents are only as realistic as the input topology")
        lines.append("- **No Real Logs**: Incidents do not contain actual log lines, metrics, or traces")
        lines.append("- **Language Coverage**: Primarily English and Portuguese (Brazil)")
        lines.append("")
        lines.append("## Citation")
        lines.append("")
        lines.append("If you use this dataset, please cite:")
        lines.append("")
        lines.append("```bibtex")
        lines.append("@misc{incidentforge,")
        lines.append("  title={IncidentForge: Synthetic Incident Post-Mortem Generator},")
        lines.append("  author={IncidentForge Contributors},")
        lines.append("  year={2024},")
        lines.append("  url={https://github.com/incidentforge/incidentforge}")
        lines.append("}")
        lines.append("```")
        lines.append("")
        lines.append("## License")
        lines.append("")
        lines.append("This dataset is released under the {0} License. ".format(self.license) +
            "The synthetic incidents are generated using LLMs whose outputs may be subject to " +
            "the respective model's terms of use. Please review the model's license before " +
            "using this dataset commercially.")
        lines.append("")
        lines.append("## Contact")
        lines.append("")
        lines.append("For questions or contributions, visit [IncidentForge GitHub](https://github.com/incidentforge/incidentforge).")

        return "\n".join(lines)

    def save(self, output_path: Path) -> Path:
        """Save dataset card to file."""
        content = self.generate_card()
        output_path.write_text(content, encoding="utf-8")
        return output_path


async def generate_report(
    incidents: list[Incident],
    output_dir: Path,
    format: str = "both",
) -> dict[str, Path]:
    """
    Generate quality report and dataset card.

    Args:
        incidents: List of incidents.
        output_dir: Output directory.
        format: "markdown", "json", or "both".

    Returns:
        Dictionary of output paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    reporter = QualityReporter.from_incidents(incidents)
    card_generator = DatasetCardGenerator(incidents)

    paths = {}

    if format in ("markdown", "both"):
        md_path = output_dir / "quality_report.md"
        md_path.write_text(reporter.to_markdown(), encoding="utf-8")
        paths["markdown"] = md_path

    if format in ("json", "both"):
        json_path = output_dir / "quality_report.json"
        json_path.write_text(reporter.to_json(), encoding="utf-8")
        paths["json"] = json_path

    card_path = output_dir / "DATASET_CARD.md"
    card_generator.save(card_path)
    paths["dataset_card"] = card_path

    return paths


if __name__ == "__main__":
    from .models import (
        Incident, TimelineEvent, SLAImpact, ActionItem, IncidentMetadata,
        Severity, FailureCategory, Priority, Language, Style, ArchitectureProfile
    )

    incidents = [
        Incident(
            id="INC-2024-0001",
            service="api-gateway",
            severity=Severity.SEV_2,
            outage_duration_minutes=30,
            failure_category=FailureCategory.CONNECTION_LEAK,
            sla_impact=SLAImpact(
                availability_before=0.9999,
                availability_after=0.9950,
                p99_latency_ms=5000,
            ),
            root_cause_analysis="A connection leak in the nginx upstream module caused pool exhaustion. The HikariCP pool was not returning connections properly after requests to the auth-service.",
            timeline=[
                TimelineEvent(timestamp="2024-01-15T10:00:00Z", event="Connection pool usage starts increasing", source="nginx", severity=Severity.SEV_4),
                TimelineEvent(timestamp="2024-01-15T10:05:00Z", event="First 503 errors observed", source="api-gateway", severity=Severity.SEV_3),
                TimelineEvent(timestamp="2024-01-15T10:15:00Z", event="Pool exhaustion, all requests failing", source="api-gateway", severity=Severity.SEV_2),
                TimelineEvent(timestamp="2024-01-15T10:25:00Z", event="Restart of api-gateway pods", source="kubernetes", severity=Severity.SEV_2),
                TimelineEvent(timestamp="2024-01-15T10:30:00Z", event="Service recovered", source="api-gateway", severity=Severity.SEV_4),
            ],
            action_items=[
                ActionItem(action="Fix connection leak in nginx upstream configuration", owner="platform-team", priority=Priority.P0),
                ActionItem(action="Add connection pool monitoring and alerts", owner="platform-team", priority=Priority.P1),
            ],
            metadata=IncidentMetadata(
                model="gpt-4o-mini",
                prompt_version="1.0",
                seed=42,
                generated_at="2024-01-15T11:00:00Z",
                schema_version="1.0",
                synthetic=True,
            ),
        ),
        Incident(
            id="INC-2024-0002",
            service="auth-service",
            severity=Severity.SEV_1,
            outage_duration_minutes=45,
            failure_category=FailureCategory.DEADLOCK,
            sla_impact=SLAImpact(
                availability_before=0.9995,
                availability_after=0.9900,
                p99_latency_ms=10000,
            ),
            root_cause_analysis="A database deadlock occurred in PostgreSQL when multiple transactions tried to update the same rows in different order. The Spring Boot application using HikariCP experienced transaction rollbacks.",
            timeline=[
                TimelineEvent(timestamp="2024-01-15T14:00:00Z", event="Deadlock detected in PostgreSQL logs", source="postgresql", severity=Severity.SEV_3),
                TimelineEvent(timestamp="2024-01-15T14:10:00Z", event="Auth service latency spikes", source="auth-service", severity=Severity.SEV_2),
                TimelineEvent(timestamp="2024-01-15T14:20:00Z", event="Cascading failures to api-gateway", source="api-gateway", severity=Severity.SEV_1),
                TimelineEvent(timestamp="2024-01-15T14:35:00Z", event="Manual intervention to kill blocking queries", source="postgresql", severity=Severity.SEV_2),
                TimelineEvent(timestamp="2024-01-15T14:45:00Z", event="Service recovered", source="auth-service", severity=Severity.SEV_4),
            ],
            action_items=[
                ActionItem(action="Add deadlock detection and retry logic", owner="identity-team", priority=Priority.P0),
                ActionItem(action="Review transaction ordering in user service", owner="identity-team", priority=Priority.P1),
                ActionItem(action="Add database lock monitoring", owner="data-team", priority=Priority.P2),
            ],
            metadata=IncidentMetadata(
                model="gpt-4o-mini",
                prompt_version="1.0",
                seed=43,
                generated_at="2024-01-15T15:00:00Z",
                schema_version="1.0",
                synthetic=True,
            ),
        ),
    ]

    import asyncio

    async def test():
        output_dir = Path("test_report")
        paths = await generate_report(incidents, output_dir, format="both")
        print("Reports generated: {0}".format(paths))

        md_content = (output_dir / "quality_report.md").read_text()
        print(md_content[:1000])

    asyncio.run(test())