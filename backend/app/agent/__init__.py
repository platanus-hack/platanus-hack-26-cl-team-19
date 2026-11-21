"""Lo que usa el agente de IA (ADR 0001). Por ahora, las operaciones que proponen versiones (JAJ-68)."""

from app.agent.ops import OpError, OpsResult, apply_ops, ops_json_schema, parse_ops

__all__ = ["OpError", "OpsResult", "apply_ops", "ops_json_schema", "parse_ops"]
