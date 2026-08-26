"""Production vs shadow comparison (Phase 7 §14, §15).

``ComparisonEngine`` maps (production decision, shadow decision) to a
ComparisonClass. A mismatch is a metric/audit signal ONLY -- never an automatic
correctness judgment and never a trigger to override, replace or execute a
shadow result.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import ComparisonClass, ShadowDecision


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    comparison_class: ComparisonClass
    reason: str
    comparable: bool

    def to_dict(self) -> dict[str, object]:
        return {"class": self.comparison_class.value, "reason": self.reason,
                "comparable": self.comparable}


class ComparisonEngine:
    """Deterministic, side-effect-free comparison of two decisions."""

    @staticmethod
    def compare(
        *,
        production: ShadowDecision | None,
        shadow: ShadowDecision,
    ) -> ComparisonResult:
        if type(shadow) is not ShadowDecision:
            raise ValueError("shadow must be an exact ShadowDecision value")
        if production is None:
            return ComparisonResult(ComparisonClass.NOT_COMPARABLE, "no production decision supplied",
                                    comparable=False)

        if type(production) is not ShadowDecision:
            return ComparisonResult(ComparisonClass.NOT_COMPARABLE, "production is not a decision",
                                    comparable=False)

        # Shadow denial / unknown short-circuit to their own classes.
        if shadow.boundary_disposition == "denied" or shadow.policy_disposition == "denied":
            return ComparisonResult(ComparisonClass.SHADOW_DENIED,
                                    "shadow boundary/policy denied", comparable=True)
        if shadow.supervisor_disposition in ("unknown", "human_review"):
            return ComparisonResult(ComparisonClass.SHADOW_UNKNOWN,
                                    "shadow disposition unknown/human-review", comparable=True)

        if shadow.selected_agent != production.selected_agent:
            return ComparisonResult(ComparisonClass.DIFFERENT_AGENT,
                                    f"shadow selected {shadow.selected_agent!r} != production {production.selected_agent!r}",
                                    comparable=True)
        if shadow.plan_digest != production.plan_digest:
            return ComparisonResult(ComparisonClass.DIFFERENT_PLAN, "plan digest differs",
                                    comparable=True)
        if shadow.supervisor_disposition != production.supervisor_disposition:
            return ComparisonResult(ComparisonClass.DIFFERENT_DISPOSITION,
                                    reason="supervisor disposition differs", comparable=True)

        if shadow.agent_observation and production.agent_observation:
            if shadow.agent_observation == production.agent_observation:
                return ComparisonResult(ComparisonClass.MATCH, "observations agree",
                                        comparable=True)
            return ComparisonResult(ComparisonClass.PARTIAL_MATCH, "decision agrees, observation differs",
                                    comparable=True)

        return ComparisonResult(ComparisonClass.MATCH, "decisions agree", comparable=True)

    @staticmethod
    def safety_assertion() -> bool:
        """Documented invariant: comparison can never auto-correct production."""
        return True


__all__ = ["ComparisonEngine", "ComparisonResult"]