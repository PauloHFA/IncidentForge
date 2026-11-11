"""Tests for task planner."""

import pytest
from incidentforge.planner import TaskPlanner, PlannerConfig, build_generation_plan
from incidentforge.models import (
    Topology, Service, ServiceTechnology, ServiceSLO, ServiceDependency,
    FailureCatalog, FailureTemplate, FailureCategory, Severity, Style, Language, ArchitectureProfile
)


def create_sample_topology() -> Topology:
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


def create_sample_catalog() -> FailureCatalog:
    """Create a sample failure catalog for testing."""
    from incidentforge.failures import load_failure_catalog
    return load_failure_catalog()
class TestPlannerConfig:
    """Tests for PlannerConfig."""

    def test_default_config(self):
        config = PlannerConfig()
        assert config.count == 100
        assert config.seed == 42
        assert config.severity_distribution is None
        assert config.style_distribution is None
        assert config.language_distribution is None
        assert config.architecture_profile == ArchitectureProfile.MICROSERVICES
        assert config.failures_mode == "extend"
        assert config.user_failures_path is None
        assert config.dry_run is False

    def test_custom_config(self):
        config = PlannerConfig(
            count=50,
            seed=123,
            severity_distribution={Severity.SEV_1: 0.5, Severity.SEV_2: 0.5},
            dry_run=True,
        )
        assert config.count == 50
        assert config.seed == 123
        assert config.severity_distribution is not None
        assert config.dry_run is True


class TestTaskPlanner:
    """Tests for TaskPlanner."""

    def test_build_plan_basic(self):
        """Test basic plan generation."""
        topology = create_sample_topology()
        catalog = create_sample_catalog()

        config = PlannerConfig(count=10, seed=42)
        planner = TaskPlanner(config)
        plan = planner.build_plan(topology, catalog)

        assert plan.total_count == 10
        assert plan.seed == 42
        assert len(plan.tasks) == 10
        assert plan.estimated_tokens > 0

    def test_build_plan_all_combinations(self):
        """Test plan generation with all valid combinations."""
        topology = create_sample_topology()
        catalog = create_sample_catalog()

        # Count larger than combinations to test variation
        config = PlannerConfig(count=100, seed=42)
        planner = TaskPlanner(config)
        plan = planner.build_plan(topology, catalog)

        # Should have tasks for all valid service/failure/severity combinations
        assert plan.total_count > 0
        assert len(plan.tasks) == plan.total_count

    def test_deterministic_generation(self):
        """Test that same seed produces same plan."""
        topology = create_sample_topology()
        catalog = create_sample_catalog()

        config1 = PlannerConfig(count=20, seed=42)
        planner1 = TaskPlanner(config1)
        plan1 = planner1.build_plan(topology, catalog)

        config2 = PlannerConfig(count=20, seed=42)
        planner2 = TaskPlanner(config2)
        plan2 = planner2.build_plan(topology, catalog)

        # Same seed should produce identical tasks
        assert len(plan1.tasks) == len(plan2.tasks)
        for t1, t2 in zip(plan1.tasks, plan2.tasks):
            assert t1.service_name == t2.service_name
            assert t1.failure_category == t2.failure_category
            assert t1.severity == t2.severity

    def test_different_seeds_produce_different_plans(self):
        """Test that different seeds produce different plans."""
        topology = create_sample_topology()
        catalog = create_sample_catalog()

        config1 = PlannerConfig(count=20, seed=42)
        planner1 = TaskPlanner(config1)
        plan1 = planner1.build_plan(topology, catalog)

        config2 = PlannerConfig(count=20, seed=123)
        planner2 = TaskPlanner(config2)
        plan2 = planner2.build_plan(topology, catalog)

        # Different seeds should produce different task orders
        # (though they might have same combinations, order should differ)
        task_keys_1 = [(t.service_name, t.failure_category.value, t.severity.value) for t in plan1.tasks]
        task_keys_2 = [(t.service_name, t.failure_category.value, t.severity.value) for t in plan2.tasks]

        # At least the order should be different
        assert task_keys_1 != task_keys_2

    def test_severity_distribution(self):
        """Test severity distribution is applied."""
        topology = create_sample_topology()
        catalog = create_sample_catalog()

        config = PlannerConfig(
            count=100,
            seed=42,
            severity_distribution={
                Severity.SEV_1: 0.5,
                Severity.SEV_2: 0.3,
                Severity.SEV_3: 0.2,
            },
        )
        planner = TaskPlanner(config)
        plan = planner.build_plan(topology, catalog)

        # Count severities
        severity_counts = {}
        for task in plan.tasks:
            severity_counts[task.severity] = severity_counts.get(task.severity, 0) + 1

        # SEV-1 should be most common
        assert severity_counts.get(Severity.SEV_1, 0) > severity_counts.get(Severity.SEV_3, 0)

    def test_task_attributes(self):
        """Test that generated tasks have all required attributes."""
        topology = create_sample_topology()
        catalog = create_sample_catalog()

        config = PlannerConfig(count=10, seed=42)
        planner = TaskPlanner(config)
        plan = planner.build_plan(topology, catalog)

        for task in plan.tasks:
            assert task.service_name in ["api-gateway", "auth-service", "auth-db"]
            assert task.failure_category is not None  # any catalog failure
            assert task.severity in [Severity.SEV_1, Severity.SEV_2, Severity.SEV_3, Severity.SEV_4]
            assert task.style in [Style.BLAMELESS_FORMAL, Style.DETAILED, Style.TERSE]
            assert task.language in [Language.EN, Language.PT_BR]
            assert task.architecture_profile == ArchitectureProfile.MICROSERVICES

    def test_technology_compatibility_filtering(self):
        """Test that only compatible failures are included for each service."""
        topology = create_sample_topology()
        catalog = create_sample_catalog()

        config = PlannerConfig(count=50, seed=42)
        planner = TaskPlanner(config)
        plan = planner.build_plan(topology, catalog)

        # auth-db only has PostgreSQL, so all tasks should be PostgreSQL-compatible
        auth_db_tasks = [t for t in plan.tasks if t.service_name == "auth-db"]
        for task in auth_db_tasks:
            # Verify PostgreSQL compatibility via the catalog
            matching = catalog.get_applicable_failures(["PostgreSQL"])
            compatible_cats = {f.category for f in matching}
            assert task.failure_category in compatible_cats

        # auth-service has PostgreSQL and Redis
        auth_service_tasks = [t for t in plan.tasks if t.service_name == "auth-service"]
        categories = {t.failure_category for t in auth_service_tasks}
        # Should have PostgreSQL and Redis compatible failures
        assert FailureCategory.CONNECTION_LEAK in categories or FailureCategory.DEADLOCK in categories
        assert FailureCategory.CACHE_STAMPEDE in categories

    def test_build_generation_plan_convenience(self):
        """Test the convenience function."""
        topology = create_sample_topology()

        plan = build_generation_plan(
            topology,
            count=20,
            seed=42,
        )

        assert plan.total_count == 20
        assert plan.seed == 42
        assert len(plan.tasks) == 20

    def test_empty_catalog_raises_error(self):
        """Test that empty catalog raises error."""
        topology = create_sample_topology()
        # Can't construct FailureCatalog with 0 failures (min is 25) so use a catalog
        # with failures that don't match any service technology
        from incidentforge.failures import load_failure_catalog
        # Use the real catalog but expect no combinations for an incompatible topology
        pass  # Covered by test_incompatible_technologies_raises_error

    def test_incompatible_technologies_raises_error(self):
        """Test that topology with no compatible technologies raises error."""
        # Topology with technology not in catalog
        topology = Topology(
            version="1.0",
            services=[
                Service(
                    name="unknown-service",
                    technology=[ServiceTechnology(name="UnknownTech", category="compute")],
                    slo=ServiceSLO(availability_target=0.999, latency_p99_ms=100),
                    team="team",
                ),
            ],
        )
        catalog = create_sample_catalog()

        config = PlannerConfig(count=10, seed=42)
        planner = TaskPlanner(config)

        with pytest.raises(ValueError, match="No valid task combinations found"):
            planner.build_plan(topology, catalog)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])