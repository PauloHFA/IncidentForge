"""Semantic deduplication for IncidentForge."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
from datasketch import MinHash, MinHashLSH
from sentence_transformers import SentenceTransformer

from .models import Incident


@dataclass
class DedupConfig:
    """Configuration for deduplication."""

    similarity_threshold: float = 0.92  # Cosine similarity threshold
    minhash_threshold: float = 0.85  # Jaccard similarity threshold
    num_perm: int = 128  # MinHash permutations
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    use_embeddings: bool = True
    use_minhash: bool = True


class EmbeddingDeduplicator:
    """Deduplication using sentence embeddings and cosine similarity."""

    def __init__(self, config: DedupConfig):
        self.config = config
        self._model: SentenceTransformer | None = None
        self._embeddings: dict[str, np.ndarray] = {}  # incident_id -> embedding
        self._texts: dict[str, str] = {}  # incident_id -> text for embedding

    @property
    def model(self) -> SentenceTransformer:
        """Lazy-load embedding model."""
        if self._model is None:
            self._model = SentenceTransformer(self.config.embedding_model)
        return self._model

    def _get_incident_text(self, incident: Incident) -> str:
        """Get representative text for incident embedding."""
        parts = [
            incident.service,
            incident.failure_category.value,
            incident.root_cause_analysis,
            " ".join(e.event for e in incident.timeline),
            " ".join(item.action for item in incident.action_items),
        ]
        return " | ".join(parts)

    def add(self, incident: Incident) -> None:
        """Add incident to deduplication index."""
        if not self.config.use_embeddings:
            return

        text = self._get_incident_text(incident)
        self._texts[incident.id] = text
        embedding = self.model.encode(text, normalize_embeddings=True)
        self._embeddings[incident.id] = embedding

    def is_duplicate(self, incident: Incident) -> tuple[bool, str | None, float]:
        """
        Check if incident is a duplicate of any existing.

        Returns:
            Tuple of (is_duplicate, duplicate_id, similarity_score).
        """
        if not self.config.use_embeddings or not self._embeddings:
            return False, None, 0.0

        text = self._get_incident_text(incident)
        embedding = self.model.encode(text, normalize_embeddings=True)

        max_similarity = 0.0
        duplicate_id = None

        for existing_id, existing_embedding in self._embeddings.items():
            similarity = float(np.dot(embedding, existing_embedding))
            if similarity > max_similarity:
                max_similarity = similarity
                duplicate_id = existing_id

        is_dup = max_similarity >= self.config.similarity_threshold
        return is_dup, duplicate_id, max_similarity

    def get_similar(self, incident: Incident, top_k: int = 5) -> list[tuple[str, float]]:
        """Get top-k most similar incidents."""
        if not self.config.use_embeddings or not self._embeddings:
            return []

        text = self._get_incident_text(incident)
        embedding = self.model.encode(text, normalize_embeddings=True)

        similarities = []
        for existing_id, existing_embedding in self._embeddings.items():
            similarity = float(np.dot(embedding, existing_embedding))
            similarities.append((existing_id, similarity))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]


class MinHashDeduplicator:
    """Deduplication using MinHash LSH for approximate Jaccard similarity."""

    def __init__(self, config: DedupConfig):
        self.config = config
        self._lsh: MinHashLSH | None = None
        self._minhashes: dict[str, MinHash] = {}

    def _get_minhash(self, incident: Incident) -> MinHash:
        """Create MinHash for incident."""
        m = MinHash(num_perm=self.config.num_perm)

        # Create shingles from incident text
        text = self._get_incident_text(incident)
        shingles = self._get_shingles(text)

        for shingle in shingles:
            m.update(shingle.encode("utf-8"))

        return m

    def _get_shingles(self, text: str, k: int = 5) -> set[str]:
        """Generate k-shingles from text."""
        text = text.lower()
        words = text.split()
        shingles = set()

        for i in range(len(words) - k + 1):
            shingle = " ".join(words[i:i + k])
            shingles.add(shingle)

        return shingles

    def _get_incident_text(self, incident: Incident) -> str:
        """Get representative text for MinHash."""
        parts = [
            incident.service,
            incident.failure_category.value,
            incident.root_cause_analysis,
            " ".join(e.event for e in incident.timeline),
            " ".join(item.action for item in incident.action_items),
        ]
        return " | ".join(parts)

    def add(self, incident: Incident) -> None:
        """Add incident to LSH index."""
        if not self.config.use_minhash:
            return

        if self._lsh is None:
            self._lsh = MinHashLSH(
                threshold=self.config.minhash_threshold,
                num_perm=self.config.num_perm,
            )

        minhash = self._get_minhash(incident)
        self._minhashes[incident.id] = minhash
        self._lsh.insert(incident.id, minhash)

    def is_duplicate(self, incident: Incident) -> tuple[bool, str | None, float]:
        """
        Check if incident is a duplicate using MinHash LSH.

        Returns:
            Tuple of (is_duplicate, duplicate_id, estimated_jaccard).
        """
        if not self.config.use_minhash or self._lsh is None:
            return False, None, 0.0

        minhash = self._get_minhash(incident)
        candidates = self._lsh.query(minhash)

        if not candidates:
            return False, None, 0.0

        # Compute actual Jaccard with candidates
        max_jaccard = 0.0
        duplicate_id = None

        for candidate_id in candidates:
            if candidate_id == incident.id:
                continue
            candidate_minhash = self._minhashes.get(candidate_id)
            if candidate_minhash:
                jaccard = minhash.jaccard(candidate_minhash)
                if jaccard > max_jaccard:
                    max_jaccard = jaccard
                    duplicate_id = candidate_id

        is_dup = max_jaccard >= self.config.minhash_threshold
        return is_dup, duplicate_id, max_jaccard


class DiversityController:
    """Controls diversity of generated incidents."""

    def __init__(self, config: DedupConfig):
        self.config = config
        self.embedding_dedup = EmbeddingDeduplicator(config)
        self.minhash_dedup = MinHashDeduplicator(config)
        self.category_counts: dict[str, int] = {}
        self.total_count = 0

    @classmethod
    def from_incidents(cls, incidents: list[Incident], config: DedupConfig | None = None) -> DiversityController:
        """Create controller from existing incidents."""
        if config is None:
            config = DedupConfig()
        controller = cls(config)
        for incident in incidents:
            controller.add(incident)
        return controller

    def add(self, incident: Incident) -> None:
        """Add incident to diversity tracking."""
        self.embedding_dedup.add(incident)
        self.minhash_dedup.add(incident)

        cat = incident.failure_category.value
        self.category_counts[cat] = self.category_counts.get(cat, 0) + 1
        self.total_count += 1

    def check_duplicate(self, incident: Incident) -> tuple[bool, str | None, float]:
        """
        Check if incident is duplicate using both methods.

        Returns:
            Tuple of (is_duplicate, duplicate_id, max_similarity).
        """
        # Check embeddings
        emb_dup, emb_id, emb_sim = self.embedding_dedup.is_duplicate(incident)
        if emb_dup:
            return True, emb_id, emb_sim

        # Check MinHash
        mh_dup, mh_id, mh_sim = self.minhash_dedup.is_duplicate(incident)
        if mh_dup:
            return True, mh_id, mh_sim

        return False, None, max(emb_sim, mh_sim)

    def check_category_balance(self, incident: Incident, max_category_pct: float = 0.20) -> bool:
        """
        Check if adding this incident would exceed category balance.

        Args:
            incident: Incident to check.
            max_category_pct: Maximum percentage for any category (default 20%).

        Returns:
            True if adding would maintain balance, False otherwise.
        """
        if self.total_count == 0:
            return True

        cat = incident.failure_category.value
        current_count = self.category_counts.get(cat, 0)
        new_count = current_count + 1
        new_total = self.total_count + 1

        return (new_count / new_total) <= max_category_pct

    def get_category_distribution(self) -> dict[str, float]:
        """Get current category distribution as percentages."""
        if self.total_count == 0:
            return {}

        return {
            cat: count / self.total_count
            for cat, count in self.category_counts.items()
        }

    def get_stats(self) -> dict[str, Any]:
        """Get deduplication statistics."""
        return {
            "total_incidents": self.total_count,
            "unique_categories": len(self.category_counts),
            "category_distribution": self.get_category_distribution(),
            "embedding_index_size": len(self.embedding_dedup._embeddings),
            "minhash_index_size": len(self.minhash_dedup._minhashes),
        }


def create_dedup_controller(config: DedupConfig | None = None) -> DiversityController:
    """Create a diversity controller with default or custom config."""
    if config is None:
        config = DedupConfig()
    return DiversityController(config)


if __name__ == "__main__":
    # Test deduplication
    from .models import (
        Incident, TimelineEvent, SLAImpact, ActionItem, IncidentMetadata,
        Severity, FailureCategory, Priority, Language, Style, ArchitectureProfile
    )

    config = DedupConfig(
        similarity_threshold=0.92,
        use_embeddings=True,
        use_minhash=True,
    )

    controller = create_dedup_controller(config)

    # Create test incidents
    base_incident = Incident(
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

    # Add first incident
    controller.add(base_incident)
    print(f"Added first incident: {base_incident.id}")

    # Create similar incident (should be detected as duplicate)
    similar_incident = Incident(
        id="INC-2024-0002",
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
            seed=43,
            generated_at="2024-01-15T11:00:00Z",
            schema_version="1.0",
            synthetic=True,
        ),
    )

    is_dup, dup_id, sim = controller.check_duplicate(similar_incident)
    print(f"Similar incident duplicate check: {is_dup} (id: {dup_id}, similarity: {sim:.4f})")

    # Create different incident
    different_incident = Incident(
        id="INC-2024-0003",
        service="auth-service",
        severity=Severity.SEV_1,
        outage_duration_minutes=45,
        failure_category=FailureCategory.DEADLOCK,
        sla_impact=SLAImpact(
            availability_before=0.9995,
            availability_after=0.9900,
            p99_latency_ms=10000,
        ),
        root_cause_analysis="A database deadlock occurred in PostgreSQL when multiple transactions tried to update the same rows in different order. The Spring Boot application using HikariCP experienced transaction rollbacks.",
        timeline=[
            TimelineEvent(timestamp="2024-01-15T14:00:00Z", event="Deadlock detected in PostgreSQL logs", source="postgresql", severity=Severity.SEV_3),
            TimelineEvent(timestamp="2024-01-15T14:10:00Z", event="Auth service latency spikes", source="auth-service", severity=Severity.SEV_2),
            TimelineEvent(timestamp="2024-01-15T14:20:00Z", event="Cascading failures to api-gateway", source="api-gateway", severity=Severity.SEV_1),
            TimelineEvent(timestamp="2024-01-15T14:35:00Z", event="Manual intervention to kill blocking queries", source="postgresql", severity=Severity.SEV_2),
            TimelineEvent(timestamp="2024-01-15T14:45:00Z", event="Service recovered", source="auth-service", severity=Severity.SEV_4),
        ],
        action_items=[
            ActionItem(action="Add deadlock detection and retry logic", owner="identity-team", priority=Priority.P0),
            ActionItem(action="Review transaction ordering in user service", owner="identity-team", priority=Priority.P1),
            ActionItem(action="Add database lock monitoring", owner="data-team", priority=Priority.P2),
        ],
        metadata=IncidentMetadata(
            model="gpt-4o-mini",
            prompt_version="1.0",
            seed=44,
            generated_at="2024-01-15T15:00:00Z",
            schema_version="1.0",
            synthetic=True,
        ),
    )

    is_dup, dup_id, sim = controller.check_duplicate(different_incident)
    print(f"Different incident duplicate check: {is_dup} (id: {dup_id}, similarity: {sim:.4f})")

    controller.add(different_incident)
    print(f"Stats: {controller.get_stats()}")