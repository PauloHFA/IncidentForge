"""IncidentForge - Synthetic post-mortem and chaos scenario generator."""

__version__ = "0.1.0"
__author__ = "IncidentForge Contributors"
__license__ = "MIT"

from .models import (
    Incident,
    Topology,
    FailureCatalog,
    Service,
    ServiceDependency,
    ServiceTechnology,
    ServiceSLO,
    FailureCategory,
    FailureTemplate,
    TimelineEvent,
    ActionItem,
    Severity,
    Priority,
    ArchitectureProfile,
    Language,
    Style,
    SLAImpact,
    IncidentMetadata,
    GenerationPlan,
    GenerationTask,
)

from .topology import TopologyLoader
from .failures import FailureCatalogLoader
from .planner import TaskPlanner, PlannerConfig
from .generator import IncidentGenerator, GeneratorConfig
from .validators import (
    ValidationResult,
    ValidationContext,
    SchemaValidator,
    SemanticValidator,
    SecurityValidator,
    MultiLayerValidator,
    create_validator,
    validate_incident,
)
from .dedup import DiversityController, DedupConfig
from .exporter import ExporterManager, export_incidents
from .report import QualityReporter, generate_report

__all__ = [
    "__version__",
    "Incident",
    "Topology",
    "FailureCatalog",
    "Service",
    "ServiceDependency",
    "ServiceTechnology",
    "ServiceSLO",
    "FailureCategory",
    "FailureTemplate",
    "TimelineEvent",
    "ActionItem",
    "Severity",
    "Priority",
    "ArchitectureProfile",
    "Language",
    "Style",
    "SLAImpact",
    "IncidentMetadata",
    "GenerationPlan",
    "GenerationTask",
    "TopologyLoader",
    "FailureCatalogLoader",
    "TaskPlanner",
    "PlanConfig",
    "IncidentGenerator",
    "GeneratorConfig",
    "ValidationPipeline",
    "ValidationConfig",
    "ValidationResult",
    "DiversityController",
    "DedupConfig",
    "Exporter",
    "ExportConfig",
    "QualityReporter",
    "generate_report",
]