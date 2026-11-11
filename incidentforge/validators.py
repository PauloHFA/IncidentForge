"""Multi-layer validation system for IncidentForge."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from .models import (
    Incident,
    IncidentMetadata,
    Service,
    Topology,
    ValidationResult,
)


@dataclass
class ValidationContext:
    """Context for validation."""

    topology: Topology
    service: Service
    task_metadata: dict[str, Any] | None = None


class SchemaValidator:
    """Layer 1: Schema validation using Pydantic."""

    @staticmethod
    def validate(incident: Incident) -> ValidationResult:
        """
        Validate incident against Pydantic schema.

        Args:
            incident: Incident to validate.

        Returns:
            ValidationResult with any schema errors.
        """
        errors = []
        warnings = []

        try:
            # Re-validate to catch any issues
            Incident.model_validate(incident.model_dump())
        except ValidationError as e:
            for err in e.errors():
                loc = " -> ".join(str(x) for x in err["loc"])
                errors.append(f"{loc}: {err['msg']}")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            layer="schema",
        )


class SemanticValidator:
    """Layer 2: Semantic validation (chronology, duration, topology consistency)."""

    def __init__(self, context: ValidationContext):
        self.context = context

    def validate(self, incident: Incident) -> ValidationResult:
        """
        Validate incident semantic rules.

        Args:
            incident: Incident to validate.

        Returns:
            ValidationResult with any semantic errors.
        """
        errors = []
        warnings = []

        # 1. Timeline chronological order
        timeline_errors = self._validate_timeline_order(incident)
        errors.extend(timeline_errors)

        # 2. Duration consistency
        duration_errors = self._validate_duration_consistency(incident)
        errors.extend(duration_errors)

        # 3. Topology consistency
        topology_errors = self._validate_topology_consistency(incident)
        errors.extend(topology_errors)

        # 4. Root cause mentions technology
        root_cause_errors = self._validate_root_cause_technology(incident)
        errors.extend(root_cause_errors)

        # 5. Action items validation
        action_errors = self._validate_action_items(incident)
        errors.extend(action_errors)

        # 6. SLA impact validation
        sla_errors = self._validate_sla_impact(incident)
        errors.extend(sla_errors)

        # 7. Severity consistency
        severity_warnings = self._validate_severity_consistency(incident)
        warnings.extend(severity_warnings)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            layer="semantic",
        )

    def _validate_timeline_order(self, incident: Incident) -> list[str]:
        """Validate timeline events are in strictly increasing order."""
        errors = []
        if len(incident.timeline) < 2:
            return errors

        prev_time = None
        for i, event in enumerate(incident.timeline):
            try:
                curr_time = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"Timeline event {i}: Invalid timestamp format: {event.timestamp}")
                continue

            if prev_time is not None and curr_time <= prev_time:
                errors.append(
                    f"Timeline event {i} ({curr_time.isoformat()}) is not strictly after "
                    f"event {i-1} ({prev_time.isoformat()})"
                )
            prev_time = curr_time

        return errors

    def _validate_duration_consistency(self, incident: Incident) -> list[str]:
        """Validate outage_duration_minutes matches timeline."""
        errors = []
        if not incident.timeline:
            return errors

        try:
            first = datetime.fromisoformat(incident.timeline[0].timestamp.replace("Z", "+00:00"))
            last = datetime.fromisoformat(incident.timeline[-1].timestamp.replace("Z", "+00:00"))
        except ValueError:
            return errors  # Timestamp errors caught elsewhere

        actual_duration = (last - first).total_seconds() / 60
        expected = incident.outage_duration_minutes

        if actual_duration == 0:
            return errors

        deviation = abs(actual_duration - expected) / expected
        if deviation > 0.1:  # 10% tolerance
            errors.append(
                f"Outage duration {expected}min deviates {deviation:.1%} from timeline "
                f"({actual_duration:.1f}min). Must be within 10%."
            )

        return errors

    def _validate_topology_consistency(self, incident: Incident) -> list[str]:
        """Validate incident is consistent with topology."""
        errors = []

        # Service must exist in topology
        service = self.context.topology.get_service(incident.service)
        if service is None:
            errors.append(f"Service '{incident.service}' not found in topology")
            return errors

        # Failure category should be applicable to service technologies
        tech_names = [t.name.lower() for t in service.technology]
        # This would need failure catalog context; skip for now

        return errors

    def _validate_root_cause_technology(self, incident: Incident) -> list[str]:
        """Validate root cause mentions at least one service technology."""
        errors = []
        service = self.context.topology.get_service(incident.service)
        if service is None:
            return errors

        tech_names = [t.name.lower() for t in service.technology]
        root_cause_lower = incident.root_cause_analysis.lower()

        if not any(tech in root_cause_lower for tech in tech_names):
            errors.append(
                f"Root cause analysis doesn't mention any service technology: {tech_names}. "
                f"Root cause: {incident.root_cause_analysis[:200]}..."
            )

        # Check minimum length
        if len(incident.root_cause_analysis) < 150:
            errors.append(
                f"Root cause analysis too short: {len(incident.root_cause_analysis)} chars, "
                f"minimum 150"
            )

        return errors

    def _validate_action_items(self, incident: Incident) -> list[str]:
        """Validate action items."""
        errors = []

        if not (2 <= len(incident.action_items) <= 8):
            errors.append(
                f"Action items count {len(incident.action_items)} not in range 2-8"
            )

        for i, item in enumerate(incident.action_items):
            if len(item.action) < 10:
                errors.append(f"Action item {i} too short: '{item.action}'")
            if not item.owner:
                errors.append(f"Action item {i} missing owner")
            if item.priority not in ["P0", "P1", "P2", "P3"]:
                errors.append(f"Action item {i} invalid priority: {item.priority}")

        return errors

    def _validate_sla_impact(self, incident: Incident) -> list[str]:
        """Validate SLA impact metrics."""
        errors = []
        sla = incident.sla_impact

        if sla.availability_before <= sla.availability_after:
            errors.append(
                f"Availability before ({sla.availability_before}) should be greater than "
                f"after ({sla.availability_after})"
            )

        if not (0 <= sla.availability_before <= 1):
            errors.append(f"Availability before out of range: {sla.availability_before}")

        if not (0 <= sla.availability_after <= 1):
            errors.append(f"Availability after out of range: {sla.availability_after}")

        if sla.p99_latency_ms <= 0:
            errors.append(f"P99 latency must be positive: {sla.p99_latency_ms}")

        return errors

    def _validate_severity_consistency(self, incident: Incident) -> list[str]:
        """Validate severity is consistent with impact."""
        warnings = []
        sla = incident.sla_impact

        # SEV-1 should have significant availability impact
        if incident.severity.value == "SEV-1":
            availability_drop = sla.availability_before - sla.availability_after
            if availability_drop < 0.01:  # Less than 1% drop
                warnings.append(
                    f"SEV-1 incident has minimal availability impact ({availability_drop:.2%})"
                )

        # SEV-4 should have minimal impact
        if incident.severity.value == "SEV-4":
            availability_drop = sla.availability_before - sla.availability_after
            if availability_drop > 0.05:  # More than 5% drop
                warnings.append(
                    f"SEV-4 incident has significant availability impact ({availability_drop:.2%})"
                )

        return warnings


class SecurityValidator:
    """Layer 3: Security validation (PII, secrets, injection)."""

    # Patterns for detecting sensitive data
    PII_PATTERNS = [
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "email"),
        (r"\b\d{3}-\d{2}-\d{4}\b", "ssn"),
        (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "credit_card"),
        (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "ipv4"),
        (r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b", "ipv6"),
        (r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "phone"),
        (r"\b[A-Za-z0-9]{32,}\b", "api_key"),  # Generic long token
        (r"sk-[A-Za-z0-9]{48}", "openai_key"),
        (r"gh[pousr]_[A-Za-z0-9]{36,}", "github_token"),
        (r"aws_access_key_id\s*=\s*[A-Z0-9]{20}", "aws_key"),
        (r"aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}", "aws_secret"),
    ]

    INJECTION_PATTERNS = [
        (r"ignore\s+(?:previous|above|all)\s+(?:instructions|rules|prompts?)", "prompt_injection"),
        (r"disregard\s+(?:previous|above|all)\s+(?:instructions|rules|prompts?)", "prompt_injection"),
        (r"system\s*:\s*you\s+are", "role_injection"),
        (r"<\|im_start\|>", "token_injection"),
        (r"<\|im_end\|>", "token_injection"),
    ]

    def __init__(self, context: ValidationContext):
        self.context = context

    def validate(self, incident: Incident) -> ValidationResult:
        """
        Validate incident for security issues.

        Args:
            incident: Incident to validate.

        Returns:
            ValidationResult with any security errors.
        """
        errors = []
        warnings = []

        # Check all text fields for PII
        text_fields = {
            "root_cause_analysis": incident.root_cause_analysis,
            "timeline_events": " ".join(e.event for e in incident.timeline),
            "action_items": " ".join(item.action for item in incident.action_items),
        }

        for field_name, text in text_fields.items():
            pii_found = self._scan_pii(text)
            for pattern, pii_type in pii_found:
                errors.append(
                    f"Potential {pii_type} detected in {field_name}: {pattern[:50]}..."
                )

            injection_found = self._scan_injection(text)
            for pattern, inj_type in injection_found:
                errors.append(
                    f"Potential {inj_type} detected in {field_name}: {pattern[:50]}..."
                )

        # Check metadata for sensitive info
        if incident.metadata.model:
            # Model name is OK
            pass

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            layer="security",
        )

    def _scan_pii(self, text: str) -> list[tuple[str, str]]:
        """Scan text for PII patterns."""
        found = []
        for pattern, pii_type in self.PII_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                found.append((match, pii_type))
        return found

    def _scan_injection(self, text: str) -> list[tuple[str, str]]:
        """Scan text for prompt injection patterns."""
        found = []
        for pattern, inj_type in self.INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                found.append((pattern, inj_type))
        return found


class MultiLayerValidator:
    """Orchestrates all three validation layers."""

    def __init__(self, context: ValidationContext):
        self.context = context
        self.schema_validator = SchemaValidator()
        self.semantic_validator = SemanticValidator(context)
        self.security_validator = SecurityValidator(context)

    def validate(self, incident: Incident) -> list[ValidationResult]:
        """
        Run all validation layers.

        Args:
            incident: Incident to validate.

        Returns:
            List of ValidationResult for each layer.
        """
        results = []

        # Layer 1: Schema
        schema_result = self.schema_validator.validate(incident)
        results.append(schema_result)

        # Only run semantic if schema passes
        if schema_result.valid:
            semantic_result = self.semantic_validator.validate(incident)
            results.append(semantic_result)

            # Only run security if semantic passes
            if semantic_result.valid:
                security_result = self.security_validator.validate(incident)
                results.append(security_result)

        return results

    def is_valid(self, incident: Incident) -> bool:
        """Check if incident passes all validation layers."""
        results = self.validate(incident)
        return all(r.valid for r in results)

    def get_all_errors(self, incident: Incident) -> list[str]:
        """Get all errors from all layers."""
        results = self.validate(incident)
        errors = []
        for r in results:
            errors.extend(r.errors)
        return errors


def create_validator(topology: Topology, service: Service) -> MultiLayerValidator:
    """Create a multi-layer validator for a service."""
    context = ValidationContext(topology=topology, service=service)
    return MultiLayerValidator(context)


def validate_incident(incident: Incident, topology: Topology) -> list[ValidationResult]:
    """
    Convenience function to validate an incident.

    Args:
        incident: Incident to validate.
        topology: System topology.

    Returns:
        List of ValidationResult for each layer.
    """
    service = topology.get_service(incident.service)
    if service is None:
        return [ValidationResult(
            valid=False,
            errors=[f"Service '{incident.service}' not found in topology"],
            layer="schema",
        )]

    validator = create_validator(topology, service)
    return validator.validate(incident)


if __name__ == "__main__":
    # Test validators
    from .topology import load_topology
    from .models import Incident, TimelineEvent, SLAImpact, ActionItem, IncidentMetadata, Severity, FailureCategory, Priority, Language, Style, ArchitectureProfile

    topology = load_topology("configs/topology_sample.yaml")
    service = topology.get_service("api-gateway")

    # Create a test incident
    incident = Incident(
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
    )

    validator = create_validator(topology, service)
    results = validator.validate(incident)

    for result in results:
        print(f"\n=== {result.layer.upper()} ===")
        print(f"Valid: {result.valid}")
        for err in result.errors:
            print(f"  ERROR: {err}")
        for warn in result.warnings:
            print(f"  WARN: {warn}")