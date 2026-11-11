"""Tests for topology loader."""

import pytest
import tempfile
from pathlib import Path

from incidentforge.topology import TopologyLoader
from incidentforge.models import Topology, Service, ServiceTechnology, ServiceSLO, ServiceDependency


class TestTopologyLoader:
    """Tests for TopologyLoader."""

    def create_sample_topology_yaml(self) -> str:
        """Create a sample topology YAML for testing."""
        import textwrap
        return textwrap.dedent("""\
            version: "1.0"
            services:
              - name: "api-gateway"
                technology:
                  - name: "nginx"
                    version: "1.24"
                    category: "network"
                  - name: "Go"
                    version: "1.21"
                    category: "compute"
                slo:
                  availability_target: 0.9995
                  latency_p99_ms: 100
                  throughput_rps: 10000
                dependencies:
                  - target: "auth-service"
                    traffic_percentage: 90.0
                    critical: true
                  - target: "rate-limit-cache"
                    traffic_percentage: 100.0
                    critical: false
                team: "platform-team"
                region: "us-east-1"
                replicas: 3
                language: "Go"
                framework: "gin"

              - name: "auth-service"
                technology:
                  - name: "PostgreSQL"
                    version: "15"
                    category: "database"
                  - name: "Redis"
                    version: "7"
                    category: "cache"
                  - name: "Python"
                    version: "3.11"
                    category: "compute"
                slo:
                  availability_target: 0.9999
                  latency_p99_ms: 50
                dependencies:
                  - target: "auth-db"
                    traffic_percentage: 100.0
                    critical: true
                team: "auth-team"
                region: "us-east-1"
                replicas: 2

              - name: "auth-db"
                technology:
                  - name: "PostgreSQL"
                    version: "15"
                    category: "database"
                slo:
                  availability_target: 0.9999
                  latency_p99_ms: 10
                team: "data-team"
                region: "us-east-1"
                replicas: 1

              - name: "rate-limit-cache"
                technology:
                  - name: "Redis"
                    version: "7"
                    category: "cache"
                slo:
                  availability_target: 0.9999
                  latency_p99_ms: 5
                team: "platform-team"
                region: "us-east-1"
                replicas: 2
            """)

    def test_load_valid_topology(self):
        """Test loading a valid topology from YAML."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(self.create_sample_topology_yaml())
            f.flush()
            path = Path(f.name)

        try:
            loader = TopologyLoader()
            topology = loader.load(path)

            assert isinstance(topology, Topology)
            assert topology.version == "1.0"
            assert len(topology.services) == 4

            # Check service names
            service_names = {s.name for s in topology.services}
            assert service_names == {"api-gateway", "auth-service", "auth-db", "rate-limit-cache"}

            # Check api-gateway
            api_gateway = topology.get_service("api-gateway")
            assert api_gateway is not None
            assert len(api_gateway.technology) == 2
            assert api_gateway.slo.availability_target == 0.9995
            assert len(api_gateway.dependencies) == 2

            # Check auth-service
            auth_service = topology.get_service("auth-service")
            assert auth_service is not None
            assert len(auth_service.dependencies) == 1

            # Check auth-db (no dependencies)
            auth_db = topology.get_service("auth-db")
            assert auth_db is not None
            assert len(auth_db.dependencies) == 0

        finally:
            path.unlink()

    def test_load_nonexistent_file(self):
        """Test loading a non-existent file raises FileNotFoundError."""
        loader = TopologyLoader()
        with pytest.raises(FileNotFoundError):
            loader.load("nonexistent.yaml")

    def test_load_invalid_yaml(self):
        """Test loading invalid YAML raises ValueError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: [")
            f.flush()
            path = Path(f.name)

        try:
            loader = TopologyLoader()
            with pytest.raises(ValueError, match="Invalid YAML"):
                loader.load(path)
        finally:
            path.unlink()

    def test_load_empty_yaml(self):
        """Test loading empty YAML raises ValidationError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("")
            f.flush()
            path = Path(f.name)

        try:
            loader = TopologyLoader()
            with pytest.raises(Exception):
                loader.load(path)
        finally:
            path.unlink()

    def test_load_duplicate_services(self):
        """Test loading topology with duplicate service names raises error."""
        yaml_content = """version: "1.0"
services:
  - name: "service-a"
    technology:
      - name: "nginx"
        version: "1.24"
        category: "network"
    slo:
      availability_target: 0.9995
      latency_p99_ms: 100
    team: "platform-team"
    region: "us-east-1"
    replicas: 1
  - name: "service-a"
    technology:
      - name: "nginx"
        version: "1.24"
        category: "network"
    slo:
      availability_target: 0.9995
      latency_p99_ms: 100
    team: "platform-team"
    region: "us-east-1"
    replicas: 1
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            loader = TopologyLoader()
            with pytest.raises(Exception):
                loader.load(path)
        finally:
            path.unlink()

    def test_load_invalid_dependency(self):
        """Test loading topology with invalid dependency raises error."""
        yaml_content = """version: "1.0"
services:
  - name: "service-a"
    technology:
      - name: "nginx"
        version: "1.24"
        category: "network"
    slo:
      availability_target: 0.9995
      latency_p99_ms: 100
    dependencies:
      - target: "nonexistent-service"
        traffic_percentage: 100.0
        critical: true
    team: "platform-team"
    region: "us-east-1"
    replicas: 1
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            loader = TopologyLoader()
            with pytest.raises(Exception, match="depends on non-existent service"):
                loader.load(path)
        finally:
            path.unlink()

    def test_strict_mode(self):
        """Test strict mode behavior."""
        # Valid topology should work in both modes
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(self.create_sample_topology_yaml())
            f.flush()
            path = Path(f.name)

        try:
            loader_strict = TopologyLoader(strict=True)
            topology = loader_strict.load(path)
            assert len(topology.services) == 4

            loader_non_strict = TopologyLoader(strict=False)
            topology = loader_non_strict.load(path)
            assert len(topology.services) == 4
        finally:
            path.unlink()

    def test_get_dependencies(self):
        """Test getting dependencies for a service."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(self.create_sample_topology_yaml())
            f.flush()
            path = Path(f.name)

        try:
            loader = TopologyLoader()
            topology = loader.load(path)

            deps = topology.get_dependencies("api-gateway")
            assert len(deps) == 2
            dep_targets = {d.target for d in deps}
            assert dep_targets == {"auth-service", "rate-limit-cache"}

            deps = topology.get_dependencies("auth-service")
            assert len(deps) == 1
            assert deps[0].target == "auth-db"

            # Service with no dependencies
            deps = topology.get_dependencies("auth-db")
            assert deps == []
        finally:
            path.unlink()

    def test_get_dependents(self):
        """Test getting services that depend on a given service."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(self.create_sample_topology_yaml())
            f.flush()
            path = Path(f.name)

        try:
            loader = TopologyLoader()
            topology = loader.load(path)

            dependents = topology.get_dependents("auth-service")
            assert len(dependents) == 1
            assert dependents[0].name == "api-gateway"

            dependents = topology.get_dependents("auth-db")
            assert len(dependents) == 1
            assert dependents[0].name == "auth-service"

            # Service with no dependents
            dependents = topology.get_dependents("api-gateway")
            assert dependents == []
        finally:
            path.unlink()

    def test_has_cycles(self):
        """Test cycle detection."""
        # No cycles
        import textwrap
        yaml_no_cycle = textwrap.dedent("""\
            version: "1.0"
            services:
              - name: "service-a"
                technology:
                  - name: "nginx"
                    version: "1.24"
                    category: "network"
                slo:
                  availability_target: 0.9995
                  latency_p99_ms: 100
                dependencies:
                  - target: "service-b"
                    traffic_percentage: 100.0
                    critical: true
                team: "platform-team"
                region: "us-east-1"
                replicas: 1
              - name: "service-b"
                technology:
                  - name: "nginx"
                    version: "1.24"
                    category: "network"
                slo:
                  availability_target: 0.9995
                  latency_p99_ms: 100
                team: "platform-team"
                region: "us-east-1"
                replicas: 1
            """)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_no_cycle)
            f.flush()
            path = Path(f.name)

        try:
            loader = TopologyLoader()
            topology = loader.load(path)
            assert topology.has_cycles() is False
        finally:
            path.unlink()

        # With cycle
        yaml_cycle = textwrap.dedent("""\
            version: "1.0"
            services:
              - name: "service-a"
                technology:
                  - name: "nginx"
                    version: "1.24"
                    category: "network"
                slo:
                  availability_target: 0.9995
                  latency_p99_ms: 100
                dependencies:
                  - target: "service-b"
                    traffic_percentage: 100.0
                    critical: true
                team: "platform-team"
                region: "us-east-1"
                replicas: 1
              - name: "service-b"
                technology:
                  - name: "nginx"
                    version: "1.24"
                    category: "network"
                slo:
                  availability_target: 0.9995
                  latency_p99_ms: 100
                dependencies:
                  - target: "service-a"
                    traffic_percentage: 100.0
                    critical: true
                team: "platform-team"
                region: "us-east-1"
                replicas: 1
            """)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_cycle)
            f.flush()
            path = Path(f.name)

        try:
            loader = TopologyLoader()
            topology = loader.load(path)
            assert topology.has_cycles() is True
        finally:
            path.unlink()