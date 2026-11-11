"""Pydantic models for IncidentForge - Topology, Failures, and Incident schemas."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import core_schema


class Severity(str, Enum):
    """Incident severity levels."""

    SEV_1 = "SEV-1"
    SEV_2 = "SEV-2"
    SEV_3 = "SEV-3"
    SEV_4 = "SEV-4"


class Priority(str, Enum):
    """Action item priority levels."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ArchitectureProfile(str, Enum):
    """System architecture profiles."""

    MICROSERVICES = "microservices"
    MONOLITH_LEGACY = "monolith_legacy"
    SERVERLESS = "serverless"


class Language(str, Enum):
    """Supported languages for incident text."""

    PT_BR = "pt-BR"
    EN = "en"


class Style(str, Enum):
    """Incident report styles."""

    BLAMELESS_FORMAL = "blameless_formal"
    TERSE = "terse"
    DETAILED = "detailed"


class FailureCategory(str, Enum):
    """Failure categories from the default catalog."""

    # Database
    CONNECTION_LEAK = "Connection Leak"
    DEADLOCK = "Deadlock"
    SPLIT_BRAIN = "Split-brain"
    REPLICATION_LAG = "Replication Lag"
    QUERY_TIMEOUT = "Query Timeout"
    POOL_EXHAUSTION = "Pool Exhaustion"
    SCHEMA_MISMATCH = "Schema Mismatch"
    VACUUM_BLOCKING = "Vacuum Blocking"

    # Network
    DNS_RESOLUTION_FAILURE = "DNS Resolution Failure"
    NETWORK_PARTITION = "Network Partition"
    BANDWIDTH_SATURATION = "Bandwidth Saturation"
    TLS_HANDSHAKE_FAILURE = "TLS Handshake Failure"
    LOAD_BALANCER_MISCONFIG = "Load Balancer Misconfiguration"

    # Messaging
    MESSAGE_QUEUE_BACKLOG = "Message Queue Backlog"
    DUPLICATE_MESSAGE_PROCESSING = "Duplicate Message Processing"
    POISON_MESSAGE = "Poison Message"
    BROKER_UNAVAILABLE = "Broker Unavailable"
    CONSUMER_LAG = "Consumer Lag"

    # Compute
    OOM_KILLED = "OOMKilled"
    CPU_THROTTLING = "CPU Throttling"
    THREAD_POOL_EXHAUSTION = "Thread Pool Exhaustion"
    GC_PRESSURE = "GC Pressure"
    CONTAINER_RESTART_LOOP = "Container Restart Loop"

    # Cache
    CACHE_STAMPEDE = "Cache Stampede"
    CACHE_MISS_STORM = "Cache Miss Storm"
    STALE_CACHE = "Stale Cache"
    CACHE_EVICTION_STORM = "Cache Eviction Storm"

    # Deploy
    ROLLBACK_FAILURE = "Rollback Failure"
    CANARY_ANALYSIS_FAILURE = "Canary Analysis Failure"
    CONFIG_DRIFT = "Config Drift"
    DEPENDENCY_CONFLICT = "Dependency Conflict"
    MIGRATION_FAILURE = "Migration Failure"


# Custom types
IncidentID = Annotated[
    str,
    StringConstraints(pattern=r"^INC-\d{4}-\d{4}$"),
    Field(description="Incident ID in format INC-YYYY-NNNN"),
]

ISO8601DateTime = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"),
    Field(description="ISO 8601 datetime in UTC"),
]

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
RootCauseStr = Annotated[str, StringConstraints(min_length=150, strip_whitespace=True)]
ActionStr = Annotated[str, StringConstraints(min_length=10, strip_whitespace=True)]


class ServiceTechnology(BaseModel):
    """Technology stack for a service."""

    model_config = ConfigDict(extra="forbid")

    name: NonEmptyStr = Field(description="Technology name (e.g., PostgreSQL, Redis, Kafka)")
    version: str | None = Field(default=None, description="Version if applicable")
    category: NonEmptyStr = Field(description="Category: database, cache, messaging, compute, network, deploy")


class ServiceSLO(BaseModel):
    """Service Level Objectives."""

    model_config = ConfigDict(extra="forbid")

    availability_target: float = Field(ge=0.0, le=1.0, description="Availability target (e.g., 0.9995)")
    latency_p99_ms: int = Field(gt=0, description="P99 latency target in milliseconds")
    throughput_rps: int | None = Field(default=None, ge=0, description="Target throughput in requests per second")


class ServiceDependency(BaseModel):
    """Service dependency with traffic info."""

    model_config = ConfigDict(extra="forbid")

    target: NonEmptyStr = Field(description="Target service name")
    traffic_percentage: float = Field(ge=0.0, le=100.0, description="Percentage of traffic to this dependency")
    critical: bool = Field(default=True, description="Whether this dependency is critical for availability")


class Service(BaseModel):
    """Service definition in the topology."""

    model_config = ConfigDict(extra="forbid")

    name: NonEmptyStr = Field(description="Unique service name")
    technology: list[ServiceTechnology] = Field(min_length=1, description="Technology stack")
    slo: ServiceSLO = Field(description="Service Level Objectives")
    dependencies: list[ServiceDependency] = Field(default_factory=list, description="Downstream dependencies")
    team: NonEmptyStr = Field(description="Owning team name")
    region: NonEmptyStr = Field(default="us-east-1", description="Deployment region")
    replicas: int = Field(default=3, ge=1, description="Number of replicas")
    language: str | None = Field(default=None, description="Primary programming language")
    framework: str | None = Field(default=None, description="Primary framework")


class Topology(BaseModel):
    """System topology definition."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(default="1.0", description="Topology schema version")
    services: list[Service] = Field(min_length=1, description="List of services")
    global_slo: ServiceSLO | None = Field(default=None, description="Global SLO overriding service SLOs")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @field_validator("services", mode="after")
    @classmethod
    def validate_unique_service_names(cls, services: list[Service]) -> list[Service]:
        names = [s.name for s in services]
        if len(names) != len(set(names)):
            duplicates = [n for n in names if names.count(n) > 1]
            raise ValueError(f"Duplicate service names: {set(duplicates)}")
        return services

    @field_validator("services", mode="after")
    @classmethod
    def validate_dependencies_exist(cls, services: list[Service]) -> list[Service]:
        service_names = {s.name for s in services}
        for service in services:
            for dep in service.dependencies:
                if dep.target not in service_names:
                    raise ValueError(
                        f"Service '{service.name}' depends on non-existent service '{dep.target}'"
                    )
        return services

    def get_service(self, name: str) -> Service | None:
        """Get service by name."""
        return next((s for s in self.services if s.name == name), None)

    def get_dependencies(self, service_name: str) -> list[ServiceDependency]:
        """Get dependencies for a service."""
        service = self.get_service(service_name)
        return service.dependencies if service else []

    def get_dependents(self, service_name: str) -> list[Service]:
        """Get services that depend on the given service."""
        return [s for s in self.services if any(d.target == service_name for d in s.dependencies)]

    def has_cycles(self) -> bool:
        """Check for dependency cycles using DFS."""
        visited = set()
        rec_stack = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for dep in self.get_dependencies(node):
                if dep.target not in visited:
                    if dfs(dep.target):
                        return True
                elif dep.target in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        for service in self.services:
            if service.name not in visited:
                if dfs(service.name):
                    return True
        return False


class FailureTemplate(BaseModel):
    """Failure template from the catalog."""

    model_config = ConfigDict(extra="forbid")

    category: FailureCategory = Field(description="Failure category")
    name: NonEmptyStr = Field(description="Human-readable failure name")
    description: NonEmptyStr = Field(description="Description of the failure mode")
    applicable_technologies: list[str] = Field(
        min_length=1, description="List of technology names this failure applies to"
    )
    typical_severities: list[Severity] = Field(
        default_factory=lambda: [Severity.SEV_2, Severity.SEV_3],
        description="Typical severity levels for this failure",
    )
    min_duration_minutes: int = Field(default=5, ge=1, description="Minimum outage duration")
    max_duration_minutes: int = Field(default=240, ge=1, description="Maximum outage duration")
    tags: list[str] = Field(default_factory=list, description="Additional tags for filtering")


class FailureCatalog(BaseModel):
    """Catalog of failure templates."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(default="1.0", description="Catalog schema version")
    failures: list[FailureTemplate] = Field(min_length=25, description="Failure templates (min 25)")

    def get_applicable_failures(self, technologies: list[str]) -> list[FailureTemplate]:
        """Get failures applicable to the given technologies."""
        tech_set = set(t.lower() for t in technologies)
        return [
            f for f in self.failures
            if any(t.lower() in tech_set for t in f.applicable_technologies)
        ]

    def get_by_category(self, category: FailureCategory) -> FailureTemplate | None:
        """Get failure template by category."""
        return next((f for f in self.failures if f.category == category), None)

    def merge(self, other: "FailureCatalog", mode: str = "extend") -> "FailureCatalog":
        """Merge with another catalog.

        Args:
            other: Another FailureCatalog to merge with.
            mode: "extend" to combine both, "replace" to use only other.

        Returns:
            New FailureCatalog with merged failures.
        """
        if mode == "replace":
            merged_failures = other.failures.copy()
        else:  # extend
            existing_categories = {f.category for f in self.failures}
            merged_failures = self.failures.copy()
            for failure in other.failures:
                if failure.category not in existing_categories:
                    merged_failures.append(failure)
        return FailureCatalog(version=self.version, failures=merged_failures)

class TimelineEvent(BaseModel):
    """Single event in the incident timeline."""

    model_config = ConfigDict(extra="forbid")

    timestamp: ISO8601DateTime = Field(description="Event timestamp in UTC")
    event: NonEmptyStr = Field(description="Event description")
    source: NonEmptyStr = Field(description="Source component/service")
    severity: Severity | None = Field(default=None, description="Event severity if applicable")


class SLAImpact(BaseModel):
    """SLA impact metrics."""

    model_config = ConfigDict(extra="forbid")

    availability_before: float = Field(ge=0.0, le=1.0, description="Availability before incident")
    availability_after: float = Field(ge=0.0, le=1.0, description="Availability after incident")
    p99_latency_ms: int = Field(gt=0, description="P99 latency during incident in milliseconds")


class ActionItem(BaseModel):
    """Action item from incident review."""

    model_config = ConfigDict(extra="forbid")

    action: ActionStr = Field(description="Action description")
    owner: NonEmptyStr = Field(description="Responsible team/person")
    priority: Priority = Field(description="Priority level")


class IncidentMetadata(BaseModel):
    """Metadata about incident generation."""

    model_config = ConfigDict(extra="forbid")

    model: NonEmptyStr = Field(description="LLM model used for generation")
    prompt_version: NonEmptyStr = Field(description="Prompt template version")
    seed: int = Field(description="Random seed used")
    generated_at: ISO8601DateTime = Field(description="Generation timestamp")
    schema_version: str = Field(default="1.0", description="Incident schema version")
    synthetic: bool = Field(default=True, description="Always true for synthetic incidents")
    generation_time_ms: int | None = Field(default=None, description="Time taken to generate")
    tokens_input: int | None = Field(default=None, description="Input tokens used")
    tokens_output: int | None = Field(default=None, description="Output tokens used")


class Incident(BaseModel):
    """Complete incident report."""

    model_config = ConfigDict(extra="forbid")

    id: IncidentID = Field(description="Unique incident ID")
    service: NonEmptyStr = Field(description="Affected service name")
    severity: Severity = Field(description="Incident severity")
    outage_duration_minutes: int = Field(gt=0, description="Outage duration in minutes")
    failure_category: FailureCategory = Field(description="Failure category")
    sla_impact: SLAImpact = Field(description="SLA impact metrics")
    root_cause_analysis: RootCauseStr = Field(description="Root cause analysis (min 150 chars)")
    timeline: list[TimelineEvent] = Field(min_length=5, description="Chronological timeline (min 5 events)")
    action_items: list[ActionItem] = Field(min_length=2, max_length=8, description="Action items (2-8)")
    metadata: IncidentMetadata = Field(description="Generation metadata")



    @model_validator(mode="after")
    def validate_root_cause_mentions_technology(self) -> Incident:
        """Validate root cause mentions at least one technology from the service."""
        # This would need topology context; skip for now, validated in semantic validator
        return self


class GenerationPlan(BaseModel):
    """Plan for incident generation."""

    model_config = ConfigDict(extra="forbid")

    tasks: list[GenerationTask] = Field(description="Generation tasks")
    total_count: int = Field(description="Total number of tasks")
    seed: int = Field(description="Random seed for reproducibility")
    estimated_tokens: int = Field(default=0, description="Estimated token cost")


class GenerationTask(BaseModel):
    """Single generation task."""

    model_config = ConfigDict(extra="forbid")

    service_name: NonEmptyStr = Field(description="Service to generate incident for")
    failure_category: FailureCategory = Field(description="Failure category")
    severity: Severity = Field(description="Severity level")
    style: Style = Field(default=Style.BLAMELESS_FORMAL, description="Report style")
    language: Language = Field(default=Language.EN, description="Report language")
    architecture_profile: ArchitectureProfile = Field(
        default=ArchitectureProfile.MICROSERVICES, description="Architecture profile"
    )


class ValidationResult(BaseModel):
    """Result of incident validation."""

    model_config = ConfigDict(extra="forbid")

    valid: bool = Field(description="Whether validation passed")
    errors: list[str] = Field(default_factory=list, description="Validation errors")
    warnings: list[str] = Field(default_factory=list, description="Validation warnings")
    layer: Literal["schema", "semantic", "security"] = Field(description="Validation layer")


class RejectedIncident(BaseModel):
    """Rejected incident with reason."""

    model_config = ConfigDict(extra="forbid")

    task: GenerationTask = Field(description="Original generation task")
    raw_response: str = Field(description="Raw LLM response")
    validation_errors: list[ValidationResult] = Field(description="Validation failures")
    retry_count: int = Field(default=0, description="Number of retries attempted")
    rejected_at: ISO8601DateTime = Field(description="Rejection timestamp")


# JSON Schema export helper
def export_json_schema(model_class: type[BaseModel], output_path: str) -> None:
    """Export JSON schema for a model."""
    import json
    schema = model_class.model_json_schema()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    # Export schemas when run directly
    export_json_schema(Topology, "schema/topology.schema.json")
    export_json_schema(FailureCatalog, "schema/failures.schema.json")
    export_json_schema(Incident, "schema/incident.schema.json")
    print("Schemas exported to schema/")