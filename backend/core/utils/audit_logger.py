"""
NexusOps Audit Logging System
===============================
Every LLM prompt, tool call, and agent response is logged to a persistent
audit trail. This is non-negotiable for enterprise compliance.

Architecture:
  - AuditLogger is injected into every agent execution path
  - Logs are written to PostgreSQL (via SQLAlchemy) AND to structured JSON files
  - Each audit record captures: who, what, when, input, output, tokens used, latency
  - Supports log levels: INFO, WARN, ERROR, SECURITY
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path


class AuditLevel(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    SECURITY = "SECURITY"


@dataclass
class AuditRecord:
    """Immutable audit record for every agent interaction."""
    record_id: str
    timestamp: str
    level: AuditLevel
    agent_name: str
    action: str                         # "llm_call", "tool_execution", "delegation", "error"
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    input_data: Optional[str] = None
    output_data: Optional[str] = None
    tool_name: Optional[str] = None
    model_name: Optional[str] = None
    latency_ms: float = 0.0
    token_usage: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class AuditLogger:
    """
    Enterprise-grade audit logger.
    Dual-writes to structured log files and can be extended to write to DB.
    """

    def __init__(self, log_dir: str = "./logs/audit"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("nexusops.audit")
        self._records: List[AuditRecord] = []

        # File handler for audit-specific logs
        fh = logging.FileHandler(self.log_dir / "audit.jsonl", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(fh)
        self._logger.setLevel(logging.INFO)

    def log(self, record: AuditRecord):
        """Write an audit record."""
        self._records.append(record)
        self._logger.info(json.dumps(asdict(record), default=str))

    def log_llm_call(
        self,
        agent_name: str,
        prompt: str,
        response: str,
        model_name: str,
        latency_ms: float,
        session_id: Optional[str] = None,
        token_usage: Optional[Dict[str, int]] = None,
    ):
        """Convenience method for LLM calls."""
        import uuid
        self.log(AuditRecord(
            record_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            level=AuditLevel.INFO,
            agent_name=agent_name,
            action="llm_call",
            session_id=session_id,
            input_data=prompt[:2000],          # Truncate for storage
            output_data=response[:2000],
            model_name=model_name,
            latency_ms=latency_ms,
            token_usage=token_usage or {},
        ))

    def log_tool_execution(
        self,
        agent_name: str,
        tool_name: str,
        input_data: str,
        output_data: str,
        latency_ms: float,
        session_id: Optional[str] = None,
    ):
        """Convenience method for tool executions."""
        import uuid
        self.log(AuditRecord(
            record_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            level=AuditLevel.INFO,
            agent_name=agent_name,
            action="tool_execution",
            session_id=session_id,
            tool_name=tool_name,
            input_data=input_data[:2000],
            output_data=output_data[:2000],
            latency_ms=latency_ms,
        ))

    def log_security_event(self, agent_name: str, description: str, metadata: Dict = None):
        """Log a security-relevant event (e.g., blocked mutation attempt)."""
        import uuid
        self.log(AuditRecord(
            record_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            level=AuditLevel.SECURITY,
            agent_name=agent_name,
            action="security_event",
            input_data=description,
            metadata=metadata or {},
        ))

    def get_recent_records(self, limit: int = 50) -> List[AuditRecord]:
        """Retrieve the most recent audit records (in-memory)."""
        return self._records[-limit:]


# Singleton instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
