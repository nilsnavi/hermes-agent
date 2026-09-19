"""Application orchestration facade for a future runtime migration.

The class intentionally accepts ports and does not know gateway, SQLite,
provider SDK, environment or subprocess details.
"""

from dataclasses import dataclass
from typing import Mapping, Optional

from hermes_core.application.delivery_service import DeliveryService
from hermes_core.application.execution_service import ExecutionService
from hermes_core.application.provider_router import ProviderRouter
from hermes_core.application.session_service import SessionService
from hermes_core.domain.delivery import DeliveryState
from hermes_core.domain.routing import RouteDecision, RoutePurpose
from hermes_core.domain.session import Session, SessionId, SessionKey


@dataclass(frozen=True)
class IncomingEvent:
    session_id: Optional[SessionId] = None
    session_key: Optional[SessionKey] = None
    owner: str = ""
    provider: Optional[str] = None
    model: Optional[str] = None
    purpose: RoutePurpose = RoutePurpose.MAIN


@dataclass(frozen=True)
class RuntimePlan:
    session: Session
    route: RouteDecision
    generation: int


class RuntimeApplication:
    def __init__(
        self,
        sessions: SessionService,
        providers: ProviderRouter,
        execution: ExecutionService,
        delivery: DeliveryService,
    ) -> None:
        self.sessions = sessions
        self.providers = providers
        self.execution = execution
        self.delivery = delivery

    def plan(self, event: IncomingEvent) -> RuntimePlan:
        if event.session_id is not None:
            session = self.sessions.resume(event.session_id)
        elif event.session_key is not None:
            session = self.sessions.resume_by_key(event.session_key)
        else:
            raise ValueError("event requires a session id or key")
        generation = self.sessions.acquire(session, event.owner)
        route = self.providers.route(provider=event.provider, model=event.model, purpose=event.purpose)
        return RuntimePlan(session=session, route=route, generation=generation)

    def finish(self, plan: RuntimePlan, owner: str) -> bool:
        return self.sessions.release(plan.session, owner, plan.generation)
