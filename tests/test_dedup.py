"""Tests for deduplication."""

import pytest
from incidentforge.dedup import (
    DedupConfig,
    EmbeddingDeduplicator,
    MinHashDeduplicator,
    DiversityController,
)
from incidentforge.models import (
    Incident, TimelineEvent, SLAImpact, ActionItem, IncidentMetadata,
    Severity, FailureCategory, Priority
)


def create_incident(
    incident_id: str,
    service: str,
    category: FailureCategory,
    root_cause: str,
) -> Incident:
    """Create a test incident."""
    # Ensure root_cause is at least 150 characters
    if len(root_cause) < 150:
        root_cause = root_cause + " " + "This is a detailed root cause analysis that explains the underlying technical issues that led to the incident. The investigation revealed multiple contributing factors including configuration issues, resource constraints, and monitoring gaps that need to be addressed to prevent recurrence."
    
    return Incident(
        id=incident_id,
        service=service,
        severity=Severity.SEV_2,
        outage_duration_minutes=30,
        failure_category=category,
        sla_impact=SLAImpact(
            availability_before=0.9999,
            availability_after=0.9950,
            p99_latency_ms=5000,
        ),
        root_cause_analysis=root_cause,
        timeline=[
            TimelineEvent(timestamp="2024-01-15T10:00:00Z", event="Event 1", source=service),
            TimelineEvent(timestamp="2024-01-15T10:05:00Z", event="Event 2", source=service),
            TimelineEvent(timestamp="2024-01-15T10:15:00Z", event="Event 3", source=service),
            TimelineEvent(timestamp="2024-01-15T10:25:00Z", event="Event 4", source=service),
            TimelineEvent(timestamp="2024-01-15T10:30:00Z", event="Event 5", source=service),
        ],
        action_items=[
            ActionItem(action="Fix the issue", owner="team", priority=Priority.P0),
            ActionItem(action="Add monitoring", owner="team", priority=Priority.P1),
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


class TestDedupConfig:
    """Tests for DedupConfig."""

    def test_default_config(self):
        config = DedupConfig()
        assert config.similarity_threshold == 0.92
        assert config.minhash_threshold == 0.85
        assert config.num_perm == 128
        assert config.use_embeddings is True
        assert config.use_minhash is True

    def test_custom_config(self):
        config = DedupConfig(
            similarity_threshold=0.95,
            minhash_threshold=0.90,
            use_embeddings=False,
        )
        assert config.similarity_threshold == 0.95
        assert config.minhash_threshold == 0.90
        assert config.use_embeddings is False
        assert config.use_minhash is True


class TestEmbeddingDeduplicator:
    """Tests for EmbeddingDeduplicator."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = DedupConfig(
            similarity_threshold=0.92,
            use_embeddings=True,
            use_minhash=False,
        )
        self.dedup = EmbeddingDeduplicator(self.config)

    def test_add_and_check_duplicate(self):
        """Test adding and checking for duplicates."""
        incident1 = create_incident(
            "INC-2024-0001",
            "api-gateway",
            FailureCategory.CONNECTION_LEAK,
            "A connection leak in the nginx upstream module caused pool exhaustion. The HikariCP pool was not returning connections properly.",
        )
        incident2 = create_incident(
            "INC-2024-0002",
            "api-gateway",
            FailureCategory.CONNECTION_LEAK,
            "A connection leak in the nginx upstream module caused pool exhaustion. The HikariCP pool was not returning connections properly.",
        )
        incident3 = create_incident(
            "INC-2024-0003",
            "auth-service",
            FailureCategory.DEADLOCK,
            "A deadlock occurred in the PostgreSQL database when two transactions waited for each other's locks.",
        )

        # Add first incident
        self.dedup.add(incident1)

        # Check duplicate of first incident
        is_dup, dup_id, sim = self.dedup.is_duplicate(incident2)
        assert is_dup is True
        assert dup_id == "INC-2024-0001"
        assert sim > 0.9

        # Check different incident
        is_dup, dup_id, sim = self.dedup.is_duplicate(incident3)
        assert is_dup is False

    def test_different_incidents_not_duplicate(self):
        """Test that different incidents are not flagged as duplicates."""
        incident1 = create_incident(
            "INC-2024-0001",
            "api-gateway",
            FailureCategory.CONNECTION_LEAK,
            "A connection leak in the nginx upstream module caused pool exhaustion.",
        )
        incident2 = create_incident(
            "INC-2024-0002",
            "auth-service",
            FailureCategory.DEADLOCK,
            "A deadlock occurred in the PostgreSQL database when two transactions waited for each other's locks.",
        )

        self.dedup.add(incident1)
        is_dup, _, _ = self.dedup.is_duplicate(incident2)
        assert is_dup is False


class TestMinHashDeduplicator:
    """Tests for MinHashDeduplicator."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = DedupConfig(
            minhash_threshold=0.85,
            use_embeddings=False,
            use_minhash=True,
        )
        self.dedup = MinHashDeduplicator(self.config)

    def test_add_and_check_duplicate(self):
        """Test adding and checking for duplicates with MinHash."""
        incident1 = create_incident(
            "INC-2024-0001",
            "api-gateway",
            FailureCategory.CONNECTION_LEAK,
            "A connection leak in the nginx upstream module caused pool exhaustion. The HikariCP pool was not returning connections properly.",
        )
        incident2 = create_incident(
            "INC-2024-0002",
            "api-gateway",
            FailureCategory.CONNECTION_LEAK,
            "A connection leak in the nginx upstream module caused pool exhaustion. The HikariCP pool was not returning connections properly.",
        )
        incident3 = create_incident(
            "INC-2024-0003",
            "auth-service",
            FailureCategory.DEADLOCK,
            "A deadlock occurred in the PostgreSQL database when two transactions waited for each other's locks.",
        )

        # Add first incident
        self.dedup.add(incident1)

        # Check duplicate of first incident
        is_dup, dup_id, sim = self.dedup.is_duplicate(incident2)
        assert is_dup is True
        assert dup_id == "INC-2024-0001"
        assert sim > 0.8

        # Check different incident
        is_dup, dup_id, sim = self.dedup.is_duplicate(incident3)
        assert is_dup is False


class TestDiversityController:
    """Tests for DiversityController."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = DedupConfig(
            similarity_threshold=0.92,
            minhash_threshold=0.85,
            use_embeddings=True,
            use_minhash=True,
        )
        self.controller = DiversityController(self.config)

    def test_add_incident(self):
        """Test adding incidents to controller."""
        incident = create_incident(
            "INC-2024-0001",
            "api-gateway",
            FailureCategory.CONNECTION_LEAK,
            "A connection leak in the nginx upstream module caused pool exhaustion.",
        )

        self.controller.add(incident)

        assert self.controller.total_count == 1
        assert self.controller.category_counts["Connection Leak"] == 1

    def test_check_duplicate(self):
        """Test checking for duplicates."""
        incident1 = create_incident(
            "INC-2024-0001",
            "api-gateway",
            FailureCategory.CONNECTION_LEAK,
            "A connection leak in the nginx upstream module caused pool exhaustion.",
        )
        incident2 = create_incident(
            "INC-2024-0002",
            "api-gateway",
            FailureCategory.CONNECTION_LEAK,
            "A connection leak in the nginx upstream module caused pool exhaustion.",
        )

        self.controller.add(incident1)
        is_dup, dup_id, sim = self.controller.check_duplicate(incident2)

        assert is_dup is True
        assert dup_id == "INC-2024-0001"

    def test_check_category_balance(self):
        """Test category balance checking."""
        # Add 5 incidents of same category
        for i in range(5):
            incident = create_incident(
                f"INC-2024-{i:04d}",
                "api-gateway",
                FailureCategory.CONNECTION_LEAK,
                f"Connection leak incident number {i} with enough text to pass validation requirements.",
            )
            self.controller.add(incident)

        # Next incident of same category should exceed 20% (5/25 = 20%)
        # Actually 5/5 = 100%, so it should fail
        new_incident = create_incident(
            "INC-2024-0005",
            "api-gateway",
            FailureCategory.CONNECTION_LEAK,
            "Another connection leak incident.",
        )

        # With 5 existing, adding 1 more makes 6 total, category would be 6/6 = 100%
        # Max is 20%, so should fail
        balanced = self.controller.check_category_balance(new_incident, max_category_pct=0.20)
        assert balanced is False

        # Different category should pass
        different_incident = create_incident(
            "INC-2024-0006",
            "auth-service",
            FailureCategory.DEADLOCK,
            "Deadlock incident with different category.",
        )
        balanced = self.controller.check_category_balance(different_incident, max_category_pct=0.20)
        assert balanced is True

    def test_from_incidents_classmethod(self):
        """Test creating controller from existing incidents."""
        incidents = [
            create_incident(
                f"INC-2024-{i:04d}",
                "api-gateway",
                FailureCategory.CONNECTION_LEAK,
                f"Connection leak incident number {i}.",
            )
            for i in range(3)
        ]

        controller = DiversityController.from_incidents(incidents, self.config)

        assert controller.total_count == 3
        assert controller.category_counts["Connection Leak"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])