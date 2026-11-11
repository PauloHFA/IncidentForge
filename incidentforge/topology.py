"""Topology loader and validator for IncidentForge."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import Topology, Service, ServiceDependency


class TopologyLoader:
    """Loads and validates topology from YAML files."""

    def __init__(self, strict: bool = True):
        """
        Initialize topology loader.

        Args:
            strict: If True, raise on validation errors. If False, collect warnings.
        """
        self.strict = strict
        self.warnings: list[str] = []

    def load(self, path: str | Path) -> Topology:
        """
        Load topology from YAML file.

        Args:
            path: Path to topology YAML file.

        Returns:
            Validated Topology object.

        Raises:
            FileNotFoundError: If file doesn't exist.
            ValidationError: If topology is invalid (in strict mode).
            ValueError: If YAML is malformed.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Topology file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise ValueError(f"Invalid YAML in {path}: {e}") from e

        if data is None:
            raise ValueError(f"Empty topology file: {path}")

        return self.validate(data)

    def validate(self, data: dict[str, Any]) -> Topology:
        """
        Validate topology data.

        Args:
            data: Raw topology data from YAML.

        Returns:
            Validated Topology object.

        Raises:
            ValidationError: If topology is invalid (in strict mode).
        """
        self.warnings = []

        try:
            topology = Topology.model_validate(data)
        except ValidationError as e:
            if self.strict:
                raise
            # In non-strict mode, try to provide helpful error messages
            errors = self._format_validation_errors(e)
            raise ValueError(f"Topology validation failed:\n" + "\n".join(errors)) from e

        # Check for dependency cycles (warning only)
        if topology.has_cycles():
            cycle_warning = "Topology contains dependency cycles (this is realistic for distributed systems)"
            self.warnings.append(cycle_warning)
            warnings.warn(cycle_warning, UserWarning, stacklevel=2)

        # Check for services with no dependencies and no dependents (isolated)
        isolated = self._find_isolated_services(topology)
        if isolated:
            for svc in isolated:
                warn_msg = f"Service '{svc}' has no dependencies and no dependents (isolated)"
                self.warnings.append(warn_msg)
                warnings.warn(warn_msg, UserWarning, stacklevel=2)

        return topology

    def _format_validation_errors(self, error: ValidationError) -> list[str]:
        """Format validation errors into readable messages."""
        messages = []
        for err in error.errors():
            loc = " -> ".join(str(x) for x in err["loc"])
            msg = err["msg"]
            messages.append(f"  {loc}: {msg}")
        return messages

    def _find_isolated_services(self, topology: Topology) -> list[str]:
        """Find services with no dependencies and no dependents."""
        isolated = []
        for service in topology.services:
            has_deps = len(service.dependencies) > 0
            has_dependents = len(topology.get_dependents(service.name)) > 0
            if not has_deps and not has_dependents:
                isolated.append(service.name)
        return isolated

    def get_warnings(self) -> list[str]:
        """Get collected warnings."""
        return self.warnings.copy()


class TopologyValidator:
    """Additional semantic validation for topology."""

    @staticmethod
    def validate_slo_consistency(topology: Topology) -> list[str]:
        """
        Validate SLO consistency across services.

        Returns:
            List of warning messages.
        """
        warnings = []

        # Check if global SLO is stricter than any service SLO
        if topology.global_slo:
            for service in topology.services:
                if service.slo.availability_target < topology.global_slo.availability_target:
                    warnings.append(
                        f"Service '{service.name}' availability target "
                        f"({service.slo.availability_target}) is lower than global "
                        f"({topology.global_slo.availability_target})"
                    )
                if service.slo.latency_p99_ms > topology.global_slo.latency_p99_ms:
                    warnings.append(
                        f"Service '{service.name}' latency target "
                        f"({service.slo.latency_p99_ms}ms) is higher than global "
                        f"({topology.global_slo.latency_p99_ms}ms)"
                    )

        return warnings

    @staticmethod
    def validate_dependency_traffic(topology: Topology) -> list[str]:
        """
        Validate dependency traffic percentages.

        Returns:
            List of warning messages.
        """
        warnings = []

        for service in topology.services:
            total_traffic = sum(dep.traffic_percentage for dep in service.dependencies)
            if total_traffic > 100:
                warnings.append(
                    f"Service '{service.name}' dependencies total traffic "
                    f"({total_traffic}%) exceeds 100%"
                )
            elif total_traffic < 50 and service.dependencies:
                warnings.append(
                    f"Service '{service.name}' dependencies total traffic "
                    f"({total_traffic}%) is unusually low"
                )

        return warnings

    @staticmethod
    def validate_replica_counts(topology: Topology) -> list[str]:
        """
        Validate replica counts for high-availability services.

        Returns:
            List of warning messages.
        """
        warnings = []

        for service in topology.services:
            # Services with high availability targets should have multiple replicas
            if service.slo.availability_target >= 0.999 and service.replicas < 3:
                warnings.append(
                    f"Service '{service.name}' targets {service.slo.availability_target} "
                    f"availability but only has {service.replicas} replicas"
                )

            # Critical path services should have more replicas
            dependents = topology.get_dependents(service.name)
            critical_dependents = sum(1 for d in dependents
                                      for dep in d.dependencies
                                      if dep.target == service.name and dep.critical)
            if critical_dependents >= 3 and service.replicas < 3:
                warnings.append(
                    f"Service '{service.name}' is critical dependency for {critical_dependents} "
                    f"services but only has {service.replicas} replicas"
                )

        return warnings

    @classmethod
    def validate_all(cls, topology: Topology) -> list[str]:
        """Run all semantic validations."""
        warnings = []
        warnings.extend(cls.validate_slo_consistency(topology))
        warnings.extend(cls.validate_dependency_traffic(topology))
        warnings.extend(cls.validate_replica_counts(topology))
        return warnings


def load_topology(path: str | Path, strict: bool = True) -> Topology:
    """
    Convenience function to load and validate topology.

    Args:
        path: Path to topology YAML file.
        strict: If True, raise on validation errors.

    Returns:
        Validated Topology object.
    """
    loader = TopologyLoader(strict=strict)
    return loader.load(path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        topology_path = sys.argv[1]
    else:
        topology_path = "configs/topology_sample.yaml"

    try:
        topology = load_topology(topology_path)
        print(f"[OK] Topology loaded successfully: {len(topology.services)} services")

        # Run semantic validations
        validator = TopologyValidator()
        semantic_warnings = validator.validate_all(topology)
        for warn in semantic_warnings:
                    print(f"[WARN] {warn}")

        if semantic_warnings:
            print(f"\nTotal semantic warnings: {len(semantic_warnings)}")
        else:
            print("No semantic warnings.")

    except Exception as e:
        print(f"[ERROR] Failed to load topology: {e}")
        sys.exit(1)