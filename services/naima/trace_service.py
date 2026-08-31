from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class NaimaTraceEvent:
    """
    Un événement de trace produit pendant un tour Naima.
    """

    event: str

    message: Optional[str] = None

    data: Dict[str, Any] = field(
        default_factory=dict
    )

    timestamp: str = field(
        default_factory=lambda: (
            datetime.now(
                timezone.utc
            ).isoformat()
        )
    )

    def to_dict(
        self,
    ) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "message": self.message,
            "data": dict(
                self.data
            ),
        }


class NaimaTraceCollector:
    """
    Collecteur local de traces.

    Il ne dépend ni de Flask,
    ni de print(),
    ni d'un logger particulier.

    L'adaptateur Flask pourra plus tard décider
    de les imprimer ou de les enregistrer.
    """

    def __init__(
        self,
    ):
        self._events: List[
            NaimaTraceEvent
        ] = []

    def add(
        self,
        event: str,
        *,
        message: Optional[str] = None,
        **data: Any,
    ) -> None:

        self._events.append(
            NaimaTraceEvent(
                event=event,
                message=message,
                data=data,
            )
        )

    def extend(
        self,
        events: List[
            Dict[str, Any]
        ],
    ) -> None:
        """
        Ajoute plusieurs événements déjà sérialisés.
        """

        for raw in (
            events
            or []
        ):

            if not isinstance(
                raw,
                dict,
            ):
                continue

            self.add(
                raw.get(
                    "event",
                    "unknown",
                ),
                message=(
                    raw.get(
                        "message"
                    )
                ),
                **(
                    raw.get(
                        "data"
                    )
                    or {}
                ),
            )

    def to_list(
        self,
    ) -> List[
        Dict[str, Any]
    ]:
        return [
            event.to_dict()
            for event
            in self._events
        ]

    def clear(
        self,
    ) -> None:
        self._events.clear()

    def __len__(
        self,
    ) -> int:
        return len(
            self._events
        )


def trace_context(
    collector: NaimaTraceCollector,
    context: Dict[str, Any],
) -> None:

    collector.add(
        "context_resolved",

        current_equation=(
            context.get(
                "current_equation"
            )
        ),

        initial_equation=(
            context.get(
                "initial_equation"
            )
        ),

        equation_type=(
            context.get(
                "equation_type"
            )
        ),

        is_new_problem=(
            context.get(
                "is_new_problem"
            )
        ),

        context_preserved=(
            context.get(
                "context_preserved"
            )
        ),

        extraction_consistent=(
            context.get(
                "extraction_consistent"
            )
        ),

        reason=(
            context.get(
                "reason"
            )
        ),
    )


def trace_validation(
    collector: NaimaTraceCollector,
    validation: Dict[str, Any],
) -> None:

    collector.add(
        "validation_completed",

        verdict=(
            validation.get(
                "verdict"
            )
        ),

        confidence=(
            validation.get(
                "confidence"
            )
        ),

        method=(
            validation.get(
                "method"
            )
        ),

        result_correct=(
            validation.get(
                "result_correct"
            )
        ),

        reasoning_correct=(
            validation.get(
                "reasoning_correct"
            )
        ),

        error_type=(
            validation.get(
                "error_type"
            )
        ),

        requires_review=(
            validation.get(
                "requires_review"
            )
        ),
    )


def trace_pedagogical(
    collector: NaimaTraceCollector,
    pedagogical: Dict[str, Any],
) -> None:

    policy = (
        pedagogical.get(
            "pedagogical_policy"
        )
        or {}
    )

    recovery = (
        pedagogical.get(
            "recovery_summary"
        )
        or {}
    )

    behavioral = (
        pedagogical.get(
            "behavioral_state"
        )
        or {}
    )

    cognitive = (
        pedagogical.get(
            "cognitive_control"
        )
        or {}
    )

    collector.add(
        "pedagogical_pipeline_completed",

        behavioral_state=(
            behavioral.get(
                "etat"
            )
        ),

        cognitive_level=(
            cognitive.get(
                "niveau"
            )
        ),

        strategy=(
            policy.get(
                "strategie"
            )
        ),

        help_level=(
            policy.get(
                "niveau_aide"
            )
        ),

        may_reveal_solution=(
            policy.get(
                "peut_reveler_solution"
            )
        ),

        recovery_phase=(
            recovery.get(
                "phase"
            )
        ),

        recovery_status=(
            recovery.get(
                "dernier_statut_recuperation"
            )
        ),
    )


def trace_response(
    collector: NaimaTraceCollector,
    response: Dict[str, Any],
) -> None:

    collector.add(
        "response_decision",

        response_type=(
            response.get(
                "response_type"
            )
        ),

        use_local_response=(
            response.get(
                "use_local_response"
            )
        ),

        use_llm=(
            response.get(
                "use_llm"
            )
        ),

        objective_reached=(
            response.get(
                "objective_reached"
            )
        ),

        keep_exercise_open=(
            response.get(
                "keep_exercise_open"
            )
        ),

        solution_leakage_blocked=(
            response.get(
                "solution_leakage_blocked"
            )
        ),

        reason=(
            response.get(
                "reason"
            )
        ),
    )


def build_turn_trace(
    turn_result: Dict[str, Any],
) -> List[
    Dict[str, Any]
]:
    """
    Produit une trace standardisée depuis un NaimaTurnResult.
    """

    collector = (
        NaimaTraceCollector()
    )

    collector.add(
        "turn_started",
        message=(
            turn_result.get(
                "message"
            )
        ),
    )

    trace_context(
        collector,
        turn_result.get(
            "context"
        )
        or {},
    )

    trace_validation(
        collector,
        turn_result.get(
            "validation"
        )
        or {},
    )

    trace_pedagogical(
        collector,
        turn_result.get(
            "pedagogical"
        )
        or {},
    )

    trace_response(
        collector,
        turn_result.get(
            "response"
        )
        or {},
    )

    collector.add(
        "turn_completed",

        equation_type=(
            turn_result.get(
                "equation_type"
            )
        ),

        handled_deterministically=(
            turn_result.get(
                "handled_deterministically"
            )
        ),

        requires_llm=(
            turn_result.get(
                "requires_llm"
            )
        ),

        objective_reached=(
            turn_result.get(
                "objective_reached"
            )
        ),
    )

    return collector.to_list()


def render_console_trace(
    events: List[
        Dict[str, Any]
    ],
) -> str:
    """
    Produit une représentation lisible pour le terminal.

    Ne fait volontairement pas print().
    """

    lines = []

    for event in (
        events
        or []
    ):

        event_name = (
            event.get(
                "event",
                "unknown",
            )
        )

        data = (
            event.get(
                "data"
            )
            or {}
        )

        if data:
            lines.append(
                f"[NAIMA V2] "
                f"{event_name} "
                f"{data}"
            )

        else:
            lines.append(
                f"[NAIMA V2] "
                f"{event_name}"
            )

    return "\n".join(
        lines
    )