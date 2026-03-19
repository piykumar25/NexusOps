"""
NexusOps MetricsAgent
======================
Specialist agent that converts natural language questions about system
performance into PromQL queries, executes them against Prometheus,
and returns structured metric analysis.

In production, this agent would:
  - Build PromQL from intent (e.g., "CPU usage of payment-service" → rate(container_cpu_usage_seconds_total{pod=~"payment.*"}[5m]))
  - Query a real Prometheus HTTP API
  - Interpret time series data and detect anomalies

For MVP, we simulate Prometheus responses with realistic mock data.
"""

from typing import Any, List, Optional
from pydantic import BaseModel, Field
from backend.core.agents.pydantic_ai_agent import PydanticAIAgent
from backend.core.agents.agent_base import AgentMetadata
import random
import json


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
    Converts natural language to PromQL, queries Prometheus, and analyzes results.
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
4. Provide a clear, actionable summary of your findings""",
            output_type=MetricsAgentOutput,
            model_name=model_name,
        )
        self.prometheus_url = prometheus_url
        self._register_tools()

    def _register_tools(self):

        async def query_prometheus(ctx, promql: str, service: str = "unknown") -> str:
            """
            Execute a PromQL query against Prometheus and return the results.
            Args:
                promql: The PromQL query string (e.g., 'rate(http_requests_total{service="payment"}[5m])')
                service: The target service name for context
            """
            # ── Simulated Prometheus Response ──
            # In production, this would be: requests.get(f"{self.prometheus_url}/api/v1/query", params={"query": promql})
            simulated_responses = {
                "cpu": {
                    "metric": "container_cpu_usage_seconds_total",
                    "values": [
                        {"timestamp": "2026-03-19T15:00:00Z", "value": round(random.uniform(0.2, 0.4), 3)},
                        {"timestamp": "2026-03-19T15:05:00Z", "value": round(random.uniform(0.3, 0.5), 3)},
                        {"timestamp": "2026-03-19T15:10:00Z", "value": round(random.uniform(0.7, 0.95), 3)},  # Spike
                        {"timestamp": "2026-03-19T15:15:00Z", "value": round(random.uniform(0.8, 0.98), 3)},  # Sustained
                        {"timestamp": "2026-03-19T15:20:00Z", "value": round(random.uniform(0.85, 0.99), 3)},  # Critical
                    ],
                    "anomaly": f"CPU usage for {service} spiked to >90% at 15:10 UTC and has remained elevated.",
                },
                "memory": {
                    "metric": "container_memory_working_set_bytes",
                    "values": [
                        {"timestamp": "2026-03-19T15:00:00Z", "value": round(random.uniform(500, 600), 1)},
                        {"timestamp": "2026-03-19T15:10:00Z", "value": round(random.uniform(800, 950), 1)},
                        {"timestamp": "2026-03-19T15:20:00Z", "value": round(random.uniform(950, 1024), 1)},  # Near OOM
                    ],
                    "anomaly": f"Memory usage for {service} is approaching the pod limit (1024Mi). OOM kill imminent.",
                },
                "error_rate": {
                    "metric": "http_requests_total{status=~'5..'}",
                    "values": [
                        {"timestamp": "2026-03-19T15:00:00Z", "value": round(random.uniform(0.01, 0.02), 4)},
                        {"timestamp": "2026-03-19T15:10:00Z", "value": round(random.uniform(0.15, 0.35), 4)},  # Spike
                        {"timestamp": "2026-03-19T15:20:00Z", "value": round(random.uniform(0.20, 0.45), 4)},  # Rising
                    ],
                    "anomaly": f"5xx error rate for {service} jumped from 1% to >30% starting at 15:10 UTC.",
                },
                "latency": {
                    "metric": "http_request_duration_seconds_bucket",
                    "values": [
                        {"timestamp": "2026-03-19T15:00:00Z", "value": round(random.uniform(0.05, 0.1), 4)},
                        {"timestamp": "2026-03-19T15:10:00Z", "value": round(random.uniform(0.8, 2.5), 4)},  # Slow
                        {"timestamp": "2026-03-19T15:20:00Z", "value": round(random.uniform(1.5, 5.0), 4)},  # Very slow
                    ],
                    "anomaly": f"P99 latency for {service} degraded from 100ms to >2s. Possible downstream dependency failure.",
                },
            }

            # Determine which mock to return based on PromQL content
            query_lower = promql.lower()
            if "cpu" in query_lower:
                result = simulated_responses["cpu"]
            elif "memory" in query_lower or "mem" in query_lower:
                result = simulated_responses["memory"]
            elif "error" in query_lower or "5xx" in query_lower or "status" in query_lower:
                result = simulated_responses["error_rate"]
            elif "latency" in query_lower or "duration" in query_lower:
                result = simulated_responses["latency"]
            else:
                result = simulated_responses["error_rate"]  # Default

            return json.dumps(result, indent=2)

        async def get_service_health_summary(ctx, service: str) -> str:
            """
            Get a comprehensive health snapshot of a service across all key metrics.
            Args:
                service: The service name to analyze
            """
            health = {
                "service": service,
                "status": random.choice(["degraded", "critical", "unhealthy"]),
                "cpu_utilization": f"{random.randint(75, 98)}%",
                "memory_utilization": f"{random.randint(80, 99)}%",
                "error_rate_5xx": f"{round(random.uniform(5, 40), 1)}%",
                "p99_latency_ms": random.randint(800, 5000),
                "active_pods": random.randint(1, 3),
                "desired_pods": 3,
                "restarts_last_hour": random.randint(2, 15),
                "last_deploy": "2026-03-19T14:45:00Z",
                "alert_summary": f"{service} is experiencing elevated error rates and resource pressure. Multiple pods have restarted in the last hour.",
            }
            return json.dumps(health, indent=2)

        self.add_tool(query_prometheus, name="query_prometheus", return_to_caller=True)
        self.add_tool(get_service_health_summary, name="get_service_health_summary", return_to_caller=True)
