"""Immutable permissions granted to a specialized agent."""

from dataclasses import dataclass, fields

from .exceptions import AgentContractError


@dataclass(frozen=True, slots=True)
class AgentPermissions:
    """Explicit capability grants; every permission is denied by default."""

    read_files: bool = False
    write_files: bool = False
    execute_code: bool = False
    network_access: bool = False
    memory_read: bool = False
    memory_write: bool = False
    agent_message_send: bool = False

    def __post_init__(self) -> None:
        if any(not isinstance(getattr(self, item.name), bool) for item in fields(self)):
            raise AgentContractError("permission grants must be bool values")
