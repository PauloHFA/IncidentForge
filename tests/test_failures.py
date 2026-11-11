"""Tests for failure catalog loader."""

import pytest
import tempfile
from pathlib import Path

from incidentforge.failures import FailureCatalogLoader, load_failure_catalog
from incidentforge.models import FailureCatalog, FailureTemplate, FailureCategory, Severity


class TestFailureCatalogLoader:
    """Tests for FailureCatalogLoader."""

    def create_sample_failures_yaml(self) -> str:
        """Create a sample failures YAML for testing with 25+ failures."""
        # Create 25 failures by repeating categories with different technologies
        categories = [
            ("Connection Leak", "Database Connection Leak", "Application fails to return database connections to the pool", ["PostgreSQL", "MySQL", "HikariCP", "pgBouncer"], ["SEV-2", "SEV-3"], 10, 120, ["database", "resource-exhaustion"]),
            ("Deadlock", "Database Deadlock", "Circular wait condition between transactions", ["PostgreSQL", "MySQL", "SQL Server"], ["SEV-2", "SEV-3"], 5, 60, ["database", "concurrency"]),
            ("Split-brain", "Database Split-brain", "Network partition causes multiple primaries", ["PostgreSQL", "MySQL", "MongoDB", "Cassandra", "Redis Cluster"], ["SEV-1", "SEV-2"], 15, 240, ["database", "replication", "data-integrity"]),
            ("Replication Lag", "Excessive Replication Lag", "Replica falls significantly behind primary", ["PostgreSQL", "MySQL", "MongoDB", "Cassandra", "Redis"], ["SEV-3", "SEV-4"], 10, 180, ["database", "replication", "performance"]),
            ("Query Timeout", "Long-running Query Timeout", "Unoptimized query or missing index causes timeout", ["PostgreSQL", "MySQL", "SQL Server", "Oracle", "MongoDB"], ["SEV-2", "SEV-3"], 5, 90, ["database", "performance"]),
            ("Pool Exhaustion", "Connection Pool Exhaustion", "All connections in pool are in use", ["PostgreSQL", "MySQL", "HikariCP", "pgBouncer"], ["SEV-2", "SEV-3"], 5, 60, ["database", "resource-exhaustion"]),
            ("Schema Mismatch", "Schema Mismatch", "Application schema doesn't match database schema", ["PostgreSQL", "MySQL", "MongoDB"], ["SEV-2", "SEV-3"], 10, 120, ["database", "schema"]),
            ("Vacuum Blocking", "Vacuum Blocking", "Long-running vacuum blocks writes", ["PostgreSQL"], ["SEV-3", "SEV-4"], 30, 360, ["database", "maintenance"]),
            ("DNS Resolution Failure", "DNS Resolution Failure", "DNS lookup fails for service discovery", ["Kubernetes", "Consul", "etcd", "AWS Route53"], ["SEV-2", "SEV-3"], 5, 60, ["network", "dns"]),
            ("Network Partition", "Network Partition", "Network split isolates cluster nodes", ["Kubernetes", "Cassandra", "Redis Cluster", "MongoDB"], ["SEV-1", "SEV-2"], 10, 180, ["network", "partition"]),
            ("Bandwidth Saturation", "Bandwidth Saturation", "Network link saturated causing packet loss", ["Kubernetes", "AWS", "GCP", "Azure"], ["SEV-2", "SEV-3"], 15, 120, ["network", "bandwidth"]),
            ("TLS Handshake Failure", "TLS Handshake Failure", "Certificate validation or handshake fails", ["nginx", "Envoy", "AWS ALB", "Kubernetes Ingress"], ["SEV-2", "SEV-3"], 5, 30, ["network", "tls"]),
            ("Load Balancer Misconfiguration", "Load Balancer Misconfiguration", "Incorrect load balancer routing rules", ["nginx", "Envoy", "AWS ALB", "HAProxy"], ["SEV-2", "SEV-3"], 10, 60, ["network", "load-balancer"]),
            ("Message Queue Backlog", "Message Queue Backlog", "Messages accumulate faster than consumers process", ["Kafka", "RabbitMQ", "AWS SQS", "Google Pub/Sub"], ["SEV-2", "SEV-3"], 15, 180, ["messaging", "backlog"]),
            ("Duplicate Message Processing", "Duplicate Message Processing", "Same message processed multiple times", ["Kafka", "RabbitMQ", "AWS SQS"], ["SEV-2", "SEV-3"], 10, 120, ["messaging", "duplication"]),
            ("Poison Message", "Poison Message", "Malformed message blocks queue processing", ["Kafka", "RabbitMQ", "AWS SQS"], ["SEV-2", "SEV-3"], 5, 60, ["messaging", "poison"]),
            ("Broker Unavailable", "Broker Unavailable", "Message broker becomes unreachable", ["Kafka", "RabbitMQ", "AWS SQS", "Google Pub/Sub"], ["SEV-1", "SEV-2"], 10, 120, ["messaging", "broker"]),
            ("Consumer Lag", "Consumer Lag", "Consumers fall behind producers", ["Kafka", "RabbitMQ", "AWS SQS"], ["SEV-3", "SEV-4"], 15, 180, ["messaging", "lag"]),
            ("OOMKilled", "Container OOMKilled", "Process exceeds memory limit, kernel kills container", ["Kubernetes", "Docker", "JVM", "Go", "Node.js", "Python"], ["SEV-1", "SEV-2"], 5, 60, ["compute", "memory", "kubernetes"]),
            ("CPU Throttling", "CPU Throttling", "Container CPU quota exceeded", ["Kubernetes", "Docker", "AWS Fargate"], ["SEV-3", "SEV-4"], 10, 120, ["compute", "cpu"]),
            ("Thread Pool Exhaustion", "Thread Pool Exhaustion", "All threads busy, requests queue up", ["Java", "Go", "Python", "Node.js"], ["SEV-2", "SEV-3"], 5, 60, ["compute", "threads"]),
            ("GC Pressure", "GC Pressure", "Garbage collector runs too frequently", ["JVM", "Go", "Node.js", "Python"], ["SEV-3", "SEV-4"], 10, 120, ["compute", "gc"]),
            ("Container Restart Loop", "Container Restart Loop", "Container crashes and restarts repeatedly", ["Kubernetes", "Docker"], ["SEV-1", "SEV-2"], 5, 60, ["compute", "kubernetes"]),
            ("Cache Stampede", "Cache Stampede (Thundering Herd)", "Popular cache key expires, massive concurrent requests", ["Redis", "Memcached", "Hazelcast", "Caffeine"], ["SEV-1", "SEV-2"], 5, 60, ["cache", "thundering-herd", "performance"]),
            ("Cache Miss Storm", "Cache Miss Storm", "Sudden surge of cache misses overwhelms backend", ["Redis", "Memcached", "Caffeine"], ["SEV-2", "SEV-3"], 10, 120, ["cache", "miss-storm"]),
            ("Cache Eviction Storm", "Cache Eviction Storm", "Mass invalidation causes backend overload", ["Redis", "Memcached", "CDN"], ["SEV-2", "SEV-3"], 10, 120, ["cache", "invalidation"]),
        ]

        failures_yaml = []
        for i, (cat, name, desc, techs, sevs, min_dur, max_dur, tags) in enumerate(categories):
            failures_yaml.append(f"""  - category: "{cat}"
    name: "{name} {i+1}"
    description: "{desc}"
    applicable_technologies: {techs}
    typical_severities: {sevs}
    min_duration_minutes: {min_dur}
    max_duration_minutes: {max_dur}
    tags: {tags}""")

        return "version: \"1.0\"\nfailures:\n" + "\n".join(failures_yaml)

    def test_load_valid_catalog(self):
        """Test loading a valid failure catalog from YAML."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(self.create_sample_failures_yaml())
            f.flush()
            path = Path(f.name)

        try:
            loader = FailureCatalogLoader()
            catalog = loader.load_from_file(path)

            assert isinstance(catalog, FailureCatalog)
            assert catalog.version == "1.0"
            assert len(catalog.failures) == 26

            # Check categories
            categories = {f.category for f in catalog.failures}
            assert FailureCategory.CONNECTION_LEAK in categories
            assert FailureCategory.DEADLOCK in categories
            assert FailureCategory.OOM_KILLED in categories
            assert FailureCategory.CACHE_STAMPEDE in categories

        finally:
            path.unlink()

    def test_load_nonexistent_file(self):
        """Test loading a non-existent file raises FileNotFoundError."""
        loader = FailureCatalogLoader()
        with pytest.raises(FileNotFoundError):
            loader.load_from_file("nonexistent.yaml")

    def test_load_invalid_yaml(self):
        """Test loading invalid YAML raises ValueError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: [")
            f.flush()
            path = Path(f.name)

        try:
            loader = FailureCatalogLoader()
            with pytest.raises(ValueError):
                loader.load_from_file(path)
        finally:
            path.unlink()

    def test_load_empty_yaml(self):
        """Test loading empty YAML raises ValueError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("")
            f.flush()
            path = Path(f.name)

        try:
            loader = FailureCatalogLoader()
            with pytest.raises(ValueError):
                loader.load_from_file(path)
        finally:
            path.unlink()

    def test_default_catalog(self):
        """Test loading the default catalog."""
        loader = FailureCatalogLoader()
        catalog = loader.default_catalog

        assert isinstance(catalog, FailureCatalog)
        assert len(catalog.failures) >= 25
        categories = {f.category for f in catalog.failures}
        assert FailureCategory.CONNECTION_LEAK in categories
        assert FailureCategory.DEADLOCK in categories
        assert FailureCategory.OOM_KILLED in categories
        assert FailureCategory.CACHE_STAMPEDE in categories

    def test_get_applicable_failures(self):
        """Test filtering failures by technology."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(self.create_sample_failures_yaml())
            f.flush()
            path = Path(f.name)

        try:
            loader = FailureCatalogLoader()
            catalog = loader.load_from_file(path)

            # Filter for PostgreSQL
            pg_failures = catalog.get_applicable_failures(["PostgreSQL"])
            assert len(pg_failures) > 0
            for failure in pg_failures:
                assert "PostgreSQL" in failure.applicable_technologies

            # Filter for Kubernetes
            k8s_failures = catalog.get_applicable_failures(["Kubernetes"])
            assert len(k8s_failures) > 0
            for failure in k8s_failures:
                assert "Kubernetes" in failure.applicable_technologies

            # Filter for non-existent technology
            none_failures = catalog.get_applicable_failures(["NonExistentTech"])
            assert len(none_failures) == 0

        finally:
            path.unlink()

    def test_merge_catalogs_extend(self):
        """Test merging catalogs in extend mode."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f1:
            f1.write(self.create_sample_failures_yaml())
            f1.flush()
            path1 = Path(f1.name)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f2:
            # Create a smaller catalog with different categories (25+ failures)
            small_yaml = self.create_sample_failures_yaml()
                # Modify one failure to have a unique category (use Config Drift which is in the enum)
            small_yaml = small_yaml.replace(
                'category: "Connection Leak"',
                    'category: "Config Drift"'
            ).replace(
                'name: "Database Connection Leak 1"',
                'name: "Custom Test Failure"'
            ).replace(
                'applicable_technologies: ["PostgreSQL", "MySQL", "HikariCP", "pgBouncer"]',
                'applicable_technologies: ["CustomTech"]'
            )
            f2.write(small_yaml)
            f2.flush()
            path2 = Path(f2.name)

        try:
            loader = FailureCatalogLoader()
            catalog1 = loader.load_from_file(path1)
            catalog2 = loader.load_from_file(path2)

            merged = loader.merge_catalogs(catalog2, mode="extend")
            # Default has 32, user has 26, some overlap -> expect ~32-38
            assert len(merged.failures) >= 32
            categories = {f.category for f in merged.failures}
            assert FailureCategory.CONNECTION_LEAK in categories
            assert FailureCategory.CONFIG_DRIFT in categories

        finally:
            path1.unlink()
            path2.unlink()

    def test_merge_catalogs_replace(self):
        """Test merging catalogs in replace mode."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f1:
            f1.write(self.create_sample_failures_yaml())
            f1.flush()
            path1 = Path(f1.name)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f2:
            # Create a valid catalog with 25+ failures for replace mode
            small_yaml = self.create_sample_failures_yaml()
                # Modify one failure to have a unique category (use Config Drift which is in the enum)
            small_yaml = small_yaml.replace(
                'category: "Connection Leak"',
                    'category: "Config Drift"'
            ).replace(
                'name: "Database Connection Leak 1"',
                'name: "Custom Test Failure"'
            ).replace(
                'applicable_technologies: ["PostgreSQL", "MySQL", "HikariCP", "pgBouncer"]',
                'applicable_technologies: ["CustomTech"]'
            )
            f2.write(small_yaml)
            f2.flush()
            path2 = Path(f2.name)

        try:
            loader = FailureCatalogLoader()
            catalog1 = loader.load_from_file(path1)
            catalog2 = loader.load_from_file(path2)

            merged = loader.merge_catalogs(catalog2, mode="replace")
            # Replace mode uses only user catalog (26 failures)
            assert len(merged.failures) == 26
            categories = {f.category for f in merged.failures}
            assert FailureCategory.CONFIG_DRIFT in categories

        finally:
            path1.unlink()
            path2.unlink()

    def test_merge_catalogs_minimum_categories(self):
        """Test that merged catalog maintains minimum 25 categories."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f1:
            f1.write(self.create_sample_failures_yaml())
            f1.flush()
            path1 = Path(f1.name)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f2:
            # Create a valid catalog with 25+ failures
            small_yaml = self.create_sample_failures_yaml()
                # Modify one failure to have a unique category (use Config Drift which is in the enum)
            small_yaml = small_yaml.replace(
                'category: "Connection Leak"',
                    'category: "Config Drift"'
            ).replace(
                'name: "Database Connection Leak 1"',
                'name: "Custom Test Failure"'
            ).replace(
                'applicable_technologies: ["PostgreSQL", "MySQL", "HikariCP", "pgBouncer"]',
                'applicable_technologies: ["CustomTech"]'
            )
            f2.write(small_yaml)
            f2.flush()
            path2 = Path(f2.name)

        try:
            loader = FailureCatalogLoader()
            catalog1 = loader.load_from_file(path1)
            catalog2 = loader.load_from_file(path2)

                    # Extend mode should have 32+ (default 32 + user 26 - overlap)
            merged_extend = loader.merge_catalogs(catalog2, mode="extend")
            assert len(merged_extend.failures) >= 32

            # Replace mode should have 26 (the replacement catalog)
            merged_replace = loader.merge_catalogs(catalog2, mode="replace")
            assert len(merged_replace.failures) == 26

        finally:
            path1.unlink()
            path2.unlink()

    def test_load_failure_catalog_convenience(self):
        """Test the convenience function load_failure_catalog."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(self.create_sample_failures_yaml())
            f.flush()
            path = Path(f.name)

        try:
            catalog = load_failure_catalog(path)
            assert isinstance(catalog, FailureCatalog)
            # load_failure_catalog merges with default catalog in extend mode
            # Our sample has 26 failures, default has 32, but some overlap
            assert len(catalog.failures) >= 26
        finally:
            path.unlink()