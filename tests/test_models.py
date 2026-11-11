"""Tests for Pydantic models."""

import pytest
from datetime import datetime

from incidentforge.models import (
    Incident,
    Topology,
    FailureCatalog,
    Service,
    ServiceTechnology,
    ServiceSLO,
    ServiceDependency,
    FailureTemplate,
    TimelineEvent,
    SLAImpact,
    ActionItem,
    IncidentMetadata,
    Severity,
    FailureCategory,
    Priority,
    Style,
    Language,
    ArchitectureProfile,
)


class TestSeverity:
    """Tests for Severity enum."""

    def test_severity_values(self):
        assert Severity.SEV_1.value == "SEV-1"
        assert Severity.SEV_2.value == "SEV-2"
        assert Severity.SEV_3.value == "SEV-3"
        assert Severity.SEV_4.value == "SEV-4"


class TestFailureCategory:
    """Tests for FailureCategory enum."""

    def test_category_values(self):
        assert FailureCategory.CONNECTION_LEAK.value == "Connection Leak"
        assert FailureCategory.DEADLOCK.value == "Deadlock"
        assert FailureCategory.OOM_KILLED.value == "OOMKilled"
        assert FailureCategory.CACHE_STAMPEDE.value == "Cache Stampede"


class TestServiceTechnology:
    """Tests for ServiceTechnology model."""

    def test_valid_technology(self):
        tech = ServiceTechnology(
            name="PostgreSQL",
            version="15.2",
            category="database",
        )
        assert tech.name == "PostgreSQL"
        assert tech.version == "15.2"
        assert tech.category == "database"

    def test_technology_without_version(self):
        tech = ServiceTechnology(
            name="Redis",
            category="cache",
        )
        assert tech.version is None


class TestServiceSLO:
    """Tests for ServiceSLO model."""

    def test_valid_slo(self):
        slo = ServiceSLO(
            availability_target=0.9995,
            latency_p99_ms=200,
            throughput_rps=1000,
        )
        assert slo.availability_target == 0.9995
        assert slo.latency_p99_ms == 200
        assert slo.throughput_rps == 1000

    def test_slo_without_throughput(self):
        slo = ServiceSLO(
            availability_target=0.999,
            latency_p99_ms=500,
        )
        assert slo.throughput_rps is None

    def test_invalid_availability(self):
        with pytest.raises(ValueError):
            ServiceSLO(availability_target=1.5, latency_p99_ms=100)

    def test_invalid_latency(self):
        with pytest.raises(ValueError):
            ServiceSLO(availability_target=0.99, latency_p99_ms=-1)


class TestServiceDependency:
    """Tests for ServiceDependency model."""

    def test_valid_dependency(self):
        dep = ServiceDependency(
            target="auth-service",
            traffic_percentage=80.0,
            critical=True,
        )
        assert dep.target == "auth-service"
        assert dep.traffic_percentage == 80.0
        assert dep.critical is True

    def test_default_critical(self):
        dep = ServiceDependency(target="service", traffic_percentage=50.0)
        assert dep.critical is True


class TestService:
    """Tests for Service model."""

    def test_valid_service(self):
        service = Service(
            name="api-gateway",
            technology=[
                ServiceTechnology(name="nginx", category="network"),
                ServiceTechnology(name="Go", version="1.21", category="compute"),
            ],
            slo=ServiceSLO(availability_target=0.9995, latency_p99_ms=100),
            dependencies=[
                ServiceDependency(target="auth-service", traffic_percentage=90.0),
            ],
            team="platform-team",
            region="us-east-1",
            replicas=3,
        )
        assert service.name == "api-gateway"
        assert len(service.technology) == 2
        assert len(service.dependencies) == 1
        assert service.replicas == 3


class TestTopology:
    """Tests for Topology model."""

    def test_valid_topology(self):
        topology = Topology(
            version="1.0",
            services=[
                Service(
                    name="service-a",
                    technology=[ServiceTechnology(name="PostgreSQL", category="database")],
                    slo=ServiceSLO(availability_target=0.999, latency_p99_ms=200),
                    team="team-a",
                ),
                Service(
                    name="service-b",
                    technology=[ServiceTechnology(name="Redis", category="cache")],
                    slo=ServiceSLO(availability_target=0.999, latency_p99_ms=100),
                    team="team-b",
                    dependencies=[ServiceDependency(target="service-a", traffic_percentage=100.0)],
                ),
            ],
        )
        assert len(topology.services) == 2
        assert topology.version == "1.0"

    def test_duplicate_service_names(self):
        with pytest.raises(ValueError, match="Duplicate service names"):
            Topology(
                services=[
                    Service(
                        name="service-a",
                        technology=[ServiceTechnology(name="PostgreSQL", category="database")],
                        slo=ServiceSLO(availability_target=0.999, latency_p99_ms=200),
                        team="team-a",
                    ),
                    Service(
                        name="service-a",  # Duplicate
                        technology=[ServiceTechnology(name="Redis", category="cache")],
                        slo=ServiceSLO(availability_target=0.999, latency_p99_ms=100),
                        team="team-b",
                    ),
                ],
            )

    def test_invalid_dependency(self):
        with pytest.raises(ValueError, match="depends on non-existent service"):
            Topology(
                services=[
                    Service(
                        name="service-a",
                        technology=[ServiceTechnology(name="PostgreSQL", category="database")],
                        slo=ServiceSLO(availability_target=0.999, latency_p99_ms=200),
                        team="team-a",
                        dependencies=[ServiceDependency(target="non-existent", traffic_percentage=100.0)],
                    ),
                ],
            )

    def test_get_service(self):
        topology = Topology(
            services=[
                Service(
                    name="service-a",
                    technology=[ServiceTechnology(name="PostgreSQL", category="database")],
                    slo=ServiceSLO(availability_target=0.999, latency_p99_ms=200),
                    team="team-a",
                ),
            ],
        )
        service = topology.get_service("service-a")
        assert service is not None
        assert service.name == "service-a"

        assert topology.get_service("non-existent") is None

    def test_has_cycles(self):
        # No cycles
        topology = Topology(
            services=[
                Service(
                    name="a",
                    technology=[ServiceTechnology(name="PostgreSQL", category="database")],
                    slo=ServiceSLO(availability_target=0.999, latency_p99_ms=200),
                    team="team-a",
                ),
                Service(
                    name="b",
                    technology=[ServiceTechnology(name="Redis", category="cache")],
                    slo=ServiceSLO(availability_target=0.999, latency_p99_ms=100),
                    team="team-b",
                    dependencies=[ServiceDependency(target="a", traffic_percentage=100.0)],
                ),
            ],
        )
        assert topology.has_cycles() is False

        # With cycle
        topology_cycle = Topology(
            services=[
                Service(
                    name="a",
                    technology=[ServiceTechnology(name="PostgreSQL", category="database")],
                    slo=ServiceSLO(availability_target=0.999, latency_p99_ms=200),
                    team="team-a",
                    dependencies=[ServiceDependency(target="b", traffic_percentage=100.0)],
                ),
                Service(
                    name="b",
                    technology=[ServiceTechnology(name="Redis", category="cache")],
                    slo=ServiceSLO(availability_target=0.999, latency_p99_ms=100),
                    team="team-b",
                    dependencies=[ServiceDependency(target="a", traffic_percentage=100.0)],
                ),
            ],
        )
        assert topology_cycle.has_cycles() is True


class TestFailureTemplate:
    """Tests for FailureTemplate model."""

    def test_valid_template(self):
        template = FailureTemplate(
            category=FailureCategory.CONNECTION_LEAK,
            name="Database Connection Leak",
            description="Application fails to return connections to pool",
            applicable_technologies=["PostgreSQL", "HikariCP"],
            typical_severities=[Severity.SEV_2, Severity.SEV_3],
            min_duration_minutes=10,
            max_duration_minutes=120,
            tags=["database", "resource-exhaustion"],
        )
        assert template.category == FailureCategory.CONNECTION_LEAK
        assert len(template.applicable_technologies) == 2


class TestFailureCatalog:
    """Tests for FailureCatalog model."""

    def _make_failure(self, category: FailureCategory, tech: list[str], idx: int = 0) -> FailureTemplate:
        """Helper to create a failure template for testing."""
        return FailureTemplate(
            category=category,
            name=f"{category.value} {idx}",
            description=f"Test failure for {category.value}",
            applicable_technologies=tech,
            typical_severities=[Severity.SEV_2],
            min_duration_minutes=5,
            max_duration_minutes=60,
        )

    def test_valid_catalog(self):
        # Create 25 failures to meet min_length requirement
        failures = []
        categories = list(FailureCategory)
        for i in range(25):
            cat = categories[i % len(categories)]
            failures.append(self._make_failure(cat, ["PostgreSQL"], i))
        
        catalog = FailureCatalog(version="1.0", failures=failures)
        assert len(catalog.failures) == 25

    def test_get_applicable_failures(self):
        # Create catalog with enough failures
        failures = []
        for i in range(25):
            cat = list(FailureCategory)[i % len(FailureCategory)]
            tech = ["PostgreSQL"] if i % 2 == 0 else ["Redis"]
            failures.append(self._make_failure(cat, tech, i))
        
        catalog = FailureCatalog(version="1.0", failures=failures)
        
        # Should find PostgreSQL failures
        pg_failures = catalog.get_applicable_failures(["PostgreSQL"])
        assert len(pg_failures) >= 1
        assert all("PostgreSQL" in f.applicable_technologies for f in pg_failures)

        # Should find Redis failures
        redis_failures = catalog.get_applicable_failures(["Redis"])
        assert len(redis_failures) >= 1
        assert all("Redis" in f.applicable_technologies for f in redis_failures)

        # Should find both
        both = catalog.get_applicable_failures(["PostgreSQL", "Redis"])
        assert len(both) >= 2


class TestTimelineEvent:
    """Tests for TimelineEvent model."""

    def test_valid_event(self):
        event = TimelineEvent(
            timestamp="2024-01-15T10:00:00Z",
            event="Connection pool usage starts increasing",
            source="nginx",
            severity=Severity.SEV_4,
        )
        assert event.timestamp == "2024-01-15T10:00:00Z"
        assert event.severity == Severity.SEV_4

    def test_event_without_severity(self):
        event = TimelineEvent(
            timestamp="2024-01-15T10:00:00Z",
            event="Event without severity",
            source="service",
        )
        assert event.severity is None


class TestSLAImpact:
    """Tests for SLAImpact model."""

    def test_valid_sla_impact(self):
        sla = SLAImpact(
            availability_before=0.9999,
            availability_after=0.9950,
            p99_latency_ms=5000,
        )
        assert sla.availability_before == 0.9999
        assert sla.availability_after == 0.9950
        assert sla.p99_latency_ms == 5000


class TestActionItem:
    """Tests for ActionItem model."""

    def test_valid_action_item(self):
        item = ActionItem(
            action="Fix connection leak in nginx upstream configuration",
            owner="platform-team",
            priority=Priority.P0,
        )
        assert item.action == "Fix connection leak in nginx upstream configuration"
        assert item.priority == Priority.P0

    def test_invalid_short_action(self):
        with pytest.raises(ValueError):
            ActionItem(action="Too short", owner="team", priority=Priority.P1)


class TestIncidentMetadata:
    """Tests for IncidentMetadata model."""

    def test_valid_metadata(self):
        metadata = IncidentMetadata(
            model="gpt-4o-mini",
            prompt_version="1.0",
            seed=42,
            generated_at="2024-01-15T11:00:00Z",
            schema_version="1.0",
            synthetic=True,
        )
        assert metadata.model == "gpt-4o-mini"
        assert metadata.seed == 42
        assert metadata.synthetic is True


class TestIncident:
    """Tests for Incident model."""

    def create_valid_incident(self) -> Incident:
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

    def test_valid_incident(self):
        incident = self.create_valid_incident()
        assert incident.id == "INC-2024-0001"
        assert incident.service == "api-gateway"
        assert incident.severity == Severity.SEV_2
        assert len(incident.timeline) == 5
        assert len(incident.action_items) == 2

    def test_invalid_timeline_order(self):
        incident = self.create_valid_incident()
        # Swap timeline events to make them out of order
        incident.timeline[0], incident.timeline[1] = incident.timeline[1], incident.timeline[0]
        # This is now validated in the semantic validator layer, not the model
        # The model will still accept it, but semantic validation will catch it
        validated = Incident.model_validate(incident.model_dump())
        assert validated is not None

    def test_invalid_duration_consistency(self):
        incident = self.create_valid_incident()
        # Make duration inconsistent with timeline
        incident.outage_duration_minutes = 100  # Timeline spans 30 minutes
        # This is now validated in the semantic validator layer, not the model
        validated = Incident.model_validate(incident.model_dump())
        assert validated is not None

    def test_short_root_cause(self):
        incident = self.create_valid_incident()
        incident.root_cause_analysis = "Too short"
        with pytest.raises(ValueError):
            Incident.model_validate(incident.model_dump())

    def test_invalid_action_items_count(self):
        incident = self.create_valid_incident()
        incident.action_items = [incident.action_items[0]]  # Only 1 action item
        with pytest.raises(ValueError):
            Incident.model_validate(incident.model_dump())

    def test_incident_id_format(self):
        with pytest.raises(ValueError):
            Incident(
                id="INVALID-ID",
                service="api-gateway",
                severity=Severity.SEV_2,
                outage_duration_minutes=30,
                failure_category=FailureCategory.CONNECTION_LEAK,
                sla_impact=SLAImpact(availability_before=0.9999, availability_after=0.9950, p99_latency_ms=5000),
                root_cause_analysis="A connection leak in the nginx upstream module caused pool exhaustion.",
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
            )


class TestJSONSchemaExport:
    """Tests for JSON Schema export."""

    def test_incident_schema(self):
        schema = Incident.model_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "id" in schema["properties"]
        assert "service" in schema["properties"]
        assert "severity" in schema["properties"]

    def test_topology_schema(self):
        schema = Topology.model_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "services" in schema["properties"]

    def test_failure_catalog_schema(self):
        schema = FailureCatalog.model_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "failures" in schema["properties"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])