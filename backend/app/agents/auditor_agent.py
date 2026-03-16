"""Agent for auditing generated presentation artifacts for fidelity/safety."""

from app.agents.base_agent import BaseAgent
from app.models.audit_report import AuditReport


class AuditorAgent(BaseAgent[AuditReport]):
    """A11 concrete agent for safety and fidelity audit pass."""

    prompt_file = "A11_auditor.txt"
    output_model = AuditReport
