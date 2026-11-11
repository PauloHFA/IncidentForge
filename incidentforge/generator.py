"""Async generation orchestrator for IncidentForge."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aiofiles
from pydantic import BaseModel

from .models import (
    ArchitectureProfile,
    GenerationPlan,
    GenerationTask,
    Incident,
    IncidentMetadata,
    Language,
    Severity,
    Style,
    Topology,
)
from .client import LLMClient, LLMResponse, TolerantJSONParser, create_llm_client, generate_incident
from .planner import build_generation_plan
from .retry import RetryConfig, with_retry
from .prompts import render_incident_prompt, render_correction_prompt


@dataclass
class GenerationState:
    """State for generation resume capability."""

    plan: GenerationPlan
    completed_tasks: dict[str, Incident] = field(default_factory=dict)
    failed_tasks: dict[str, dict] = field(default_factory=dict)
    rejected_tasks: list[dict] = field(default_factory=list)
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    start_time: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)

    def to_json(self) -> str:
        """Serialize state to JSON."""
        data = {
            "plan": self.plan.model_dump(),
            "completed_tasks": {k: v.model_dump() for k, v in self.completed_tasks.items()},
            "failed_tasks": self.failed_tasks,
            "rejected_tasks": self.rejected_tasks,
            "total_tokens_input": self.total_tokens_input,
            "total_tokens_output": self.total_tokens_output,
            "start_time": self.start_time,
            "last_update": self.last_update,
        }
        return json.dumps(data, default=str, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> GenerationState:
        """Deserialize state from JSON."""
        data = json.loads(json_str)
        plan = GenerationPlan.model_validate(data["plan"])
        completed = {k: Incident.model_validate(v) for k, v in data["completed_tasks"].items()}
        return cls(
            plan=plan,
            completed_tasks=completed,
            failed_tasks=data["failed_tasks"],
            rejected_tasks=data["rejected_tasks"],
            total_tokens_input=data["total_tokens_input"],
            total_tokens_output=data["total_tokens_output"],
            start_time=data["start_time"],
            last_update=data["last_update"],
        )

    @property
    def elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time

    @property
    def completed_count(self) -> int:
        """Get number of completed tasks."""
        return len(self.completed_tasks)

    @property
    def remaining_count(self) -> int:
        """Get number of remaining tasks."""
        return self.plan.total_count - self.completed_count


@dataclass
class GeneratorConfig:
    """Configuration for incident generator."""

    concurrency: int = 8
    max_tokens_budget: int | None = None
    max_validation_retries: int = 2
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    state_dir: Path = Path(".incidentforge")
    resume: bool = False
    dry_run: bool = False


class TokenBudgetExceeded(Exception):
    """Raised when token budget is exceeded."""

    def __init__(self, used: int, budget: int):
        self.used = used
        self.budget = budget
        super().__init__(f"Token budget exceeded: {used:,} / {budget:,}")


class IncidentGenerator:
    """Async incident generator with concurrency control and resume capability."""

    def __init__(
        self,
        topology: Topology,
        config: GeneratorConfig,
        llm_client: LLMClient | None = None,
        llm_config: Any = None,
    ):
        self.topology = topology
        self.config = config
        self.llm_client = llm_client
        self.llm_config = llm_config
        self._semaphore: asyncio.Semaphore | None = None
        self._state: GenerationState | None = None
        self._state_file: Path | None = None
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None
        self._shutdown = False

    async def initialize(self) -> None:
        """Initialize generator (load state if resuming)."""
        self._semaphore = asyncio.Semaphore(self.config.concurrency)
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self.config.state_dir / "state.jsonl"

        if self.config.resume and self._state_file.exists():
            await self._load_state()
        else:
            # Build new plan
            plan = build_generation_plan(self.topology, count=100, seed=42)
            self._state = GenerationState(plan=plan)

        # Start background writer
        self._writer_task = asyncio.create_task(self._background_writer())

    async def _load_state(self) -> None:
        """Load generation state from file."""
        try:
            async with aiofiles.open(self._state_file, "r", encoding="utf-8") as f:
                content = await f.read()
            if content.strip():
                # Get last line (most recent state)
                lines = content.strip().split("\n")
                last_line = lines[-1]
                self._state = GenerationState.from_json(last_line)
                print(f"[RESUME] Loaded state: {self._state.completed_count}/{self._state.plan.total_count} completed")
            else:
                raise ValueError("Empty state file")
        except Exception as e:
            print(f"[WARN] Failed to load state: {e}. Starting fresh.")
            plan = build_generation_plan(self.topology, count=100, seed=42)
            self._state = GenerationState(plan=plan)

    async def _save_state(self) -> None:
        """Save generation state to file."""
        if self._state is None:
            return
        self._state.last_update = time.time()
        state_json = self._state.to_json()
        await self._write_queue.put(("state", state_json))

    async def _background_writer(self) -> None:
        """Background task for async file writing."""
        state_file = self._state_file
        incidents_file = self.config.state_dir / "incidents.jsonl"
        rejected_file = self.config.state_dir / "rejected.jsonl"

        async with aiofiles.open(state_file, "a", encoding="utf-8") as sf, \
                   aiofiles.open(incidents_file, "a", encoding="utf-8") as inf, \
                   aiofiles.open(rejected_file, "a", encoding="utf-8") as rf:

            while not self._shutdown:
                try:
                    item_type, data = await asyncio.wait_for(self._write_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if item_type == "state":
                    await sf.write(data + "\n")
                    await sf.flush()
                elif item_type == "incident":
                    await inf.write(data + "\n")
                    await inf.flush()
                elif item_type == "rejected":
                    await rf.write(data + "\n")
                    await rf.flush()

    async def generate(self) -> list[Incident]:
        """
        Generate incidents according to plan.

        Returns:
            List of generated incidents.
        """
        if self._state is None:
            await self.initialize()

        if self.config.dry_run:
            print(f"[DRY RUN] Would generate {self._state.plan.total_count} incidents")
            print(f"[DRY RUN] Estimated tokens: {self._state.plan.estimated_tokens:,}")
            return []

        print(f"[GENERATE] Starting generation: {self._state.remaining_count} remaining tasks")
        print(f"[GENERATE] Concurrency: {self.config.concurrency}")

        # Create tasks for remaining work
        remaining_tasks = self._get_remaining_tasks()
        if not remaining_tasks:
            print("[GENERATE] All tasks already completed")
            return list(self._state.completed_tasks.values())

        # Process tasks with concurrency control
        await self._process_tasks(remaining_tasks)

        # Wait for writer to finish
        await self._write_queue.join()
        self._shutdown = True
        if self._writer_task:
            await self._writer_task

        # Final state save
        await self._save_state()

        incidents = list(self._state.completed_tasks.values())
        print(f"[GENERATE] Completed: {len(incidents)} incidents generated")
        print(f"[GENERATE] Tokens: {self._state.total_tokens_input:,} in, {self._state.total_tokens_output:,} out")
        print(f"[GENERATE] Time: {self._state.elapsed_time:.1f}s")

        return incidents

    def _get_remaining_tasks(self) -> list[GenerationTask]:
        """Get tasks that haven't been completed yet."""
        completed_keys = set(self._state.completed_tasks.keys())
        remaining = []

        for task in self._state.plan.tasks:
            task_key = self._task_key(task)
            if task_key not in completed_keys:
                remaining.append(task)

        return remaining

    def _task_key(self, task: GenerationTask) -> str:
        """Generate unique key for task."""
        return f"{task.service_name}|{task.failure_category.value}|{task.severity.value}"

    async def _process_tasks(self, tasks: list[GenerationTask]) -> None:
        """Process tasks with concurrency control."""
        # Create worker tasks
        workers = [
            asyncio.create_task(self._worker(i, tasks))
            for i in range(min(self.config.concurrency, len(tasks)))
        ]

        # Wait for all workers
        await asyncio.gather(*workers, return_exceptions=True)

    async def _worker(self, worker_id: int, tasks: list[GenerationTask]) -> None:
        """Worker coroutine to process tasks."""
        task_iter = iter(tasks)

        while not self._shutdown:
            async with self._semaphore:
                try:
                    task = next(task_iter)
                except StopIteration:
                    break

                # Check token budget
                if self.config.max_tokens_budget:
                    total_used = self._state.total_tokens_input + self._state.total_tokens_output
                    if total_used >= self.config.max_tokens_budget:
                        print(f"[WORKER {worker_id}] Token budget reached, stopping")
                        self._shutdown = True
                        break

                await self._process_task(worker_id, task)

    async def _process_task(self, worker_id: int, task: GenerationTask) -> None:
        """Process a single generation task."""
        task_key = self._task_key(task)
        print(f"[WORKER {worker_id}] Processing: {task_key}")

        # Get service technologies for prompt
        service = self.topology.get_service(task.service_name)
        if not service:
            print(f"[WORKER {worker_id}] Service not found: {task.service_name}")
            return

        technologies = [t.name for t in service.technology]

        # Render prompt
        prompt = render_incident_prompt(
            task=task,
            service=service,
            technologies=technologies,
            topology=self.topology,
        )

        system_prompt = self._get_system_prompt(task)

        # Get schema for structured output
        schema = Incident.model_json_schema()

        # Create LLM client if not provided
        client = self.llm_client
        if client is None and self.llm_config:
            client = create_llm_client(self.llm_config)

        if client is None:
            raise ValueError("No LLM client available")

        # Generate with retries
        incident = await self._generate_with_validation(
            client=client,
            task=task,
            prompt=prompt,
            system_prompt=system_prompt,
            schema=schema,
        )

        if incident:
            # Success
            self._state.completed_tasks[task_key] = incident
            if incident.metadata.tokens_input:
                self._state.total_tokens_input += incident.metadata.tokens_input
            if incident.metadata.tokens_output:
                self._state.total_tokens_output += incident.metadata.tokens_output

            # Save incident
            incident_json = incident.model_dump_json()
            await self._write_queue.put(("incident", incident_json))

            print(f"[WORKER {worker_id}] Completed: {task_key} -> {incident.id}")
        else:
            # Failed after retries
            self._state.failed_tasks[task_key] = {
                "task": task.model_dump(),
                "attempts": self.config.max_validation_retries + 1,
            }
            print(f"[WORKER {worker_id}] Failed: {task_key}")

        # Save state periodically
        if len(self._state.completed_tasks) % 10 == 0:
            await self._save_state()

    async def _generate_with_validation(
        self,
        client: LLMClient,
        task: GenerationTask,
        prompt: str,
        system_prompt: str,
        schema: dict,
    ) -> Incident | None:
        """Generate incident with validation retries."""
        last_error = None

        for attempt in range(self.config.max_validation_retries + 1):
            try:
                incident, response, error = await generate_incident(
                    client=client,
                    task=task,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    schema=schema,
                    use_structured=True,
                )

                if error:
                    last_error = error
                    if attempt < self.config.max_validation_retries:
                        # Try correction
                        correction_prompt = render_correction_prompt(
                            original_prompt=prompt,
                            error=error,
                            attempt=attempt + 1,
                        )
                        prompt = correction_prompt
                        continue
                    else:
                        # Max retries reached, save to rejected
                        await self._save_rejected(task, prompt, last_error)
                        return None

                if incident is None:
                    last_error = "Failed to parse incident from response"
                    if attempt < self.config.max_validation_retries:
                        continue
                    else:
                        await self._save_rejected(task, prompt, last_error)
                        return None

                # Validate incident
                validation_error = self._validate_incident(incident, task, service)
                if validation_error:
                    last_error = validation_error
                    if attempt < self.config.max_validation_retries:
                        correction_prompt = render_correction_prompt(
                            original_prompt=prompt,
                            error=validation_error,
                            attempt=attempt + 1,
                        )
                        prompt = correction_prompt
                        continue
                    else:
                        await self._save_rejected(task, prompt, last_error)
                        return None

                # Update metadata with generation info
                if response and response.usage:
                    incident.metadata.tokens_input = response.usage.get("prompt_tokens", 0)
                    incident.metadata.tokens_output = response.usage.get("completion_tokens", 0)
                    incident.metadata.generation_time_ms = int(
                        (time.time() - self._state.start_time) * 1000
                    )

                return incident

            except Exception as e:
                last_error = str(e)
                if attempt < self.config.max_validation_retries:
                    await asyncio.sleep(2 ** attempt)  # Brief backoff
                    continue
                else:
                    await self._save_rejected(task, prompt, last_error)
                    return None

        return None

    def _validate_incident(self, incident: Incident, task: GenerationTask, service: Any) -> str | None:
        """Validate incident against semantic rules."""
        # Check service matches
        if incident.service != task.service_name:
            return f"Incident service '{incident.service}' doesn't match task '{task.service_name}'"

        # Check severity matches
        if incident.severity != task.severity:
            return f"Incident severity '{incident.severity}' doesn't match task '{task.severity}'"

        # Check failure category matches
        if incident.failure_category != task.failure_category:
            return f"Incident failure category '{incident.failure_category}' doesn't match task '{task.failure_category}'"

        # Check timeline has at least 5 events
        if len(incident.timeline) < 5:
            return f"Timeline has only {len(incident.timeline)} events, minimum is 5"

        # Check root cause mentions technology
        tech_names = [t.name.lower() for t in service.technology]
        root_cause_lower = incident.root_cause_analysis.lower()
        if not any(tech in root_cause_lower for tech in tech_names):
            return f"Root cause doesn't mention any service technology: {tech_names}"

        # Check action items count
        if not (2 <= len(incident.action_items) <= 8):
            return f"Action items count {len(incident.action_items)} not in range 2-8"

        # Check outage duration consistency (already in model validator)
        return None

    async def _save_rejected(self, task: GenerationTask, prompt: str, error: str) -> None:
        """Save rejected incident."""
        rejected = {
            "task": task.model_dump(),
            "prompt": prompt,
            "error": error,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._state.rejected_tasks.append(rejected)
        await self._write_queue.put(("rejected", json.dumps(rejected, ensure_ascii=False)))

    def _get_system_prompt(self, task: GenerationTask) -> str:
        """Get system prompt based on task configuration."""
        base = """You are an expert Site Reliability Engineer writing production incident post-mortems.
Generate realistic, detailed incident reports in JSON format that conform exactly to the provided schema.

Key principles:
- Blameless culture: focus on systems, not individuals
- Technical accuracy: use real technology names and failure modes
- Actionable insights: action items should be specific and assignable
- Consistency: timeline must be chronologically ordered and duration must match"""

        style_guidance = {
            Style.BLAMELESS_FORMAL: "Use formal, blameless language. Comprehensive detail.",
            Style.TERSE: "Be concise. Maximum 60% of detailed length. Essential facts only.",
            Style.DETAILED: "Provide extensive detail. Include context, debugging steps, and thorough analysis.",
        }

        lang_guidance = {
            Language.EN: "Write in English.",
            Language.PT_BR: "Escreva em português do Brasil. Mantenha chaves JSON em inglês.",
        }

        arch_guidance = {
            ArchitectureProfile.MICROSERVICES: "Context: Microservices architecture with distributed services.",
            ArchitectureProfile.MONOLITH_LEGACY: "Context: Legacy monolithic application with shared database.",
            ArchitectureProfile.SERVERLESS: "Context: Serverless architecture with managed services.",
        }

        return "\n\n".join([
            base,
            style_guidance.get(task.style, ""),
            lang_guidance.get(task.language, ""),
            arch_guidance.get(task.architecture_profile, ""),
        ])

    async def close(self) -> None:
        """Clean up resources."""
        self._shutdown = True
        if self._writer_task:
            await self._writer_task
        if self.llm_client:
            await self.llm_client.close()


async def generate_incidents(
    topology: Topology,
    count: int = 100,
    concurrency: int = 8,
    seed: int = 42,
    max_tokens_budget: int | None = None,
    resume: bool = False,
    dry_run: bool = False,
    llm_config: Any = None,
) -> list[Incident]:
    """
    Convenience function to generate incidents.

    Args:
        topology: System topology.
        count: Number of incidents to generate.
        concurrency: Maximum concurrent requests.
        seed: Random seed for reproducibility.
        max_tokens_budget: Optional token budget limit.
        resume: Whether to resume from previous state.
        dry_run: Whether to just show plan without generating.
        llm_config: LLM configuration.

    Returns:
        List of generated incidents.
    """
    config = GeneratorConfig(
        concurrency=concurrency,
        max_tokens_budget=max_tokens_budget,
        resume=resume,
        dry_run=dry_run,
    )

    generator = IncidentGenerator(topology, config, llm_config=llm_config)
    await generator.initialize()

    try:
        return await generator.generate()
    finally:
        await generator.close()


if __name__ == "__main__":
    import sys
    from .topology import load_topology

    async def main():
        if len(sys.argv) > 1:
            topology_path = sys.argv[1]
        else:
            topology_path = "configs/topology_sample.yaml"

        count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        concurrency = int(sys.argv[3]) if len(sys.argv) > 3 else 2

        topology = load_topology(topology_path)

        # Dry run by default for testing
        incidents = await generate_incidents(
            topology=topology,
            count=count,
            concurrency=concurrency,
            dry_run=True,
        )

        print(f"Would generate {len(incidents)} incidents")

    asyncio.run(main())