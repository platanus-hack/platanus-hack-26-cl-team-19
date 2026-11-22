"""En el chat, los cambios de escenario y arquitectura se preparan para revisión."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import Field

from app.agent.proposals import ProposalDraft, ScenarioChange, prepare_proposal
from app.agent.tools import CLI_ONLY, AgentTools, Limiter, ProjectRef, ProposeArgs, ToolError
from app.api.store import ProjectStore

WRITE_TOOLS = {"set_traffic", "set_deployment"}


class ScenarioProposalArgs(ProjectRef):
    scenario: ScenarioChange
    note: str | None = Field(None, max_length=500)


class ChatAgentTools(AgentTools):
    def __init__(
        self,
        store: ProjectStore,
        owner: str | None,
        limiter: Limiter,
        attachments: Any,
        *,
        project_id: str,
        base_version: int,
    ) -> None:
        super().__init__(store, owner, limiter, attachments)
        self.project_id = project_id
        self.base_version = base_version
        for name in CLI_ONLY | WRITE_TOOLS:
            self._args.pop(name, None)
        self._args["propose_scenario"] = ScenarioProposalArgs

    def schemas(self, *, cli: bool = False) -> list[dict]:
        schemas = super().schemas(cli=cli)
        for schema in schemas:
            if schema["name"] == "propose_version":
                schema["description"] = (
                    "Prepara operaciones de ops_schema para aceptar en el chat. No guarda una versión."
                )
        return schemas

    def _preview(self, project_id: str, draft: ProposalDraft) -> dict:
        if project_id != self.project_id:
            raise ToolError("Prepara la propuesta para el proyecto abierto.")
        project = self._project(project_id)
        base = self._version(project, self.base_version)
        try:
            prepared = prepare_proposal(base.model, draft, self.store.list_scenarios(project_id))
        except ValueError as e:
            raise ToolError(str(e)) from None
        return {
            "proposal": {
                "id": str(uuid4()),
                "draft": draft.model_dump(exclude_none=True),
                "changes": prepared.changes,
                "warnings": prepared.warnings,
            }
        }

    def _propose_scenario(self, args: ScenarioProposalArgs) -> dict:
        return self._preview(
            args.project_id, ProposalDraft(base=self.base_version, scenario=args.scenario, note=args.note)
        )

    def _propose_version(self, args: ProposeArgs) -> dict:
        if args.version not in (None, self.base_version):
            raise ToolError("Usa como base la versión abierta en el editor.")
        if not 1 <= len(args.ops) <= 20:
            raise ToolError("La propuesta tiene que incluir entre 1 y 20 operaciones.")
        return self._preview(args.project_id, ProposalDraft(base=self.base_version, ops=args.ops, note=args.note))
