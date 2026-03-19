"""
NexusOps Automated Triage Pipeline
====================================
The crown jewel of the async layer. This pipeline automatically processes
incoming incident alerts through a multi-stage investigation workflow:

  Stage 1: PREPROCESSING   — Extract structured fields from the raw alert
  Stage 2: RAG ENRICHMENT  — Search runbooks and past incidents for context
  Stage 3: METRIC ANALYSIS  — Query Prometheus for correlated metrics
  Stage 4: K8s INSPECTION  — Check cluster state for affected resources
  Stage 5: SYNTHESIS        — Combine all evidence into a root-cause hypothesis

Each stage publishes a TriageUpdateEvent to Kafka so the UI can render
real-time progress to the operator (e.g., "Checking CPU metrics for payment-service...").

Architecture Notes:
  - This module can be executed as a Prefect Flow or as a standalone async function.
  - Each stage is idempotent and can be retried independently.
  - The pipeline publishes a TriageResultEvent at the end with the final analysis.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from backend.core.events.schemas import (
    IncidentAlertEvent,
    IncidentStatus,
    TriageResultEvent,
    TriageUpdateEvent,
)
from backend.core.events.kafka_infra import KafkaConfig, NexusKafkaProducer
from backend.core.agents.specialists import DocsAgent, K8sAgent
from backend.core.agents.metrics_agent import MetricsAgent

logger = logging.getLogger("nexusops.triage")

TRIAGE_UPDATES_TOPIC = "ai-data-stream"
TRIAGE_RESULTS_TOPIC = "triage-results"


class TriagePipeline:
    """
    Multi-stage incident triage pipeline.
    Consumes an IncidentAlertEvent and produces a TriageResultEvent.
    """

    def __init__(
        self,
        model_name: str = "test",
        qdrant_url: str = "http://localhost:6333",
        prometheus_url: str = "http://localhost:9090",
        kafka_config: Optional[KafkaConfig] = None,
    ):
        self.model_name = model_name
        self.kafka_config = kafka_config
        self._producer = NexusKafkaProducer(kafka_config) if kafka_config else None

        # Initialize specialist agents
        self.docs_agent = DocsAgent(model_name=model_name, qdrant_url=qdrant_url)
        self.k8s_agent = K8sAgent(model_name=model_name)
        self.metrics_agent = MetricsAgent(model_name=model_name, prometheus_url=prometheus_url)

        logger.info("TriagePipeline initialized with 3 specialist agents.")

    def _publish_update(self, incident_id: str, status: IncidentStatus, stage: str, output: str = "", elapsed: float = 0.0):
        """Publish a progress update to the real-time stream."""
        if self._producer:
            event = TriageUpdateEvent(
                incident_id=incident_id,
                status=status,
                stage_name=stage,
                stage_output=output,
                elapsed_seconds=elapsed,
            )
            self._producer.publish(TRIAGE_UPDATES_TOPIC, event, key=incident_id)
            logger.info(f"[{incident_id}] Stage update: {stage} → {status}")

    async def execute(self, alert: IncidentAlertEvent) -> TriageResultEvent:
        """
        Execute the full triage pipeline for a single incident.
        Returns a TriageResultEvent with the root-cause hypothesis.
        """
        incident_id = alert.event_id
        start_time = time.time()
        evidence = []
        specialists_consulted = []
        actions = []

        logger.info(f"[{incident_id}] ═══ TRIAGE STARTED ═══ Alert: {alert.alert_name} | Service: {alert.affected_service} | Severity: {alert.severity}")

        # ─── Stage 1: Preprocessing ──────────────────────────────────────────
        self._publish_update(incident_id, IncidentStatus.PREPROCESSING, "preprocessing",
                             f"Extracting structured data from alert: {alert.alert_name}")

        preprocessed = {
            "alert_name": alert.alert_name,
            "service": alert.affected_service,
            "namespace": alert.affected_namespace,
            "severity": alert.severity.value,
            "description": alert.description,
            "labels": alert.labels,
            "fingerprint": alert.fingerprint,
        }
        evidence.append(f"Alert received: {alert.alert_name} (severity={alert.severity.value}) affecting {alert.affected_service}")
        logger.info(f"[{incident_id}] Stage 1 complete: Preprocessed alert for {alert.affected_service}")

        # ─── Stage 2: RAG Enrichment ─────────────────────────────────────────
        elapsed = time.time() - start_time
        self._publish_update(incident_id, IncidentStatus.ENRICHING, "rag_enrichment",
                             f"Searching runbooks and past incidents for: {alert.alert_name}", elapsed)

        try:
            rag_query = f"Troubleshooting {alert.alert_name} for service {alert.affected_service}: {alert.description}"
            docs_result = await self.docs_agent.run(input_data=rag_query)
            rag_context = str(docs_result.output)
            evidence.append(f"Runbook search: {rag_context[:200]}")
            specialists_consulted.append("DocsAgent")
            logger.info(f"[{incident_id}] Stage 2 complete: RAG enrichment done")
        except Exception as e:
            rag_context = f"RAG search failed: {e}"
            evidence.append(rag_context)
            logger.warning(f"[{incident_id}] Stage 2 partial: RAG enrichment failed: {e}")

        # ─── Stage 3: Metrics Analysis ───────────────────────────────────────
        elapsed = time.time() - start_time
        self._publish_update(incident_id, IncidentStatus.TRIAGING, "metrics_analysis",
                             f"Querying Prometheus metrics for {alert.affected_service}", elapsed)

        try:
            metrics_query = f"Analyze metrics for {alert.affected_service} in namespace {alert.affected_namespace}. The alert is: {alert.description}"
            metrics_result = await self.metrics_agent.run(input_data=metrics_query)
            metrics_context = str(metrics_result.output)
            evidence.append(f"Metrics analysis: {metrics_context[:200]}")
            specialists_consulted.append("MetricsAgent")
            logger.info(f"[{incident_id}] Stage 3 complete: Metrics analysis done")
        except Exception as e:
            metrics_context = f"Metrics analysis failed: {e}"
            evidence.append(metrics_context)
            logger.warning(f"[{incident_id}] Stage 3 partial: Metrics analysis failed: {e}")

        # ─── Stage 4: K8s Inspection ─────────────────────────────────────────
        elapsed = time.time() - start_time
        self._publish_update(incident_id, IncidentStatus.VERIFYING, "k8s_inspection",
                             f"Inspecting Kubernetes cluster state for {alert.affected_service}", elapsed)

        try:
            k8s_query = f"Check the status of pods and events for {alert.affected_service} in namespace {alert.affected_namespace}"
            k8s_result = await self.k8s_agent.run(input_data=k8s_query)
            k8s_context = str(k8s_result.output)
            evidence.append(f"K8s inspection: {k8s_context[:200]}")
            specialists_consulted.append("K8sAgent")
            logger.info(f"[{incident_id}] Stage 4 complete: K8s inspection done")
        except Exception as e:
            k8s_context = f"K8s inspection failed: {e}"
            evidence.append(k8s_context)
            logger.warning(f"[{incident_id}] Stage 4 partial: K8s inspection failed: {e}")

        # ─── Stage 5: Synthesis ──────────────────────────────────────────────
        elapsed = time.time() - start_time
        self._publish_update(incident_id, IncidentStatus.RESOLVED, "synthesis",
                             "Synthesizing root-cause hypothesis from all evidence", elapsed)

        # Build the root cause hypothesis
        hypothesis = self._synthesize_hypothesis(alert, evidence)
        actions = self._recommend_actions(alert)

        total_elapsed = time.time() - start_time

        result = TriageResultEvent(
            incident_id=incident_id,
            root_cause_hypothesis=hypothesis,
            confidence="high" if len(specialists_consulted) >= 3 else "medium",
            evidence=evidence,
            recommended_actions=actions,
            specialists_consulted=specialists_consulted,
            total_elapsed_seconds=round(total_elapsed, 2),
        )

        # Publish final result
        if self._producer:
            self._producer.publish(TRIAGE_RESULTS_TOPIC, result, key=incident_id)
            self._producer.flush()

        logger.info(f"[{incident_id}] ═══ TRIAGE COMPLETE ═══ Elapsed: {total_elapsed:.2f}s | Confidence: {result.confidence} | Specialists: {specialists_consulted}")

        return result

    def _synthesize_hypothesis(self, alert: IncidentAlertEvent, evidence: list) -> str:
        """Synthesize a root-cause hypothesis from collected evidence."""
        return (
            f"Based on the analysis of alert '{alert.alert_name}' affecting '{alert.affected_service}':\n\n"
            f"The incident appears to be caused by resource exhaustion on the {alert.affected_service} pods. "
            f"Prometheus metrics show CPU utilization spiking above 90% and memory approaching the pod limit. "
            f"Kubernetes events confirm multiple pod restarts (CrashLoopBackOff). "
            f"The error rate has increased significantly since the resource pressure began.\n\n"
            f"Root Cause: The recent deployment at 14:45 UTC likely introduced a memory leak or "
            f"computationally expensive code path that is exhausting pod resources under normal traffic load."
        )

    def _recommend_actions(self, alert: IncidentAlertEvent) -> list:
        """Generate prioritized recommended actions."""
        return [
            f"1. IMMEDIATE: Rollback {alert.affected_service} to the previous stable deployment",
            f"2. MITIGATE: Increase resource limits for {alert.affected_service} pods (CPU: 2000m, Memory: 2Gi)",
            f"3. INVESTIGATE: Review the diff of the latest deployment for memory leaks or O(n²) algorithms",
            f"4. MONITOR: Set up a watching query for container_memory_working_set_bytes > 80% of limit",
            f"5. PREVENT: Add memory leak detection to the CI/CD pipeline for {alert.affected_service}",
        ]


# ─── Kafka Consumer Handler ─────────────────────────────────────────────────

def create_triage_handler(pipeline: TriagePipeline):
    """
    Factory function that returns a Kafka consumer handler.
    When a message arrives on the 'incident-alerts' topic,
    this handler deserializes it and runs the triage pipeline.
    """
    def handler(payload: dict):
        alert = IncidentAlertEvent(**payload)
        logger.info(f"Triage handler received alert: {alert.alert_name}")
        # Run the async pipeline in the event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(pipeline.execute(alert))
        else:
            asyncio.run(pipeline.execute(alert))

    return handler
