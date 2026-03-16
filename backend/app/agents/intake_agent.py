"""Agent for building and validating the initial job specification."""

from app.agents.base_agent import BaseAgent
from app.models.job_spec import JobSpec


class IntakeAgent(BaseAgent[JobSpec]):
    prompt_file = "A0_job_spec_builder.txt"
    output_model = JobSpec
