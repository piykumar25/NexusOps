"""
NexusOps Event Schema Registry
================================
Canonical event schemas for the entire event-driven pipeline.
Every event flowing through Kafka MUST conform to one of these schemas.
This is the single source of truth for event structure across all services.
"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional
from datetime import datetime
from enum import Enum
import uuid


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertSource(str, Enum):
    PAGERDUTY = "pagerduty"
    PROMETHEUS = "prometheus_alertmanager"
    GRAFANA = "grafana"
    CLOUDWATCH = "cloudwatch"
    DATADOG = "datadog"
    CUSTOM = "custom"


class IncidentStatus(str, Enum):
    RECEIVED = "received"
    PREPROCESSING = "preprocessing"
    ENRICHING = "enriching"
    TRIAGING = "triaging"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    FAILED = "failed"


class NexusEvent(BaseModel):
    """Base event envelope for all NexusOps events."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    source: str = "nexusops"
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IncidentAlertEvent(NexusEvent):
    """
    Canonical event published when an external alert is ingested.
    This is the entry point for the entire triage pipeline.
    """
    event_type: str = "incident.alert.received"
    alert_name: str
    severity: Severity
    source_system: AlertSource
    affected_service: str
    affected_namespace: str = "default"
    description: str
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: Optional[str] = None


class TriageUpdateEvent(NexusEvent):
    """
    Published at each stage of the triage pipeline so the UI
    can render real-time progress to the operator.
    """
    event_type: str = "incident.triage.update"
    incident_id: str
    status: IncidentStatus
    stage_name: str
    stage_output: str = ""
    confidence: Optional[str] = None
    elapsed_seconds: float = 0.0


class TriageResultEvent(NexusEvent):
    """
    Final output of the automated triage pipeline.
    Contains the root cause hypothesis, evidence, and recommended actions.
    """
    event_type: str = "incident.triage.result"
    incident_id: str
    root_cause_hypothesis: str
    confidence: str = "medium"
    evidence: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    specialists_consulted: List[str] = Field(default_factory=list)
    total_elapsed_seconds: float = 0.0
