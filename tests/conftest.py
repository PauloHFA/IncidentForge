"""Pytest configuration and fixtures."""

import pytest
import tempfile
from pathlib import Path

from incidentforge.models import (
    Incident, Topology, Service, ServiceTechnology, ServiceSLO, ServiceDependency,
    FailureCatalog, FailureTemplate, TimelineEvent, SLAImpact, ActionItem, IncidentMetadata,
    Severity, FailureCategory, Priority, Style, Language, ArchitectureProfile
)


@pytest.fixture
def sample_topology() -> Topology:
    """Create a sample topology for testing."""
    return Topology(
        version="1.0",
        services=[
            Service(
                name="api-gateway",
                technology=[
                    ServiceTechnology(name="nginx", category="network"),
                    ServiceTechnology(name="Go", category="compute"),
                ],
                slo=ServiceSLO(availability_target=0.9995, latency_p99_ms=100),
                dependencies=[
                    ServiceDependency(target="auth-service", traffic_percentage=90.0),
                    ServiceDependency(target="rate-limit-cache", traffic_percentage=100.0),
                ],
                team="platform-team",
            ),
            Service(
                name="auth-service",
                technology=[
                    ServiceTechnology(name="PostgreSQL", category="database"),
                    ServiceTechnology(name="Redis", category="cache"),
                    ServiceTechnology(name="Python", category="compute"),
                ],
                slo=ServiceSLO(availability_target=0.9999, latency_p99_ms=50),
                dependencies=[
                    ServiceDependency(target="auth-db", traffic_percentage=100.0),
                ],
                team="auth-team",
            ),
            Service(
                name="auth-db",
                technology=[
                    ServiceTechnology(name="PostgreSQL", category="database"),
                ],
                slo=ServiceSLO(availability_target=0.9999, latency_p99_ms=10),
                team="data-team",
            ),
        ],
    )


@pytest.fixture
def sample_catalog() -> FailureCatalog:
    """Create a sample failure catalog for testing."""
    return FailureCatalog(
        version="1.0",
        failures=[
            FailureTemplate(
                category=FailureCategory.CONNECTION_LEAK,
                name="Database Connection Leak",
                description="Connection pool exhaustion",
                applicable_technologies=["PostgreSQL", "HikariCP"],
                typical_severities=[Severity.SEV_2, Severity.SEV_3],
                min_duration_minutes=10,
                max_duration_minutes=120,
            ),
            FailureTemplate(
                category=FailureCategory.DEADLOCK,
                name="Database Deadlock",
                description="Circular wait condition",
                applicable_technologies=["PostgreSQL", "MySQL"],
                typical_severities=[Severity.SEV_2, Severity.SEV_3],
                min_duration_minutes=5,
                max_duration_minutes=60,
            ),
            FailureTemplate(
                category=FailureCategory.CACHE_STAMPEDE,
                name="Cache Stampede",
                description="Thundering herd",
                applicable_technologies=["Redis", "Memcached"],
                typical_severities=[Severity.SEV_1, Severity.SEV_2],
                min_duration_minutes=5,
                max_duration_minutes=60,
            ),
            FailureTemplate(
                category=FailureCategory.OOM_KILLED,
                name="Container OOMKilled",
                description="Memory limit exceeded",
                applicable_technologies=["Kubernetes", "Docker", "JVM", "Go"],
                typical_severities=[Severity.SEV_1, Severity.SEV_2],
                min_duration_minutes=5,
                max_duration_minutes=60,
            ),
        ],
    )


@pytest.fixture
def valid_incident() -> Incident:
    """Create a valid incident for testing."""
    return Incident(
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


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# Pytest configuration
def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )


# Async test support
@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()