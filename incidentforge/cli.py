"""IncidentForge CLI - Synthetic post-mortem and chaos scenario generator."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .models import FailureCatalog, Incident, Topology
from .topology import TopologyLoader
from .failures import FailureCatalogLoader
from .planner import TaskPlanner, PlannerConfig
from .generator import IncidentGenerator, GeneratorConfig
from .validators import (
    ValidationResult,
    ValidationContext,
    SchemaValidator,
    SemanticValidator,
    SecurityValidator,
    MultiLayerValidator,
    create_validator,
    validate_incident,
)
from .dedup import DiversityController, DedupConfig
from .exporter import ExporterManager, export_incidents
from .report import QualityReporter, generate_report

app = typer.Typer(
    name="incidentforge",
    help="Synthetic post-mortem and chaos scenario generator for observability testing and incident response training.",
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        from . import __version__
        console.print(f"IncidentForge v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", "-v", callback=version_callback, is_eager=True, help="Show version and exit"),
    ] = False,
) -> None:
    """IncidentForge - Generate synthetic incident reports from system topology."""
    pass


@app.command()
def init(
    output_dir: Annotated[
        Path,
        typer.Argument(help="Directory to create sample configuration files"),
    ] = Path("configs"),
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing files"),
    ] = False,
) -> None:
    """Create sample topology and failure catalog configuration files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    topology_path = output_dir / "topology.yaml"
    failures_path = output_dir / "failures.yaml"

    if topology_path.exists() and not force:
        console.print(f"[yellow]Topology file already exists: {topology_path}[/yellow]")
    else:
        # Copy from package sample
        import shutil
        sample_topology = Path(__file__).parent.parent / "configs" / "topology_sample.yaml"
        if sample_topology.exists():
            shutil.copy2(sample_topology, topology_path)
            console.print(f"[green]Created topology sample: {topology_path}[/green]")
        else:
            console.print("[red]Sample topology not found in package[/red]")

    if failures_path.exists() and not force:
        console.print(f"[yellow]Failures file already exists: {failures_path}[/yellow]")
    else:
        sample_failures = Path(__file__).parent.parent / "configs" / "failures_default.yaml"
        if sample_failures.exists():
            shutil.copy2(sample_failures, failures_path)
            console.print(f"[green]Created failures sample: {failures_path}[/green]")
        else:
            console.print("[red]Sample failures not found in package[/red]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  1. Edit {topology_path} to match your system topology")
    console.print(f"  2. Edit {failures_path} to customize failure categories")
    console.print("  3. Run 'incidentforge plan' to preview generation tasks")
    console.print("  4. Run 'incidentforge generate' to create incidents")


@app.command()
def plan(
    topology: Annotated[
        Path,
        typer.Option("--topology", "-t", help="Path to topology YAML file"),
    ] = Path("configs/topology.yaml"),
    failures: Annotated[
        Path,
        typer.Option("--failures", "-f", help="Path to failure catalog YAML file"),
    ] = Path("configs/failures.yaml"),
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file for plan (JSON)"),
    ] = None,
    per_service: Annotated[
        int,
        typer.Option("--per-service", "-n", help="Incidents per service"),
    ] = 3,
    per_category: Annotated[
        int,
        typer.Option("--per-category", "-c", help="Incidents per failure category"),
    ] = 2,
    severities: Annotated[
        str,
        typer.Option("--severities", "-s", help="Comma-separated severities (SEV-1,SEV-2,SEV-3,SEV-4)"),
    ] = "SEV-1,SEV-2,SEV-3",
    seed: Annotated[
        int,
        typer.Option("--seed", help="Random seed for reproducibility"),
    ] = 42,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-d", help="Show plan without executing"),
    ] = True,
) -> None:
    """Preview generation plan without executing."""
    console.print("[bold]Loading configuration...[/bold]")

    try:
        topology_obj = TopologyLoader().load(topology)
        failures_obj = FailureCatalogLoader().load_from_file(failures)
    except Exception as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        raise typer.Exit(1)

    config = PlannerConfig(
        count=per_service * 10,  # approximate
        seed=seed,
    )

    planner = TaskPlanner(config)
    tasks = planner.build_plan(topology_obj, failures_obj).tasks

    console.print(f"\n[bold]Generation Plan[/bold]")
    console.print(f"  Topology: {topology_obj.version} ({len(topology_obj.services)} services)")
    console.print(f"  Failure Catalog: {failures_obj.version} ({len(failures_obj.failures)} categories)")
    console.print(f"  Total Tasks: {len(tasks)}")
    console.print(f"  Seed: {seed}")

    # Show distribution
    table = Table(title="Task Distribution")
    table.add_column("Service", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Severity", style="yellow")
    table.add_column("Count", justify="right", style="green")

    from collections import Counter
    dist = Counter((t.service_name, t.failure_category.value, t.severity.value) for t in tasks)
    for (svc, cat, sev), count in sorted(dist.items()):
        table.add_row(svc, cat, sev, str(count))

    console.print(table)

    if output:
        plan_data = {
                "topology": topology_obj.version,
                "failure_catalog": failures_obj.version,
            "total_tasks": len(tasks),
            "seed": seed,
                "config": dataclasses.asdict(config),
            "tasks": [t.model_dump() for t in tasks],
        }
        output.write_text(json.dumps(plan_data, indent=2, default=str))
        console.print(f"\n[green]Plan saved to: {output}[/green]")

    if dry_run:
        console.print("\n[yellow]Dry run complete. Use 'incidentforge generate' to execute.[/yellow]")


@app.command()
def generate(
    topology: Annotated[
        Path,
        typer.Option("--topology", "-t", help="Path to topology YAML file"),
    ] = Path("configs/topology.yaml"),
    failures: Annotated[
        Path,
        typer.Option("--failures", "-f", help="Path to failure catalog YAML file"),
    ] = Path("configs/failures.yaml"),
    output_dir: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output directory for generated incidents"),
    ] = Path("output"),
    per_service: Annotated[
        int,
        typer.Option("--per-service", "-n", help="Incidents per service"),
    ] = 3,
    per_category: Annotated[
        int,
        typer.Option("--per-category", "-c", help="Incidents per failure category"),
    ] = 2,
    severities: Annotated[
        str,
        typer.Option("--severities", "-s", help="Comma-separated severities"),
    ] = "SEV-1,SEV-2,SEV-3",
    seed: Annotated[
        int,
        typer.Option("--seed", help="Random seed for reproducibility"),
    ] = 42,
    concurrency: Annotated[
        int,
        typer.Option("--concurrency", help="Max concurrent LLM requests"),
    ] = 4,
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="LLM model name"),
    ] = "gpt-4o-mini",
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="LLM API base URL (for vLLM, Ollama, NIM, etc.)"),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="LLM API key (or set INCIDENTFORGE_API_KEY env var)"),
    ] = None,
    temperature: Annotated[
        float,
        typer.Option("--temperature", help="LLM temperature"),
    ] = 0.3,
    max_tokens: Annotated[
        int,
        typer.Option("--max-tokens", help="Max tokens per request"),
    ] = 4000,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Request timeout in seconds"),
    ] = 120.0,
    max_retries: Annotated[
        int,
        typer.Option("--max-retries", help="Max retry attempts"),
    ] = 3,
    validate: Annotated[
        bool,
        typer.Option("--validate/--no-validate", help="Run validation pipeline"),
    ] = True,
    dedup: Annotated[
        bool,
        typer.Option("--dedup/--no-dedup", help="Run deduplication"),
    ] = True,
    export_formats: Annotated[
        str,
        typer.Option("--formats", help="Comma-separated export formats (jsonl,markdown,parquet)"),
    ] = "jsonl,markdown",
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume from previous state"),
    ] = False,
) -> None:
    """Generate synthetic incident reports."""
    console.print("[bold]IncidentForge - Generating Incidents[/bold]")

    # Load configuration
    try:
        topology_obj = TopologyLoader().load(topology)
        failures_obj = FailureCatalogLoader().load_from_file(failures)
    except Exception as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        raise typer.Exit(1)

    # Plan configuration
    plan_config = PlannerConfig(
            count=per_service * len(topology_obj.services),  # approximate
            seed=seed,
        )

    # LLM configuration
    from .client import LLMConfig
    llm_config = LLMConfig(
        model=model,
        base_url=base_url or "https://api.openai.com/v1",
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
    )

    # Generator configuration
    gen_config = GeneratorConfig(
        concurrency=concurrency,
    )

    # Deduplication configuration
    dedup_config = DedupConfig(
        similarity_threshold=0.92,
        minhash_threshold=0.85,
    )

    # Create generator
    generator = IncidentGenerator(
        topology=topology_obj,
        config=gen_config,
        llm_config=llm_config,
    )

    # Run generation
    try:
        incidents = asyncio.run(generator.generate())
    except KeyboardInterrupt:
        console.print("\n[yellow]Generation interrupted by user[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"\n[red]Generation failed: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[green]Successfully generated {len(incidents)} incidents![/green]")
    console.print(f"Output directory: {output_dir}")


@app.command()
def validate(
    input_dir: Annotated[
        Path,
        typer.Argument(help="Directory containing incident JSONL files"),
    ] = Path("output"),
    topology: Annotated[
        Path,
        typer.Option("--topology", "-t", help="Path to topology YAML file"),
    ] = Path("configs/topology.yaml"),
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file for validation report"),
    ] = None,
    schema_only: Annotated[
        bool,
        typer.Option("--schema-only", help="Only validate JSON schema"),
    ] = False,
    semantic: Annotated[
        bool,
        typer.Option("--semantic/--no-semantic", help="Run semantic validation"),
    ] = True,
    security: Annotated[
        bool,
        typer.Option("--security/--no-security", help="Run security/PII validation"),
    ] = True,
) -> None:
    """Validate generated incidents."""
    console.print("[bold]Validating Incidents[/bold]")

    # Find all JSONL files
    jsonl_files = list(input_dir.rglob("*.jsonl"))
    if not jsonl_files:
        console.print(f"[red]No JSONL files found in {input_dir}[/red]")
        raise typer.Exit(1)

    console.print(f"Found {len(jsonl_files)} JSONL file(s)")

    # Load incidents
    incidents = []
    for file_path in jsonl_files:
        with file_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        incidents.append(Incident.model_validate(data))
                    except Exception as e:
                        console.print(f"[yellow]Warning: Failed to parse line in {file_path}: {e}[/yellow]")

    console.print(f"Loaded {len(incidents)} incidents")

    # Run validation
    console.print(f"Running validation (schema={True}, semantic={semantic}, security={security})")

    all_results = []
    for incident in incidents:
        # Get topology for validation
        topology_obj = TopologyLoader().load(topology)
        results = validate_incident(incident, topology_obj)
        all_results.extend(results)

    # Summary
    passed = sum(1 for r in all_results if r.valid)
    failed = len(all_results) - passed

    console.print(f"\n[bold]Validation Results[/bold]")
    console.print(f"  Total checks: {len(all_results)}")
    console.print(f"  Passed: {passed}")
    console.print(f"  Failed: {failed}")

    if output:
        report = {
            "total": len(all_results),
            "passed": passed,
            "failed": failed,
            "results": [r.model_dump() for r in all_results],
        }
        output.write_text(json.dumps(report, indent=2, default=str))
        console.print(f"\n[green]Validation report saved to: {output}[/green]")

    if failed > 0:
        raise typer.Exit(1)


@app.command()
def dedup(
    input_dir: Annotated[
        Path,
        typer.Argument(help="Directory containing incident JSONL files"),
    ] = Path("output"),
    output_dir: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output directory for deduplicated incidents"),
    ] = Path("output_dedup"),
    threshold: Annotated[
        float,
        typer.Option("--threshold", "-t", help="Similarity threshold (0-1)"),
    ] = 0.92,
    use_embeddings: Annotated[
        bool,
        typer.Option("--embeddings/--no-embeddings", help="Use embedding-based deduplication"),
    ] = True,
    use_minhash: Annotated[
        bool,
        typer.Option("--minhash/--no-minhash", help="Use MinHash-based deduplication"),
    ] = True,
) -> None:
    """Deduplicate incidents using semantic similarity."""
    console.print("[bold]Deduplicating Incidents[/bold]")

    # Find all JSONL files
    jsonl_files = list(input_dir.rglob("*.jsonl"))
    if not jsonl_files:
        console.print(f"[red]No JSONL files found in {input_dir}[/red]")
        raise typer.Exit(1)

    # Load incidents
    incidents = []
    for file_path in jsonl_files:
        with file_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        incidents.append(Incident.model_validate(data))
                    except Exception as e:
                        console.print(f"[yellow]Warning: Failed to parse line in {file_path}: {e}[/yellow]")

    console.print(f"Loaded {len(incidents)} incidents")

    # Run deduplication
    config = DedupConfig(
        similarity_threshold=threshold,
        use_embeddings=use_embeddings,
        use_minhash=use_minhash,
    )
    controller = DiversityController(config)

    unique_incidents = []
    duplicates = []

    for incident in incidents:
        is_dup, dup_id, sim = controller.check_duplicate(incident)
        if is_dup:
            duplicates.append((incident, dup_id, sim))
        else:
            controller.add(incident)
            unique_incidents.append(incident)

    console.print(f"\n[bold]Deduplication Results[/bold]")
    console.print(f"  Original: {len(incidents)}")
    console.print(f"  Unique: {len(unique_incidents)}")
    console.print(f"  Duplicates removed: {len(duplicates)}")

    # Export unique incidents
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = asyncio.run(export_incidents(
        unique_incidents,
        output_dir,
        export_markdown=False,
        export_jsonl=True,
        export_parquet=False,
    ))
    console.print(f"\n[green]Deduplicated incidents saved to: {output_dir}[/green]")
    for fmt, path in paths.items():
        console.print(f"  {fmt}: {path}")


@app.command()
def export(
    input_dir: Annotated[
        Path,
        typer.Argument(help="Directory containing incident JSONL files"),
    ] = Path("output"),
    output_dir: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output directory"),
    ] = Path("export"),
    formats: Annotated[
        str,
        typer.Option("--formats", "-f", help="Comma-separated formats (jsonl,markdown,parquet)"),
    ] = "jsonl,markdown,parquet",
) -> None:
    """Export incidents to multiple formats."""
    console.print("[bold]Exporting Incidents[/bold]")

    # Find all JSONL files
    jsonl_files = list(input_dir.rglob("*.jsonl"))
    if not jsonl_files:
        console.print(f"[red]No JSONL files found in {input_dir}[/red]")
        raise typer.Exit(1)

    # Load incidents
    incidents = []
    for file_path in jsonl_files:
        with file_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        incidents.append(Incident.model_validate(data))
                    except Exception as e:
                        console.print(f"[yellow]Warning: Failed to parse line in {file_path}: {e}[/yellow]")

    console.print(f"Loaded {len(incidents)} incidents")

    # Export
    fmt_list = [f.strip() for f in formats.split(",")]
    paths = asyncio.run(export_incidents(
        incidents,
        output_dir,
        export_markdown="markdown" in fmt_list,
        export_jsonl="jsonl" in fmt_list,
        export_parquet="parquet" in fmt_list,
    ))

    console.print(f"\n[green]Export complete![/green]")
    for fmt, path in paths.items():
        console.print(f"  {fmt}: {path}")


@app.command()
def report(
    input_dir: Annotated[
        Path,
        typer.Argument(help="Directory containing incident JSONL files"),
    ] = Path("output"),
    output_dir: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output directory for reports"),
    ] = Path("reports"),
    format: Annotated[
        str,
        typer.Option("--format", "-f", help="Report format (markdown, json, both)"),
    ] = "both",
) -> None:
    """Generate quality report and dataset card."""
    console.print("[bold]Generating Quality Report[/bold]")

    # Find all JSONL files
    jsonl_files = list(input_dir.rglob("*.jsonl"))
    if not jsonl_files:
        console.print(f"[red]No JSONL files found in {input_dir}[/red]")
        raise typer.Exit(1)

    # Load incidents
    incidents = []
    for file_path in jsonl_files:
        with file_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        incidents.append(Incident.model_validate(data))
                    except Exception as e:
                        console.print(f"[yellow]Warning: Failed to parse line in {file_path}: {e}[/yellow]")

    console.print(f"Loaded {len(incidents)} incidents")

    # Generate report
    paths = asyncio.run(generate_report(incidents, output_dir, format=format))

    console.print(f"\n[green]Report generated![/green]")
    for fmt, path in paths.items():
        console.print(f"  {fmt}: {path}")


@app.command()
def schema(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file for JSON schema"),
    ] = None,
) -> None:
    """Export JSON schema for Incident model."""
    schema_json = Incident.model_json_schema()

    if output:
        output.write_text(json.dumps(schema_json, indent=2))
        console.print(f"[green]Schema saved to: {output}[/green]")
    else:
        console.print(json.dumps(schema_json, indent=2))


if __name__ == "__main__":
    app()