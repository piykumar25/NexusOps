"""
NexusOps MetricsAgent
======================
Production-grade specialist agent for infrastructure metrics analysis.

Features:
  - Real Prometheus HTTP API integration (query and query_range)
  - Falls back to realistic simulated data when Prometheus is unavailable
  - Connection health check at initialization
  - Parallel multi-metric health summary queries
  - Anomaly detection using threshold-based analysis

Configuration:
  PROMETHEUS_URL: Prometheus server URL (default: http://localhost:9090)
"""

import asyncio
import json
import logging
import os
import random
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from backend.core.agents.agent_base import AgentMetadata
from backend.core.agents.pydantic_ai_agent import PydanticAIAgent

logger = logging.getLogger("nexusops.metrics")


class MetricDataPoint(BaseModel):
    timestamp: str
    value: float
    labels: dict = {}


class MetricsAgentOutput(BaseModel):
    finding: str = Field(description="Natural language summary of the metrics analysis")
    anomalies_detected: List[str] = Field(default_factory=list, description="List of detected anomalies")
    metrics_queried: List[str] = Field(default_factory=list, description="PromQL queries that were executed")
    data_points: List[MetricDataPoint] = Field(default_factory=list, description="Raw data points retrieved")


class MetricsAgent(PydanticAIAgent):
    """
    Specialist agent for querying and interpreting infrastructure metrics.
    Connects to a real Prometheus server when available, with simulated fallback.
    """

    def __init__(self, model_name: str, prometheus_url: str = "http://localhost:9090"):
        metadata = AgentMetadata(
            name="MetricsAgent",
            description="Queries Prometheus metrics to analyze infrastructure performance, detect anomalies, and correlate time-series data with incidents.",
        )
        super().__init__(
            metadata=metadata,
            system_prompt="""You are an expert SRE analyzing infrastructure metrics from Prometheus.
When given a service name and an incident description, you should:
1. Identify which metrics to check (CPU, memory, error rate, latency, request volume)
2. Use the query_prometheus tool to retrieve those metrics
3. Analyze the results for anomalies (spikes, drops, threshold violations)
4. Provide a clear, actionable summary of your findings

If Prometheus returns real data, analyze it carefully. If it returns simulated data (marked as "source": "simulated"), note that in your analysis.""",
            output_type=MetricsAgentOutput,
            model_name=model_name,
            timeout_seconds=60.0,
        )
        self.prometheus_url = prometheus_url.rstrip("/")
        self._prometheus_available = False
        self._http_client = httpx.AsyncClient(timeout=15.0)
        self._check_prometheus()
        self._register_tools()

    def _check_prometheus(self):
        """Check if Prometheus is reachable at startup."""
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.prometheus_url}/-/ready")
                if response.status_code == 200:
                    self._prometheus_available = True
                    logger.info(f"MetricsAgent: Prometheus server reachable at {self.prometheus_url}")
                else:
                    logger.warning(f"MetricsAgent: Prometheus returned {response.status_code} — using simulated data")
        except Exception as e:
            logger.warning(f"MetricsAgent: Prometheus not reachable ({e}) — using simulated data")

    async def _query_prometheus_api(self, promql: str) -> Dict:
        """Execute a PromQL instant query against the real Prometheus API."""
        try:
            response = await self._http_client.get(
                f"{self.prometheus_url}/api/v1/query",
                params={"query": promql},
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "success":
                return data.get("data", {})
            else:
                logger.warning(f"Prometheus query failed: {data.get('error', 'unknown')}")
                return {}

        except Exception as e:
            logger.error(f"Prometheus API query failed: {e}")
            return {}

    async def _query_prometheus_range(self, promql: str, start: str, end: str, step: str = "60s") -> Dict:
        """Execute a PromQL range query against the real Prometheus API."""
        try:
            response = await self._http_client.get(
                f"{self.prometheus_url}/api/v1/query_range",
                params={
                    "query": promql,
                    "start": start,
                    "end": end,
                    "step": step,
                },
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "success":
                return data.get("data", {})
            return {}

        except Exception as e:
            logger.error(f"Prometheus range query failed: {e}")
            return {}

    def _register_tools(self):

        async def query_prometheus(ctx: RunContext[Any], promql: str, service: str = "unknown", **kwargs) -> str:
            """
            Execute a PromQL query against Prometheus and return the results.
            Args:
                promql: The PromQL query string (e.g., 'rate(http_requests_total{service="payment"}[5m])')
                service: The target service name for context
            """
            if self._prometheus_available:
                return await self._real_query_prometheus(promql, service)
            return self._simulated_query_prometheus(promql, service)

        async def get_service_health_summary(ctx: RunContext[Any], service: str, **kwargs) -> str:
            """
            Get a comprehensive health snapshot of a service across all key metrics.
            Queries CPU, memory, error rate, and latency in parallel.
            Args:
                service: The service name to analyze
            """
            if self._prometheus_available:
                return await self._real_health_summary(service)
            return self._simulated_health_summary(service)

        self.add_tool(query_prometheus, name="query_prometheus", return_to_caller=True)
        self.add_tool(get_service_health_summary, name="get_service_health_summary", return_to_caller=True)

    async def _real_query_prometheus(self, promql: str, service: str) -> str:
        """Execute a real PromQL query and format the results."""
        try:
            data = await self._query_prometheus_api(promql)

            if not data:
                return json.dumps({
                    "query": promql,
                    "service": service,
                    "status": "no_data",
                    "message": "Query returned no results",
                })

            result_type = data.get("resultType", "vector")
            results = data.get("result", [])

            formatted = {
                "query": promql,
                "service": service,
                "result_type": result_type,
                "results": [],
            }

            for item in results[:20]:  # Cap at 20 results
                metric_labels = item.get("metric", {})
                if result_type == "vector":
                    timestamp, value = item.get("value", [0, "0"])
                    formatted["results"].append({
                        "labels": metric_labels,
                        "timestamp": str(timestamp),
                        "value": float(value),
                    })
                elif result_type == "matrix":
                    formatted["results"].append({
                        "labels": metric_labels,
                        "values": [
                            {"timestamp": str(ts), "value": float(val)}
                            for ts, val in item.get("values", [])[-10:]  # Last 10 points
                        ],
                    })

            return json.dumps(formatted, indent=2)

        except Exception as e:
            logger.error(f"Real Prometheus query failed: {e}")
            return self._simulated_query_prometheus(promql, service)

    async def _real_health_summary(self, service: str) -> str:
        """Query multiple metrics in parallel for a comprehensive health summary."""
        try:
            queries = {
                "cpu": f'rate(container_cpu_usage_seconds_total{{pod=~"{service}.*"}}[5m])',
                "memory": f'container_memory_working_set_bytes{{pod=~"{service}.*"}}',
                "error_rate": f'rate(http_requests_total{{service="{service}", status=~"5.."}}[5m]) / rate(http_requests_total{{service="{service}"}}[5m])',
                "latency_p99": f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service="{service}"}}[5m]))',
            }

            # Execute all queries in parallel
            tasks = {name: self._query_prometheus_api(promql) for name, promql in queries.items()}
            results = {}
            for name, task in tasks.items():
                results[name] = await task

            # Extract values
            def extract_value(data: Dict) -> Optional[float]:
                result_list = data.get("result", [])
                if result_list:
                    _, val = result_list[0].get("value", [0, "0"])
                    return float(val)
                return None

            cpu = extract_value(results.get("cpu", {}))
            memory = extract_value(results.get("memory", {}))
            error_rate = extract_value(results.get("error_rate", {}))
            latency = extract_value(results.get("latency_p99", {}))

            health = {
                "service": service,
                "source": "prometheus",
                "cpu_utilization": f"{round(cpu * 100, 1)}%" if cpu else "N/A",
                "memory_bytes": memory,
                "memory_utilization": f"{round(memory / (1024**3) * 100, 1)}%" if memory else "N/A",
                "error_rate_5xx": f"{round(error_rate * 100, 2)}%" if error_rate else "N/A",
                "p99_latency_ms": round(latency * 1000, 1) if latency else "N/A",
                "status": "healthy",
                "anomalies": [],
            }

            # Detect anomalies
            if cpu and cpu > 0.8:
                health["status"] = "degraded"
                health["anomalies"].append(f"High CPU: {health['cpu_utilization']}")
            if error_rate and error_rate > 0.05:
                health["status"] = "critical"
                health["anomalies"].append(f"Elevated error rate: {health['error_rate_5xx']}")
            if latency and latency > 1.0:
                health["anomalies"].append(f"High P99 latency: {health['p99_latency_ms']}ms")

            return json.dumps(health, indent=2)

        except Exception as e:
            logger.error(f"Real health summary failed: {e}")
            return self._simulated_health_summary(service)

    def _simulated_query_prometheus(self, promql: str, service: str) -> str:
        """Simulated Prometheus response for demo mode."""
        query_lower = promql.lower()

        if "cpu" in query_lower:
            result = {
                "query": promql, "service": service, "source": "simulated",
                "metric": "container_cpu_usage_seconds_total",
                "values": [
                    {"timestamp": "2026-03-19T15:00:00Z", "value": round(random.uniform(0.2, 0.4), 3)},
                    {"timestamp": "2026-03-19T15:10:00Z", "value": round(random.uniform(0.7, 0.95), 3)},
                    {"timestamp": "2026-03-19T15:20:00Z", "value": round(random.uniform(0.85, 0.99), 3)},
                ],
                "anomaly": f"CPU usage for {service} spiked to >90% at 15:10 UTC.",
            }
        elif "memory" in query_lower or "mem" in query_lower:
            result = {
                "query": promql, "service": service, "source": "simulated",
                "metric": "container_memory_working_set_bytes",
                "values": [
                    {"timestamp": "2026-03-19T15:00:00Z", "value": round(random.uniform(500, 600), 1)},
                    {"timestamp": "2026-03-19T15:10:00Z", "value": round(random.uniform(800, 950), 1)},
                    {"timestamp": "2026-03-19T15:20:00Z", "value": round(random.uniform(950, 1024), 1)},
                ],
                "anomaly": f"Memory usage for {service} approaching pod limit (1024Mi).",
            }
        elif "error" in query_lower or "5xx" in query_lower or "status" in query_lower:
            result = {
                "query": promql, "service": service, "source": "simulated",
                "metric": "http_requests_total{status=~'5..'}",
                "values": [
                    {"timestamp": "2026-03-19T15:00:00Z", "value": round(random.uniform(0.01, 0.02), 4)},
                    {"timestamp": "2026-03-19T15:10:00Z", "value": round(random.uniform(0.15, 0.35), 4)},
                    {"timestamp": "2026-03-19T15:20:00Z", "value": round(random.uniform(0.20, 0.45), 4)},
                ],
                "anomaly": f"5xx error rate for {service} jumped from 1% to >30%.",
            }
        elif "latency" in query_lower or "duration" in query_lower:
            result = {
                "query": promql, "service": service, "source": "simulated",
                "metric": "http_request_duration_seconds_bucket",
                "values": [
                    {"timestamp": "2026-03-19T15:00:00Z", "value": round(random.uniform(0.05, 0.1), 4)},
                    {"timestamp": "2026-03-19T15:10:00Z", "value": round(random.uniform(0.8, 2.5), 4)},
                    {"timestamp": "2026-03-19T15:20:00Z", "value": round(random.uniform(1.5, 5.0), 4)},
                ],
                "anomaly": f"P99 latency for {service} degraded from 100ms to >2s.",
            }
        else:
            result = {
                "query": promql, "service": service, "source": "simulated",
                "metric": "generic_metric",
                "values": [
                    {"timestamp": "2026-03-19T15:00:00Z", "value": round(random.uniform(0.1, 0.5), 4)},
                    {"timestamp": "2026-03-19T15:20:00Z", "value": round(random.uniform(0.5, 1.0), 4)},
                ],
                "anomaly": "Elevated metric values detected.",
            }

        return json.dumps(result, indent=2)

    def _simulated_health_summary(self, service: str) -> str:
        """Simulated health summary for demo mode."""
        health = {
            "service": service,
            "source": "simulated",
            "status": random.choice(["degraded", "critical", "unhealthy"]),
            "cpu_utilization": f"{random.randint(75, 98)}%",
            "memory_utilization": f"{random.randint(80, 99)}%",
            "error_rate_5xx": f"{round(random.uniform(5, 40), 1)}%",
            "p99_latency_ms": random.randint(800, 5000),
            "active_pods": random.randint(1, 3),
            "desired_pods": 3,
            "restarts_last_hour": random.randint(2, 15),
            "last_deploy": "2026-03-19T14:45:00Z",
            "anomalies": [
                f"{service} experiencing elevated error rates and resource pressure",
                "Multiple pod restarts in the last hour",
            ],
        }
        return json.dumps(health, indent=2)
