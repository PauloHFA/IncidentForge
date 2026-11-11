"""Tests for exporters."""

import pytest
import tempfile
import json
from pathlib import Path

from incidentforge.exporter import (
    MarkdownExporter,
    JSONLExporter,
    ParquetExporter,
    ExporterManager,
    export_incidents,
)
from incidentforge.models import (
    Incident, TimelineEvent, SLAImpact, ActionItem, IncidentMetadata,
    Severity, FailureCategory, Priority
)


def create_test_incidents() -> list[Incident]:
    """Create test incidents."""
    return [
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
            root_cause_analysis="A connection leak in the nginx upstream module caused pool exhaustion. The investigation revealed that the connection pool was not properly releasing connections back to the pool after requests completed, leading to gradual exhaustion of available connections. This was compounded by a lack of proper timeout configuration and monitoring alerts that would have detected the issue earlier.",
            timeline=[
                TimelineEvent(timestamp="2024-01-15T10:00:00Z", event="Event 1", source="nginx"),
                TimelineEvent(timestamp="2024-01-15T10:05:00Z", event="Event 2", source="api-gateway"),
                TimelineEvent(timestamp="2024-01-15T10:15:00Z", event="Event 3", source="api-gateway"),
                TimelineEvent(timestamp="2024-01-15T10:25:00Z", event="Event 4", source="kubernetes"),
                TimelineEvent(timestamp="2024-01-15T10:30:00Z", event="Event 5", source="api-gateway"),
            ],
            action_items=[
                ActionItem(action="Fix connection leak", owner="platform-team", priority=Priority.P0),
                ActionItem(action="Add monitoring", owner="platform-team", priority=Priority.P1),
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
                availability_before=0.9999,
                availability_after=0.9900,
                p99_latency_ms=10000,
            ),
            root_cause_analysis="A deadlock in PostgreSQL caused transaction failures. The investigation revealed that concurrent transactions were acquiring locks in different orders, creating a circular wait condition. The application was not using consistent lock ordering, and the database isolation level was not configured to prevent this scenario. Proper indexing and query optimization could have reduced lock contention.",
            timeline=[
                TimelineEvent(timestamp="2024-01-15T14:00:00Z", event="Event 1", source="postgresql"),
                TimelineEvent(timestamp="2024-01-15T14:10:00Z", event="Event 2", source="auth-service"),
                TimelineEvent(timestamp="2024-01-15T14:20:00Z", event="Event 3", source="auth-service"),
                TimelineEvent(timestamp="2024-01-15T14:35:00Z", event="Event 4", source="kubernetes"),
                TimelineEvent(timestamp="2024-01-15T14:45:00Z", event="Event 5", source="auth-service"),
            ],
            action_items=[
                ActionItem(action="Optimize queries", owner="db-team", priority=Priority.P0),
                ActionItem(action="Add deadlock monitoring", owner="db-team", priority=Priority.P1),
                ActionItem(action="Review transaction isolation", owner="db-team", priority=Priority.P2),
            ],
            metadata=IncidentMetadata(
                model="gpt-4o-mini",
                prompt_version="1.0",
                seed=42,
                generated_at="2024-01-15T15:00:00Z",
                schema_version="1.0",
                synthetic=True,
            ),
        ),
    ]


class TestMarkdownExporter:
    """Tests for MarkdownExporter."""

    @pytest.mark.asyncio
    async def test_export_single(self):
        """Test exporting a single incident as Markdown."""
        incidents = create_test_incidents()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            exporter = MarkdownExporter(output_dir)

            path = await exporter.export(incidents[0])

            assert path.exists()
            assert path.suffix == ".md"
            assert "INC-2024-0001" in path.name

            content = path.read_text()
            assert "# INC-2024-0001" in content
            assert "api-gateway" in content
            assert "SEV-2" in content
            assert "Connection Leak" in content
            assert "Root Cause Analysis" in content
            assert "Timeline" in content
            assert "Action Items" in content

    @pytest.mark.asyncio
    async def test_export_batch(self):
        """Test exporting multiple incidents as Markdown."""
        incidents = create_test_incidents()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            exporter = MarkdownExporter(output_dir)

            paths = await exporter.export_batch(incidents)

            assert len(paths) == 2
            for path in paths:
                assert path.exists()
                assert path.suffix == ".md"


class TestJSONLExporter:
    """Tests for JSONLExporter."""

    @pytest.mark.asyncio
    async def test_export_single(self):
        """Test exporting a single incident as JSONL."""
        incidents = create_test_incidents()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "incidents.jsonl"

            async with JSONLExporter(output_path) as exporter:
                await exporter.export(incidents[0])

            # Verify content
            content = output_path.read_text()
            lines = content.strip().split("\n")
            assert len(lines) == 1

            data = json.loads(lines[0])
            assert data["id"] == "INC-2024-0001"
            assert data["service"] == "api-gateway"
            assert data["severity"] == "SEV-2"

    @pytest.mark.asyncio
    async def test_export_batch(self):
        """Test exporting multiple incidents as JSONL."""
        incidents = create_test_incidents()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "incidents.jsonl"

            async with JSONLExporter(output_path) as exporter:
                await exporter.export_batch(incidents)

            # Verify content
            content = output_path.read_text()
            lines = content.strip().split("\n")
            assert len(lines) == 2

            for i, line in enumerate(lines):
                data = json.loads(line)
                assert data["id"] == f"INC-2024-{i+1:04d}"


class TestParquetExporter:
    """Tests for ParquetExporter."""

    def test_export(self):
        """Test exporting incidents as Parquet."""
        incidents = create_test_incidents()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "incidents.parquet"
            exporter = ParquetExporter(output_path)

            exporter.add_batch(incidents)
            result_path = exporter.export()

            assert result_path == output_path
            assert output_path.exists()

            # Verify content with pandas
            import pandas as pd
            df = pd.read_parquet(output_path)
            assert len(df) == 2
            assert "id" in df.columns
            assert "service" in df.columns
            assert "severity" in df.columns
            assert "failure_category" in df.columns
            assert "timeline" in df.columns
            assert "action_items" in df.columns

            # Check data
            assert df.iloc[0]["id"] == "INC-2024-0001"
            assert df.iloc[0]["service"] == "api-gateway"
            assert df.iloc[1]["id"] == "INC-2024-0002"
            assert df.iloc[1]["service"] == "auth-service"


class TestExporterManager:
    """Tests for ExporterManager."""

    @pytest.mark.asyncio
    async def test_export_all_formats(self):
        """Test exporting to all formats."""
        incidents = create_test_incidents()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            async with ExporterManager(
                output_dir=output_dir,
                export_markdown=True,
                export_jsonl=True,
                export_parquet=True,
            ) as manager:
                await manager.export_batch(incidents)
                paths = await manager.finalize()

            assert "markdown_dir" in paths
            assert "jsonl" in paths
            assert "parquet" in paths

            # Verify markdown
            md_dir = paths["markdown_dir"]
            md_files = list(md_dir.glob("*.md"))
            assert len(md_files) == 2

            # Verify JSONL
            jsonl_path = paths["jsonl"]
            assert jsonl_path.exists()
            content = jsonl_path.read_text()
            lines = content.strip().split("\n")
            assert len(lines) == 2

            # Verify Parquet
            parquet_path = paths["parquet"]
            assert parquet_path.exists()
            import pandas as pd
            df = pd.read_parquet(parquet_path)
            assert len(df) == 2


class TestExportIncidentsConvenience:
    """Tests for export_incidents convenience function."""

    @pytest.mark.asyncio
    async def test_export_all_formats(self):
        """Test convenience function exports all formats."""
        incidents = create_test_incidents()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            paths = await export_incidents(
                incidents,
                output_dir,
                export_markdown=True,
                export_jsonl=True,
                export_parquet=True,
            )

            assert "markdown_dir" in paths
            assert "jsonl" in paths
            assert "parquet" in paths

    @pytest.mark.asyncio
    async def test_export_selected_formats(self):
        """Test convenience function with selected formats."""
        incidents = create_test_incidents()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            paths = await export_incidents(
                incidents,
                output_dir,
                export_markdown=True,
                export_jsonl=False,
                export_parquet=False,
            )

            assert "markdown_dir" in paths
            assert "jsonl" not in paths
            assert "parquet" not in paths


if __name__ == "__main__":
    pytest.main([__file__, "-v"])