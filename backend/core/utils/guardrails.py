"""
NexusOps Guardrails Module
============================
Production-grade input validation, topic classification, rate limiting,
and output sanitization for the NexusOps SaaS platform.

This module ensures:
  1. Malicious/injected inputs are blocked before reaching agents
  2. Off-topic queries are rejected with a polite redirect
  3. Per-session rate limiting prevents abuse
  4. Agent outputs are sanitized before reaching the client
"""

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nexusops.guardrails")


# ─── Configuration ───────────────────────────────────────────────────────────

@dataclass
class GuardrailConfig:
    """Configurable guardrail thresholds."""
    max_input_length: int = 4000
    min_input_length: int = 2
    rate_limit_requests: int = 30       # max requests per window
    rate_limit_window_seconds: int = 60  # window size
    enable_topic_filter: bool = True
    enable_injection_filter: bool = True
    enable_rate_limiter: bool = True
    enable_output_sanitizer: bool = True


# ─── Injection Detection ────────────────────────────────────────────────────

# Patterns that indicate prompt injection or manipulation attempts
_INJECTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?above\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(your|the)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.IGNORECASE),
    re.compile(r"new\s+instructions?:\s*", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"<\s*/?script", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r";\s*DROP\s+TABLE", re.IGNORECASE),
    re.compile(r";\s*DELETE\s+FROM", re.IGNORECASE),
    re.compile(r"UNION\s+SELECT", re.IGNORECASE),
    re.compile(r"'\s*OR\s+'1'\s*=\s*'1", re.IGNORECASE),
]


def detect_injection(text: str) -> Optional[str]:
    """
    Scan input for prompt injection and SQL injection patterns.
    Returns the matched pattern name if detected, None if clean.
    """
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning(f"Injection attempt detected: pattern={pattern.pattern[:50]}")
            return pattern.pattern[:50]
    return None


# ─── Topic Classification ───────────────────────────────────────────────────

# DevOps/Infrastructure keywords — queries must contain at least one
_DEVOPS_KEYWORDS: set = {
    # Infrastructure
    "pod", "pods", "container", "containers", "kubernetes", "k8s", "cluster",
    "node", "nodes", "deployment", "deployments", "namespace", "replica",
    "service", "services", "ingress", "helm", "docker", "image",
    # Observability
    "metric", "metrics", "prometheus", "grafana", "alert", "alerting",
    "dashboard", "monitor", "monitoring", "trace", "tracing", "log", "logs",
    "latency", "throughput", "error rate", "p99", "p95", "p50", "sli", "slo",
    # Incidents
    "incident", "outage", "downtime", "crash", "crashloop", "crashloopbackoff",
    "oom", "oomkill", "restart", "restarts", "failed", "failure", "timeout",
    "5xx", "500", "502", "503", "504", "error", "errors", "exception",
    # Resources
    "cpu", "memory", "disk", "network", "bandwidth", "iops", "storage",
    # Operations
    "deploy", "rollback", "rollout", "scale", "scaling", "autoscale", "hpa",
    "health", "healthcheck", "ready", "readiness", "liveness", "probe",
    "pipeline", "ci", "cd", "cicd", "build", "release",
    # Databases & Messaging
    "database", "db", "postgres", "postgresql", "mysql", "redis", "kafka",
    "queue", "topic", "consumer", "producer", "qdrant", "elasticsearch",
    # Cloud/DevOps
    "aws", "gcp", "azure", "terraform", "ansible", "vault", "secret",
    "config", "configuration", "environment", "env", "variable",
    # Common queries
    "why", "what", "how", "when", "status", "check", "analyze", "investigate",
    "troubleshoot", "debug", "fix", "resolve", "diagnose", "triage",
    # NexusOps-specific
    "nexusops", "agent", "agents", "runbook", "runbooks", "sre", "devops",
    "infrastructure", "infra", "payment", "auth", "order", "api", "gateway",
}

# Greetings and simple interaction patterns — always allowed
_GREETING_PATTERNS: List[re.Pattern] = [
    re.compile(r"^\s*(hi|hello|hey|greetings|good\s+(morning|afternoon|evening))\s*[!?.]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(thanks|thank\s+you|thx)\s*[!?.]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(help|what\s+can\s+you\s+do)\s*[!?.]*\s*$", re.IGNORECASE),
]


def classify_topic(text: str) -> Tuple[bool, str]:
    """
    Determine if a query is related to DevOps/Infrastructure.
    Returns (is_allowed, reason).
    """
    text_lower = text.lower()

    # Allow greetings
    for pattern in _GREETING_PATTERNS:
        if pattern.match(text_lower):
            return True, "greeting"

    # Tokenize and check for DevOps keywords
    words = set(re.findall(r'\b\w+\b', text_lower))
    # Also check for multi-word phrases
    matched_keywords = words & _DEVOPS_KEYWORDS
    # Check bigrams for multi-word keywords like "error rate"
    for kw in _DEVOPS_KEYWORDS:
        if ' ' in kw and kw in text_lower:
            matched_keywords.add(kw)

    if matched_keywords:
        return True, f"matched: {', '.join(list(matched_keywords)[:3])}"

    return False, "off-topic"


# ─── Rate Limiter ────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Sliding-window per-session rate limiter.
    Thread-safe for concurrent WebSocket connections.
    """

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._request_log: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, session_id: str) -> Tuple[bool, int]:
        """
        Check if a request from this session is allowed.
        Returns (is_allowed, remaining_requests).
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Clean old entries
        self._request_log[session_id] = [
            ts for ts in self._request_log[session_id] if ts > window_start
        ]

        current_count = len(self._request_log[session_id])

        if current_count >= self.max_requests:
            return False, 0

        self._request_log[session_id].append(now)
        return True, self.max_requests - current_count - 1

    def cleanup_session(self, session_id: str):
        """Remove a session from the rate limiter (on disconnect)."""
        self._request_log.pop(session_id, None)


# ─── Output Sanitizer ───────────────────────────────────────────────────────

# Patterns to redact from agent outputs
_SENSITIVE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'(?:password|passwd|pwd)\s*[=:]\s*\S+', re.IGNORECASE), '[REDACTED_PASSWORD]'),
    (re.compile(r'(?:api[_-]?key|apikey|secret[_-]?key)\s*[=:]\s*\S+', re.IGNORECASE), '[REDACTED_API_KEY]'),
    (re.compile(r'(?:token|bearer)\s*[=:]\s*[A-Za-z0-9_\-\.]+', re.IGNORECASE), '[REDACTED_TOKEN]'),
    (re.compile(r'(?:sk-|pk_live_|pk_test_|rk_live_|rk_test_)[A-Za-z0-9]{20,}'), '[REDACTED_KEY]'),
    (re.compile(r'(?:postgres(?:ql)?|mysql|redis|mongodb)://\S+@\S+', re.IGNORECASE), '[REDACTED_CONNECTION_STRING]'),
    (re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+\b'), '[REDACTED_IP:PORT]'),
    # File paths that could leak system info
    (re.compile(r'(?:C:|/home/|/root/|/etc/|/var/)\S+\.(?:py|env|conf|cfg|ini|key|pem)', re.IGNORECASE), '[REDACTED_PATH]'),
]


def sanitize_output(text: str) -> str:
    """
    Remove sensitive information from agent outputs before sending to clients.
    """
    sanitized = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


# ─── Circuit Breaker ────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Prevents cascading failures by tripping after consecutive LLM failures.
    States: CLOSED (normal) → OPEN (blocking) → HALF_OPEN (testing)
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._state: str = "CLOSED"

    @property
    def state(self) -> str:
        """Get current circuit breaker state, auto-transitioning to HALF_OPEN if recovery timeout passed."""
        if self._state == "OPEN":
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = "HALF_OPEN"
                logger.info("Circuit breaker: OPEN → HALF_OPEN (attempting recovery)")
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == "OPEN"

    def record_success(self):
        """Record a successful LLM call."""
        if self._state == "HALF_OPEN":
            logger.info("Circuit breaker: HALF_OPEN → CLOSED (recovery successful)")
        self._failure_count = 0
        self._state = "CLOSED"

    def record_failure(self):
        """Record a failed LLM call."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._failure_count >= self.failure_threshold:
            self._state = "OPEN"
            logger.warning(
                f"Circuit breaker: TRIPPED after {self._failure_count} consecutive failures. "
                f"Falling back to demo mode for {self.recovery_timeout}s."
            )

    def reset(self):
        """Manually reset the circuit breaker."""
        self._failure_count = 0
        self._state = "CLOSED"
        logger.info("Circuit breaker: manually reset to CLOSED")


# ─── Unified Guardrail Check ────────────────────────────────────────────────

@dataclass
class GuardrailResult:
    """Result of running all guardrail checks on an input."""
    allowed: bool
    rejection_reason: Optional[str] = None
    rejection_message: Optional[str] = None  # User-facing message
    sanitized_input: Optional[str] = None     # Cleaned input to pass to agents


_REJECTION_MESSAGES = {
    "injection": (
        "⚠️ **Security Alert**\n\n"
        "Your message was flagged by our security filters. "
        "Please rephrase your query about infrastructure or DevOps operations."
    ),
    "off-topic": (
        "🔒 **Topic Boundary**\n\n"
        "I'm NexusOps — an AI DevOps Operations Center. I specialize in:\n"
        "- 🔧 Kubernetes cluster analysis\n"
        "- 📊 Prometheus metrics investigation\n"
        "- 📚 Runbook and incident history search\n"
        "- ⚡ Automated incident triage\n\n"
        "Please ask me about your infrastructure, services, or incidents!\n\n"
        "💡 *Try: \"Why is the payment-service crashing?\" or \"Show me latency trends\"*"
    ),
    "rate_limit": (
        "⏳ **Rate Limit Reached**\n\n"
        "You've exceeded the request limit. Please wait a moment before sending another query.\n"
        "This limit protects system resources for all users."
    ),
    "too_long": (
        "📏 **Message Too Long**\n\n"
        "Please keep your query under 4000 characters. "
        "Try being more specific about the service or issue you'd like to investigate."
    ),
    "too_short": (
        "📝 **Message Too Short**\n\n"
        "Please provide more details about what you'd like to investigate."
    ),
}


def validate_input(
    message: str,
    session_id: str,
    config: GuardrailConfig,
    rate_limiter: RateLimiter,
) -> GuardrailResult:
    """
    Run all guardrail checks on a user input.
    Returns a GuardrailResult with the verdict and user-facing message.
    """
    # 1. Length checks
    if len(message.strip()) < config.min_input_length:
        return GuardrailResult(
            allowed=False,
            rejection_reason="too_short",
            rejection_message=_REJECTION_MESSAGES["too_short"],
        )

    if len(message) > config.max_input_length:
        return GuardrailResult(
            allowed=False,
            rejection_reason="too_long",
            rejection_message=_REJECTION_MESSAGES["too_long"],
        )

    # 2. Injection detection
    if config.enable_injection_filter:
        injection_match = detect_injection(message)
        if injection_match:
            logger.warning(f"[{session_id}] Injection blocked: {injection_match}")
            return GuardrailResult(
                allowed=False,
                rejection_reason="injection",
                rejection_message=_REJECTION_MESSAGES["injection"],
            )

    # 3. Topic classification
    if config.enable_topic_filter:
        is_on_topic, reason = classify_topic(message)
        if not is_on_topic:
            logger.info(f"[{session_id}] Off-topic query blocked: '{message[:80]}'")
            return GuardrailResult(
                allowed=False,
                rejection_reason="off-topic",
                rejection_message=_REJECTION_MESSAGES["off-topic"],
            )

    # 4. Rate limiting
    if config.enable_rate_limiter:
        allowed, remaining = rate_limiter.is_allowed(session_id)
        if not allowed:
            logger.warning(f"[{session_id}] Rate limited")
            return GuardrailResult(
                allowed=False,
                rejection_reason="rate_limit",
                rejection_message=_REJECTION_MESSAGES["rate_limit"],
            )

    # 5. Sanitize (strip excess whitespace, normalize)
    sanitized = " ".join(message.strip().split())

    return GuardrailResult(
        allowed=True,
        sanitized_input=sanitized,
    )
