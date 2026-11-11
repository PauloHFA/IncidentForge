"""Tests for CLI commands."""

import pytest
import tempfile
import json
from pathlib import Path
from typer.testing import CliRunner

from incidentforge.cli import app


class TestCLI:
    """Tests for CLI commands."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_version(self):
        """Test version command."""
        result = self.runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "IncidentForge v" in result.output

    def test_help(self):
        """Test help command."""
        result = self.runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Synthetic post-mortem" in result.output
        assert "init" in result.output
        assert "plan" in result.output
        assert "generate" in result.output
        assert "validate" in result.output
        assert "dedup" in result.output
        assert "export" in result.output
        assert "report" in result.output
        assert "schema" in result.output

    def test_init_command(self):
        """Test init command creates sample files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "configs"
            result = self.runner.invoke(app, ["init", str(output_dir), "--force"])
            assert result.exit_code == 0
            assert "Created topology sample" in result.output
            assert "Created failures sample" in result.output

            # Check files exist
            assert (output_dir / "topology.yaml").exists()
            assert (output_dir / "failures.yaml").exists()

    def test_init_command_no_force(self):
        """Test init command without force on existing files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "configs"
            output_dir.mkdir(parents=True)
            (output_dir / "topology.yaml").write_text("existing")
            (output_dir / "failures.yaml").write_text("existing")

            result = self.runner.invoke(app, ["init", str(output_dir)])
            assert result.exit_code == 0
            assert "already exists" in result.output

    def test_plan_command(self):
        """Test plan command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create sample configs
            configs_dir = Path(tmpdir) / "configs"
            configs_dir.mkdir(parents=True)

            # Copy sample files
            import shutil
            sample_topology = Path("configs/topology_sample.yaml")
            sample_failures = Path("configs/failures_default.yaml")
            if sample_topology.exists():
                shutil.copy2(sample_topology, configs_dir / "topology.yaml")
            if sample_failures.exists():
                shutil.copy2(sample_failures, configs_dir / "failures.yaml")

            result = self.runner.invoke(app, [
                "plan",
                "--topology", str(configs_dir / "topology.yaml"),
                "--failures", str(configs_dir / "failures.yaml"),
                "--per-service", "1",
                "--seed", "42",
            ])
            assert result.exit_code == 0
            assert "Generation Plan" in result.output
            assert "Total Tasks:" in result.output

    def test_plan_command_dry_run(self):
        """Test plan command with dry run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            configs_dir = Path(tmpdir) / "configs"
            configs_dir.mkdir(parents=True)

            import shutil
            sample_topology = Path("configs/topology_sample.yaml")
            sample_failures = Path("configs/failures_default.yaml")
            if sample_topology.exists():
                shutil.copy2(sample_topology, configs_dir / "topology.yaml")
            if sample_failures.exists():
                shutil.copy2(sample_failures, configs_dir / "failures.yaml")

            result = self.runner.invoke(app, [
                "plan",
                "--topology", str(configs_dir / "topology.yaml"),
                "--failures", str(configs_dir / "failures.yaml"),
                "--dry-run",
            ])
            assert result.exit_code == 0
            assert "Dry run complete" in result.output

    def test_plan_command_output_json(self):
        """Test plan command with JSON output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            configs_dir = Path(tmpdir) / "configs"
            configs_dir.mkdir(parents=True)

            import shutil
            sample_topology = Path("configs/topology_sample.yaml")
            sample_failures = Path("configs/failures_default.yaml")
            if sample_topology.exists():
                shutil.copy2(sample_topology, configs_dir / "topology.yaml")
            if sample_failures.exists():
                shutil.copy2(sample_failures, configs_dir / "failures.yaml")

            output_file = Path(tmpdir) / "plan.json"
            result = self.runner.invoke(app, [
                "plan",
                "--topology", str(configs_dir / "topology.yaml"),
                "--failures", str(configs_dir / "failures.yaml"),
                "--output", str(output_file),
            ])
            assert result.exit_code == 0
            assert output_file.exists()

            # Verify JSON content
            with output_file.open() as f:
                plan = json.load(f)
            assert "topology" in plan
            assert "failure_catalog" in plan
            assert "total_tasks" in plan
            assert "tasks" in plan

    def test_schema_command(self):
        """Test schema command."""
        result = self.runner.invoke(app, ["schema"])
        assert result.exit_code == 0
        # Should output JSON schema
        assert '"type": "object"' in result.output
        assert "Incident" in result.output or "id" in result.output

    def test_schema_command_output_file(self):
        """Test schema command with output file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "schema.json"
            result = self.runner.invoke(app, ["schema", "--output", str(output_file)])
            assert result.exit_code == 0
            assert output_file.exists()

            with output_file.open() as f:
                schema = json.load(f)
            assert schema["type"] == "object"

    def test_generate_command_missing_config(self):
            """Test generate command with missing config files."""
            runner = CliRunner()
            # Use non-existent config files
            result = runner.invoke(app, ["generate", "--topology", "nonexistent.yaml", "--failures", "nonexistent.yaml", "--concurrency", "0"])
            assert result.exit_code != 0
            assert "Error loading configuration" in result.output

    def test_validate_command_no_files(self):
        """Test validate command with no incident files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.runner.invoke(app, ["validate", tmpdir])
            assert result.exit_code != 0
            assert "No JSONL files found" in result.output

    def test_dedup_command_no_files(self):
        """Test dedup command with no incident files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.runner.invoke(app, ["dedup", tmpdir])
            assert result.exit_code != 0
            assert "No JSONL files found" in result.output

    def test_export_command_no_files(self):
        """Test export command with no incident files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.runner.invoke(app, ["export", tmpdir])
            assert result.exit_code != 0
            assert "No JSONL files found" in result.output

    def test_report_command_no_files(self):
        """Test report command with no incident files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.runner.invoke(app, ["report", tmpdir])
            assert result.exit_code != 0
            assert "No JSONL files found" in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])