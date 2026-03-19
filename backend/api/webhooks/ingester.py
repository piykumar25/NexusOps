"""
NexusOps Webhook Ingester
==========================
FastAPI router that receives webhook payloads from external alerting systems
(PagerDuty, Prometheus Alertmanager, Grafana, CloudWatch, etc.) and normalizes
them into canonical IncidentAlertEvent objects before publishing to Kafka.

This is the "front door" of the entire event-driven triage pipeline.

Design decisions:
  - Each alerting source gets its own adapter function (Strategy pattern)
  - Raw payload is always preserved for audit trail
  - Fingerprinting prevents duplicate incident creation
  - Health check endpoint for load balancer probes
"""

import hashlib
import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel

from backend.core.events.schemas import (
    AlertSource,
    IncidentAlertEvent,
    Severity,
)
from backend.core.events.kafka_infra import KafkaConfig, NexusKafkaProducer

logger = logging.getLogger("nexusops.webhooks")

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhook Ingestion"])

# Lazy-initialized producer (set during app startup)
_producer: NexusKafkaProducer = None
INCIDENT_ALERTS_TOPIC = "incident-alerts"


def init_webhook_producer(kafka_config: KafkaConfig):
    """Called once during FastAPI lifespan startup."""
    global _producer
    _producer = NexusKafkaProducer(kafka_config)
    logger.info("Webhook Kafka producer initialized.")


def _generate_fingerprint(alert_name: str, service: str, labels: Dict) -> str:
    """
    Generate a deterministic fingerprint for deduplication.
    Same alert + service + label combination = same fingerprint.
    """
    raw = f"{alert_name}:{service}:{json.dumps(labels, sort_keys=True)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ─── Adapter: Prometheus Alertmanager ────────────────────────────────────────

def _adapt_prometheus(payload: Dict[str, Any]) -> list[IncidentAlertEvent]:
    """
    Prometheus Alertmanager sends arrays of alerts in its webhook payload.
    See: https://prometheus.io/docs/alerting/latest/configuration/#webhook_config
    """
    events = []
    for alert in payload.get("alerts", []):
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})

        severity_map = {"critical": Severity.CRITICAL, "warning": Severity.HIGH, "info": Severity.INFO}
        severity = severity_map.get(labels.get("severity", "").lower(), Severity.MEDIUM)

        event = IncidentAlertEvent(
            alert_name=labels.get("alertname", "UnknownAlert"),
            severity=severity,
            source_system=AlertSource.PROMETHEUS,
            affected_service=labels.get("service", labels.get("job", "unknown")),
            affected_namespace=labels.get("namespace", "default"),
            description=annotations.get("summary", annotations.get("description", "No description")),
            labels=labels,
            annotations=annotations,
            raw_payload=alert,
            fingerprint=_generate_fingerprint(
                labels.get("alertname", ""), labels.get("service", ""), labels
            ),
        )
        events.append(event)
    return events


# ─── Adapter: PagerDuty ─────────────────────────────────────────────────────

def _adapt_pagerduty(payload: Dict[str, Any]) -> list[IncidentAlertEvent]:
    """
    PagerDuty V2 webhook events.
    See: https://developer.pagerduty.com/docs/db0fa8c8984fc-overview
    """
    events = []
    for message in payload.get("messages", [payload]):
        incident = message.get("incident", message)

        urgency = incident.get("urgency", "low")
        severity = Severity.CRITICAL if urgency == "high" else Severity.MEDIUM

        service_info = incident.get("service", {})
        event = IncidentAlertEvent(
            alert_name=incident.get("title", "PagerDuty Incident"),
            severity=severity,
            source_system=AlertSource.PAGERDUTY,
            affected_service=service_info.get("name", "unknown"),
            description=incident.get("description", incident.get("title", "")),
            labels={"urgency": urgency, "status": incident.get("status", "triggered")},
            raw_payload=incident,
            fingerprint=_generate_fingerprint(
                incident.get("title", ""), service_info.get("name", ""), {}
            ),
        )
        events.append(event)
    return events


# ─── Adapter: Generic / Custom ──────────────────────────────────────────────

def _adapt_generic(payload: Dict[str, Any]) -> list[IncidentAlertEvent]:
    """Fallback adapter for custom or unknown webhook formats."""
    event = IncidentAlertEvent(
        alert_name=payload.get("alert_name", payload.get("title", "Custom Alert")),
        severity=Severity(payload.get("severity", "medium")),
        source_system=AlertSource.CUSTOM,
        affected_service=payload.get("service", "unknown"),
        affected_namespace=payload.get("namespace", "default"),
        description=payload.get("description", payload.get("message", "No description")),
        labels=payload.get("labels", {}),
        raw_payload=payload,
        fingerprint=_generate_fingerprint(
            payload.get("alert_name", ""), payload.get("service", ""), payload.get("labels", {})
        ),
    )
    return [event]


# ─── Adapter Registry ───────────────────────────────────────────────────────

_ADAPTERS = {
    "prometheus": _adapt_prometheus,
    "pagerduty": _adapt_pagerduty,
    "generic": _adapt_generic,
}


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.post("/ingest/{source}")
async def ingest_webhook(source: str, request: Request):
    """
    Universal webhook ingestion endpoint.
    Route: POST /api/v1/webhooks/ingest/{source}

    Supported sources: prometheus, pagerduty, generic
    """
    if _producer is None:
        raise HTTPException(status_code=503, detail="Kafka producer not initialized")

    adapter = _ADAPTERS.get(source.lower())
    if not adapter:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source: {source}. Supported: {list(_ADAPTERS.keys())}",
        )

    payload = await request.json()
    events = adapter(payload)

    published_count = 0
    for event in events:
        _producer.publish(INCIDENT_ALERTS_TOPIC, event, key=event.fingerprint)
        published_count += 1
        logger.info(f"Published incident alert: {event.alert_name} [{event.severity}] → {INCIDENT_ALERTS_TOPIC}")

    _producer.flush(timeout=2.0)

    return {
        "status": "accepted",
        "source": source,
        "events_published": published_count,
        "fingerprints": [e.fingerprint for e in events],
    }


@router.get("/health")
async def webhook_health():
    """Health check for the webhook ingester."""
    return {"status": "healthy", "producer_ready": _producer is not None}
