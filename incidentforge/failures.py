"""Failure catalog loader for IncidentForge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import FailureCatalog, FailureTemplate, FailureCategory


class FailureCatalogLoader:
    """Loads and manages failure catalog from YAML files."""

    # Default catalog embedded in code (minimal subset for fallback)
    DEFAULT_CATALOG_YAML = """
version: "1.0"
failures:
  - category: "Connection Leak"
    name: "Database Connection Leak"
    description: "Application fails to return database connections to the pool, leading to pool exhaustion"
    applicable_technologies: ["PostgreSQL", "MySQL", "HikariCP", "pgBouncer"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 10
    max_duration_minutes: 120
    tags: ["database", "resource-exhaustion"]

  - category: "Deadlock"
    name: "Database Deadlock"
    description: "Circular wait condition between transactions causes deadlock, requiring victim selection and rollback"
    applicable_technologies: ["PostgreSQL", "MySQL", "SQL Server"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 5
    max_duration_minutes: 60
    tags: ["database", "concurrency"]

  - category: "Split-brain"
    name: "Database Split-brain"
    description: "Network partition causes multiple primaries in a replication cluster, leading to data divergence"
    applicable_technologies: ["PostgreSQL", "MySQL", "MongoDB", "Cassandra", "Redis Cluster"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 15
    max_duration_minutes: 240
    tags: ["database", "replication", "data-integrity"]

  - category: "OOMKilled"
    name: "Container OOMKilled"
    description: "Process exceeds memory limit, kernel kills container causing restart loop"
    applicable_technologies: ["Kubernetes", "Docker", "JVM", "Go", "Node.js", "Python"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 5
    max_duration_minutes: 60
    tags: ["compute", "memory", "kubernetes"]

  - category: "Cache Stampede"
    name: "Cache Stampede (Thundering Herd)"
    description: "Popular cache key expires, massive concurrent requests hit backend simultaneously"
    applicable_technologies: ["Redis", "Memcached", "Hazelcast", "Caffeine"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 5
    max_duration_minutes: 60
    tags: ["cache", "thundering-herd", "performance"]

  - category: "Message Queue Backlog"
    name: "Message Queue Backlog"
    description: "Consumers cannot keep up with producers, causing queue growth and processing delays"
    applicable_technologies: ["Kafka", "RabbitMQ", "AWS SQS", "Google Pub/Sub"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 15
    max_duration_minutes: 240
    tags: ["messaging", "backpressure", "performance"]

  - category: "Network Partition"
    name: "Network Partition"
    description: "Network split isolates subset of nodes, causing consistency issues in distributed systems"
    applicable_technologies: ["Kubernetes", "Consul", "etcd", "Cassandra"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 10
    max_duration_minutes: 180
    tags: ["network", "distributed-systems", "consistency"]

  - category: "Thread Pool Exhaustion"
    name: "Thread Pool Exhaustion"
    description: "All worker threads blocked on I/O or locks, new requests queue indefinitely"
    applicable_technologies: ["JVM", "Spring Boot", "Tomcat", "Netty", "Go", "Node.js"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 5
    max_duration_minutes: 90
    tags: ["compute", "concurrency", "threading"]

  - category: "Rollback Failure"
    name: "Automated Rollback Failure"
    description: "Deployment fails but automated rollback also fails, leaving system in broken state"
    applicable_technologies: ["Kubernetes", "ArgoCD", "Flux", "Helm", "Terraform"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 15
    max_duration_minutes: 120
    tags: ["deploy", "rollback", "gitops"]

  - category: "Config Drift"
    name: "Configuration Drift"
    description: "Runtime configuration diverges from source-controlled config, causing unexpected behavior"
    applicable_technologies: ["Kubernetes", "Consul", "etcd", "Spring Cloud Config"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 30
    max_duration_minutes: 240
    tags: ["deploy", "configuration", "gitops"]

  - category: "Replication Lag"
    name: "Excessive Replication Lag"
    description: "Replica falls significantly behind primary, causing stale reads and potential data loss on failover"
    applicable_technologies: ["PostgreSQL", "MySQL", "MongoDB", "Redis"]
    typical_severities: ["SEV-3", "SEV-4"]
    min_duration_minutes: 10
    max_duration_minutes: 180
    tags: ["database", "replication", "performance"]

  - category: "Query Timeout"
    name: "Long-running Query Timeout"
    description: "Unoptimized query or missing index causes query timeout, blocking other operations"
    applicable_technologies: ["PostgreSQL", "MySQL", "MongoDB"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 5
    max_duration_minutes: 90
    tags: ["database", "performance"]

  - category: "Pool Exhaustion"
    name: "Connection Pool Exhaustion"
    description: "All database connections in use, new requests queue or fail"
    applicable_technologies: ["PostgreSQL", "MySQL", "HikariCP", "pgBouncer"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 5
    max_duration_minutes: 60
    tags: ["database", "resource-exhaustion"]

  - category: "DNS Resolution Failure"
    name: "DNS Resolution Failure"
    description: "DNS queries fail or return stale records, preventing service discovery"
    applicable_technologies: ["CoreDNS", "Route53", "Consul", "etcd"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 5
    max_duration_minutes: 60
    tags: ["network", "dns", "service-discovery"]

  - category: "TLS Handshake Failure"
    name: "TLS Certificate/Handshake Failure"
    description: "Expired certificate, hostname mismatch, or cipher suite incompatibility breaks secure connections"
    applicable_technologies: ["nginx", "Envoy", "HAProxy", "cert-manager"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 5
    max_duration_minutes: 60
    tags: ["network", "security", "tls"]

  - category: "Load Balancer Misconfiguration"
    name: "Load Balancer Misconfiguration"
    description: "Incorrect health checks, routing rules, or target group configuration causes traffic blackholing"
    applicable_technologies: ["AWS ALB", "nginx", "Envoy", "HAProxy"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 5
    max_duration_minutes: 45
    tags: ["network", "load-balancing", "configuration"]

  - category: "Duplicate Message Processing"
    name: "Duplicate Message Processing"
    description: "At-least-once delivery without idempotency causes duplicate processing and data corruption"
    applicable_technologies: ["Kafka", "RabbitMQ", "AWS SQS"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 10
    max_duration_minutes: 120
    tags: ["messaging", "idempotency", "data-integrity"]

  - category: "Poison Message"
    name: "Poison Message"
    description: "Malformed or unprocessable message blocks queue processing, requiring manual intervention"
    applicable_technologies: ["Kafka", "RabbitMQ", "AWS SQS"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 15
    max_duration_minutes: 180
    tags: ["messaging", "data-quality", "operations"]

  - category: "Broker Unavailable"
    name: "Message Broker Unavailable"
    description: "Broker crash, OOM, or network issue makes messaging infrastructure unavailable"
    applicable_technologies: ["Kafka", "RabbitMQ", "Redis", "NATS"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 10
    max_duration_minutes: 120
    tags: ["messaging", "infrastructure", "availability"]

  - category: "CPU Throttling"
    name: "CPU Throttling"
    description: "Container exceeds CPU quota, CFS throttles causing latency spikes and timeouts"
    applicable_technologies: ["Kubernetes", "Docker", "JVM", "Go"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 10
    max_duration_minutes: 120
    tags: ["compute", "cpu", "kubernetes", "performance"]

  - category: "GC Pressure"
    name: "Garbage Collection Pressure"
    description: "Frequent/long GC pauses cause request timeouts and increased latency"
    applicable_technologies: ["JVM", "G1GC", "ZGC", "Go", ".NET"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 10
    max_duration_minutes: 120
    tags: ["compute", "memory", "gc", "performance"]

  - category: "Container Restart Loop"
    name: "Container Restart Loop (CrashLoopBackOff)"
    description: "Container repeatedly crashes on startup due to config error, missing dependency, or bug"
    applicable_technologies: ["Kubernetes", "Docker", "systemd"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 5
    max_duration_minutes: 60
    tags: ["compute", "kubernetes", "deployment"]

  - category: "Cache Miss Storm"
    name: "Cache Miss Storm"
    description: "Large-scale cache invalidation or cold start causes sustained high miss rate"
    applicable_technologies: ["Redis", "Memcached", "CDN", "Varnish"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 15
    max_duration_minutes: 180
    tags: ["cache", "invalidation", "capacity"]

  - category: "Stale Cache"
    name: "Stale Cache Data"
    description: "Cache not invalidated properly, serving outdated data to users"
    applicable_technologies: ["Redis", "Memcached", "CDN", "Hazelcast"]
    typical_severities: ["SEV-3", "SEV-4"]
    min_duration_minutes: 10
    max_duration_minutes: 240
    tags: ["cache", "data-integrity", "invalidation"]

  - category: "Canary Analysis Failure"
    name: "Canary Analysis Failure"
    description: "Canary deployment passes automated checks but has subtle regression detected post-deploy"
    applicable_technologies: ["Kubernetes", "Argo Rollouts", "Flagger", "Istio"]
    typical_severities: ["SEV-2", "SEV-3"]
    min_duration_minutes: 20
    max_duration_minutes: 180
    tags: ["deploy", "canary", "progressive-delivery"]

  - category: "Dependency Conflict"
    name: "Transitive Dependency Conflict"
    description: "Diamond dependency or version conflict causes runtime ClassNotFoundError/ModuleNotFoundError"
    applicable_technologies: ["Maven", "Gradle", "npm", "pip", "Cargo", "Go Modules"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 10
    max_duration_minutes: 90
    tags: ["deploy", "dependencies", "build"]

  - category: "Migration Failure"
    name: "Database Migration Failure"
    description: "Schema migration fails partway through, leaving database in inconsistent state"
    applicable_technologies: ["Flyway", "Liquibase", "Alembic", "Django Migrations"]
    typical_severities: ["SEV-1", "SEV-2"]
    min_duration_minutes: 15
    max_duration_minutes: 180
    tags: ["deploy", "database", "schema", "migration"]
"""

    def __init__(self):
        self._default_catalog: FailureCatalog | None = None

    @property
    def default_catalog(self) -> FailureCatalog:
        """Get the default failure catalog (lazy loaded)."""
        if self._default_catalog is None:
            self._default_catalog = self._load_default_catalog()
        return self._default_catalog

    def _load_default_catalog(self) -> FailureCatalog:
        """Load the embedded default catalog."""
        data = yaml.safe_load(self.DEFAULT_CATALOG_YAML)
        return FailureCatalog.model_validate(data)

    def load_from_file(self, path: str | Path) -> FailureCatalog:
        """
        Load failure catalog from YAML file.

        Args:
            path: Path to failures.yaml file.

        Returns:
            Validated FailureCatalog object.

        Raises:
            FileNotFoundError: If file doesn't exist.
            ValidationError: If catalog is invalid.
            ValueError: If YAML is malformed.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Failures file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise ValueError(f"Invalid YAML in {path}: {e}") from e

        if data is None:
            raise ValueError(f"Empty failures file: {path}")

        return FailureCatalog.model_validate(data)

    def merge_catalogs(
        self,
        user_catalog: FailureCatalog,
        mode: str = "extend"
    ) -> FailureCatalog:
        """
        Merge user catalog with default catalog.

        Args:
            user_catalog: User-provided catalog.
            mode: "extend" (default) adds user failures to default, "replace" uses only user catalog.

        Returns:
            Merged FailureCatalog.
        """
        if mode == "replace":
            return user_catalog

        # Extend mode: combine default + user, user overrides by category
        default_failures = {f.category: f for f in self.default_catalog.failures}
        user_failures = {f.category: f for f in user_catalog.failures}

        # User failures override defaults
        merged = {**default_failures, **user_failures}

        # Ensure we have at least 25 categories
        if len(merged) < 25:
            raise ValueError(
                f"Merged catalog has only {len(merged)} categories, minimum is 25"
            )

        return FailureCatalog(
            version=user_catalog.version or self.default_catalog.version,
            failures=list(merged.values())
        )

    def get_applicable_failures(
        self,
        catalog: FailureCatalog,
        technologies: list[str]
    ) -> list[FailureTemplate]:
        """
        Get failures applicable to the given technologies.

        Args:
            catalog: Failure catalog to filter.
            technologies: List of technology names from service topology.

        Returns:
            List of applicable failure templates.
        """
        tech_set = set(t.lower() for t in technologies)
        applicable = []

        for failure in catalog.failures:
            # Check if any applicable technology matches service technologies
            for app_tech in failure.applicable_technologies:
                if app_tech.lower() in tech_set:
                    applicable.append(failure)
                    break

        return applicable

    def filter_incompatible(
        self,
        failures: list[FailureTemplate],
        technologies: list[str]
    ) -> tuple[list[FailureTemplate], list[FailureTemplate]]:
        """
        Filter failures compatible with service technologies.

        Args:
            failures: List of failure templates to filter.
            technologies: List of technology names from service topology.

        Returns:
            Tuple of (compatible_failures, incompatible_failures).
        """
        tech_set = set(t.lower() for t in technologies)
        compatible = []
        incompatible = []

        for failure in failures:
            # Check if failure has at least one applicable technology in service
            has_match = any(
                app_tech.lower() in tech_set
                for app_tech in failure.applicable_technologies
            )
            if has_match:
                compatible.append(failure)
            else:
                incompatible.append(failure)

        return compatible, incompatible


def load_failure_catalog(
    path: str | Path | None = None,
    mode: str = "extend"
) -> FailureCatalog:
    """
    Convenience function to load failure catalog.

    Args:
        path: Optional path to user failures.yaml. If None, uses default.
        mode: "extend" (default) or "replace".

    Returns:
        Validated FailureCatalog object.
    """
    loader = FailureCatalogLoader()

    if path is None:
        return loader.default_catalog

    user_catalog = loader.load_from_file(path)
    return loader.merge_catalogs(user_catalog, mode)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        failures_path = sys.argv[1]
    else:
        failures_path = "configs/failures_default.yaml"

    try:
        catalog = load_failure_catalog(failures_path)
        print(f"[OK] Failure catalog loaded: {len(catalog.failures)} categories")

        # Show categories by type
        categories = {}
        for f in catalog.failures:
            cat = f.category
            if cat not in categories:
                categories[cat] = 0
            categories[cat] += 1

        print("\nCategories:")
        for cat, count in sorted(categories.items()):
            print(f"  {cat}: {count} templates")

    except Exception as e:
        print(f"[ERROR] Failed to load failure catalog: {e}")
        sys.exit(1)