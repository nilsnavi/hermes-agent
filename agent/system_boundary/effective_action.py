"""Effective action classifier (Sprint 1.3.3 §12, §14, §16).

The immediate tool name is insufficient: chained execution that hides
a system mutation inside a generated script, shell wrapper or
background launch must be classified by its EFFECTIVE action.

Deterministic recognizer over a bounded grammar — NOT an LLM, NOT a
shell emulator. Unknown mutation-capable commands classify UNKNOWN
(mutation-capable) and the boundary blocks them.

Recognition coverage (§16):
- file redirection writers: echo > >>, cat >, printf >, tee
- file ops: cp mv rm install ln chmod chown truncate dd rsync
- in-place edits: sed -i, perl -pi
- python -c / python script, bash/sh -c, bash/sh script
- wrappers: nohup env setsid
- service control: systemctl (restart/stop/start/kill/enable/disable),
  service (restart/stop/start)
- package managers: apt apt-get dpkg yum dnf rpm pacman
- network/firewall: iptables nft ufw ip nmcli sysctl
- mount: mount umount
- containers: docker (run/exec/compose), podman, kubectl
- self control: hermes-gateway via systemctl/service/kill/pkill
"""

import re
import shlex
from dataclasses import dataclass, field
from typing import List, Optional

from .models import (
    EffectiveActionClass,
    EffectiveActionResult,
    OperationClass,
)

#: names of the Hermes gateway service / process (self-control targets)
_GATEWAY_NAMES = (
    "hermes-gateway",
    "hermes-gateway.service",
    "hermes-gateway.service:",
    "hermes",
)

_SYSTEMCTL_MUTATIONS = {
    "restart": OperationClass.SERVICE_RESTART,
    "stop": OperationClass.SERVICE_STOP,
    "start": OperationClass.SERVICE_START,
    "kill": OperationClass.PROCESS_KILL,
    "enable": OperationClass.SERVICE_ENABLE,
    "disable": OperationClass.SERVICE_DISABLE,
    "reload": OperationClass.SERVICE_RESTART,
    "force-reload": OperationClass.SERVICE_RESTART,
    "reset-failed": OperationClass.SERVICE_RESTART,
    "daemon-reload": OperationClass.SERVICE_RESTART,
}

_SERVICE_MUTATIONS = {
    "restart": OperationClass.SERVICE_RESTART,
    "stop": OperationClass.SERVICE_STOP,
    "start": OperationClass.SERVICE_START,
    "reload": OperationClass.SERVICE_RESTART,
    "force-reload": OperationClass.SERVICE_RESTART,
    "kill": OperationClass.PROCESS_KILL,
}

_PACKAGE_MANAGERS = {
    "apt": OperationClass.PACKAGE_INSTALL,
    "apt-get": OperationClass.PACKAGE_INSTALL,
    "aptitude": OperationClass.PACKAGE_INSTALL,
    "dpkg": OperationClass.PACKAGE_INSTALL,
    "yum": OperationClass.PACKAGE_INSTALL,
    "dnf": OperationClass.PACKAGE_INSTALL,
    "rpm": OperationClass.PACKAGE_INSTALL,
    "pacman": OperationClass.PACKAGE_INSTALL,
    "zypper": OperationClass.PACKAGE_INSTALL,
    "snap": OperationClass.PACKAGE_INSTALL,
    "flatpak": OperationClass.PACKAGE_INSTALL,
}

_NETWORK_MUTATORS = {
    "iptables": OperationClass.FIREWALL_CHANGE,
    "iptables-save": OperationClass.FIREWALL_CHANGE,
    "ip6tables": OperationClass.FIREWALL_CHANGE,
    "nft": OperationClass.FIREWALL_CHANGE,
    "ufw": OperationClass.FIREWALL_CHANGE,
    "firewalld": OperationClass.FIREWALL_CHANGE,
    "ip": OperationClass.NETWORK_CHANGE,
    "nmcli": OperationClass.NETWORK_CHANGE,
    "nmcli": OperationClass.NETWORK_CHANGE,
    "tc": OperationClass.NETWORK_CHANGE,
    "route": OperationClass.NETWORK_CHANGE,
    "ipset": OperationClass.NETWORK_CHANGE,
}

_MOUNT_OPS = {
    "mount": OperationClass.MOUNT_CONTROL,
    "umount": OperationClass.MOUNT_CONTROL,
    "swapoff": OperationClass.MOUNT_CONTROL,
    "swapon": OperationClass.MOUNT_CONTROL,
}

_CONTAINER_TOOLS = {
    "docker": OperationClass.CONTAINER_CONTROL,
    "podman": OperationClass.CONTAINER_CONTROL,
    "containerd": OperationClass.CONTAINER_CONTROL,
    "nerdctl": OperationClass.CONTAINER_CONTROL,
    "kubectl": OperationClass.CONTAINER_CONTROL,
    "helm": OperationClass.CONTAINER_CONTROL,
    "docker-compose": OperationClass.CONTAINER_CONTROL,
    "k3s": OperationClass.CONTAINER_CONTROL,
    "ctr": OperationClass.CONTAINER_CONTROL,
}

_KERNEL_OPS = {
    "sysctl": OperationClass.KERNEL_CONTROL,
    "modprobe": OperationClass.KERNEL_CONTROL,
    "rmmod": OperationClass.KERNEL_CONTROL,
    "insmod": OperationClass.KERNEL_CONTROL,
    "kexec": OperationClass.KERNEL_CONTROL,
}

#: commands that only read (never mutate) — used to short-circuit
_READ_ONLY_COMMANDS = {
    "cat", "ls", "less", "more", "head", "tail", "grep", "find",
    "stat", "df", "du", "ps", "top", "htop", "free", "uname", "id",
    "whoami", "date", "hostname", "uptime", "wc", "sort", "cut",
    "awk", "sed", "env", "printenv", "echo", "printf", "pwd", "which",
    "whereis", "type", "getent", "dig", "nslookup", "ping", "traceroute",
    "curl", "wget", "git status", "git log", "git diff", "git branch",
    "journalctl", "dmesg", "uptime", "ss", "netstat", "lsof",
    "systemctl status", "systemctl show", "systemctl cat",
    "systemctl list-units", "systemctl --user status",
    "systemctl --user show", "systemctl --user list-units",
    "service --status-all", "systemctl is-active", "systemctl is-enabled",
    "systemctl is-system-running",
}

_SCRIPT_WRAPPERS = {
    "bash", "sh", "zsh", "dash", "ksh", "ash",
}

_SHELL_INVOKERS = ("bash", "sh", "zsh", "dash", "ksh", "ash", "fish")

#: file-write operators that make a command a mutation
_WRITE_REDIRECT_RE = re.compile(r"(^|\s)(>|>>|1>|2>|&>|<>)\s*\S")
_WRITE_TOOLS = {
    "tee", "install", "truncate", "dd", "rsync", "mkfs", "mkfs.ext4",
    "mkfs.xfs", "fdisk", "parted", "pvcreate", "vgcreate", "lvcreate",
    "xfs_growfs", "resize2fs", "mkswap",
}

_DELETE_TOOLS = {"rm", "rmdir", "unlink"}
_MOVE_TOOLS = {"mv", "rename"}
_COPY_TOOLS = {"cp", "scp", "rsync", "cpio", "tar", "zip", "unzip", "gzip",
               "xz", "bzip2", "7z"}
_LINK_TOOLS = {"ln", "symlink"}
_PERM_TOOLS = {"chmod", "chown", "chgrp", "chattr", "lsattr", "setfacl",
               "setcap", "usermod", "groupmod", "useradd", "userdel",
               "groupadd", "groupdel", "passwd", "chage"}
_SED_INPLACE_RE = re.compile(r"^(sed|perl)\b[^\n]*(\s-i\b|--in-place\b)")
_PYTHON_RE = re.compile(r"^(python3?|pypy3?|python -c|python3 -c)\b")
_PY_WRITE_RE = re.compile(r"open\s*\([^)]*['\"][rwa]")
_SUBPROCESS_RE = re.compile(r"subprocess|os\.system|os\.popen|Popen|run\(")
_EXEC_FAMILY_RE = re.compile(r"\b(exec|execve|posix_spawn|system)\b")

#: commands whose mutation flavor is encoded in the subcommand
_DOCKER_MUTATING_SUBCOMMANDS = ("run", "exec", "create", "rm", "rmi",
                                "build", "pull", "push", "save", "load",
                                "tag", "commit", "stop", "start",
                                "restart", "kill", "pause", "unpause",
                                "volume", "network", "compose", "up",
                                "down", "logs", "cp", "rename")

_KUBECTL_MUTATING_SUBCOMMANDS = ("apply", "create", "delete", "edit",
                                 "patch", "replace", "scale", "rollout",
                                 "drain", "cordon", "uncordon", "exec",
                                 "run", "port-forward", "label", "annotate",
                                 "taint", "autoscale", "set", "expose")

#: commands that mutate a package store
_PACKAGE_MUTATION_SUBCOMMANDS = (
    "install", "remove", "purge", "upgrade", "dist-upgrade", "update",
    "autoremove", "autoclean", "clean", "reinstall", "configure",
    "unpack", "add", "del", "delete", "erase", "download", "hold",
    "unhold", "mark", "sync", "refresh",
)


def _tokenize(command: str) -> List[str]:
    """Tokenize a command line with shlex (POSIX-ish, safe)."""
    try:
        return shlex.split(command)
    except ValueError:
        # unbalanced quotes — split on whitespace as a fallback
        return command.split()


def _is_gateway(name: str) -> bool:
    n = name.strip().rstrip(".").lower()
    if n in _GATEWAY_NAMES:
        return True
    # systemctl unit names can be "hermes-gateway.service" or with
    # an instance suffix like "hermes-gateway@x"
    if n.startswith("hermes-gateway"):
        return True
    return False


def _classify_systemctl(tokens: List[str],
                        idx: int) -> Optional[EffectiveActionResult]:
    """tokens[idx] == 'systemctl'. Returns None when read-only."""
    rest = tokens[idx + 1:]
    # skip options (--user, --system, -H, etc.)
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        if rest[i] in ("-H", "--host", "-M", "--machine",
                       "--root", "--image", "--global"):
            i += 2  # option with a value
            continue
        i += 1  # plain flag (--user, --system, --no-pager, ...)
    if i >= len(rest):
        return None  # bare systemctl with no action — unknown but no
        # recognized mutation
        # actually: bare 'systemctl' alone is not a mutation
    verb = rest[i]
    if verb == "status" or verb in ("show", "cat", "list-units",
                                    "list-unit-files", "is-active",
                                    "is-enabled", "is-system-running",
                                    "help", "get-default"):
        return None
    op = _SYSTEMCTL_MUTATIONS.get(verb)
    if op is None:
        # unknown systemctl verb — mutation-capable unknown
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.UNKNOWN,
            operation_class=OperationClass.UNKNOWN,
            targets=rest[i + 1:i + 2],
            is_mutation=True,
            confidence=0.5,
        )
    target = rest[i + 1] if i + 1 < len(rest) else ""
    targets = [target] if target else []
    self_control = any(_is_gateway(t) for t in targets)
    eff = (
        EffectiveActionClass.SERVICE_RESTART
        if op in (OperationClass.SERVICE_RESTART,
                  OperationClass.SERVICE_STOP)
        else EffectiveActionClass.PROCESS_CONTROL
    )
    if self_control:
        eff = EffectiveActionClass.PROCESS_SELF_CONTROL
    return EffectiveActionResult(
        effective_action_class=eff,
        operation_class=op,
        targets=targets,
        self_control=self_control,
        is_mutation=True,
        confidence=0.99,
    )


def _classify_service(tokens: List[str],
                      idx: int) -> Optional[EffectiveActionResult]:
    rest = tokens[idx + 1:]
    if not rest:
        return None
    verb = rest[0]
    if verb in ("--status-all",):
        return None
    op = _SERVICE_MUTATIONS.get(verb)
    if op is None:
        # service NAME ACTION form: 'service nginx restart'
        if len(rest) >= 2:
            op = _SERVICE_MUTATIONS.get(rest[1])
            if op is not None:
                return _service_result(op, rest[0], rest[1])
        # 'service nginx status' is a read
        if verb in ("status",) or (len(rest) >= 2 and
                                    rest[1] in ("status",)):
            return None
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.UNKNOWN,
            operation_class=OperationClass.UNKNOWN,
            is_mutation=True, confidence=0.5,
        )
    target = rest[1] if len(rest) > 1 else ""
    return _service_result(op, target, verb)


def _service_result(op: OperationClass, target: str,
                    verb: str) -> EffectiveActionResult:
    targets = [target] if target else []
    self_control = any(_is_gateway(t) for t in targets)
    eff = (
        EffectiveActionClass.SERVICE_RESTART
        if op in (OperationClass.SERVICE_RESTART,
                  OperationClass.SERVICE_STOP)
        else EffectiveActionClass.PROCESS_CONTROL
    )
    if self_control:
        eff = EffectiveActionClass.PROCESS_SELF_CONTROL
    return EffectiveActionResult(
        effective_action_class=eff,
        operation_class=op,
        targets=targets,
        self_control=self_control,
        is_mutation=True,
        confidence=0.99,
    )


def _classify_kill(tokens: List[str], idx: int,
                   cmdline: str) -> Optional[EffectiveActionResult]:
    """kill / pkill / killall — process control."""
    rest = tokens[idx + 1:]
    targets = [t for t in rest if not t.startswith("-")]
    # pkill -f hermes-gateway: the pattern is the target
    self_control = any(_is_gateway(t) or "hermes-gateway" in t
                       for t in targets)
    eff = EffectiveActionClass.PROCESS_KILL
    if self_control:
        eff = EffectiveActionClass.PROCESS_SELF_CONTROL
    return EffectiveActionResult(
        effective_action_class=eff,
        operation_class=OperationClass.PROCESS_KILL,
        targets=targets,
        self_control=self_control,
        is_mutation=True,
        confidence=0.98,
    )


def _classify_package_manager(tokens: List[str],
                              idx: int) -> Optional[EffectiveActionResult]:
    tool = tokens[idx]
    rest = tokens[idx + 1:]
    # apt-get update is a mutation (package state), apt-cache is read
    if tool in ("apt-cache", "apt-config", "dpkg-query", "dpkg -l"):
        return None
    if not rest:
        return None  # bare apt — no mutation
    verb = rest[0].lstrip("-")
    if verb in ("search", "show", "list", "policy", "depends",
                "rdepends", "why", "changelog", "madison"):
        return None
    targets = [t for t in rest[1:] if not t.startswith("-")]
    return EffectiveActionResult(
        effective_action_class=EffectiveActionClass.PACKAGE_CHANGE,
        operation_class=OperationClass.PACKAGE_INSTALL,
        targets=targets[:4],
        is_mutation=True,
        confidence=0.97,
    )


def _classify_network(tokens: List[str],
                      idx: int) -> Optional[EffectiveActionResult]:
    tool = tokens[idx]
    rest = tokens[idx + 1:]
    if tool == "ip" and rest and rest[0] in ("addr", "address", "link",
                                             "route", "neigh"):
        # 'ip addr show' / 'ip link show' are reads
        if len(rest) >= 2 and rest[1] in ("show", "list", "help"):
            return None
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.NETWORK_CHANGE,
            operation_class=OperationClass.NETWORK_CHANGE,
            targets=rest[:2], is_mutation=True, confidence=0.95,
        )
    if tool in ("nft", "iptables", "ip6tables", "ufw", "firewalld"):
        if rest and rest[0] in ("list", "status", "show", "--list",
                                "--status", "stat"):
            return None
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.FIREWALL_CHANGE,
            operation_class=OperationClass.FIREWALL_CHANGE,
            targets=rest[:2], is_mutation=True, confidence=0.97,
        )
    if tool == "nmcli":
        if rest and rest[0] in ("general", "device", "radio", "networking"):
            # nmcli device status / nmcli general status are reads
            if len(rest) >= 2 and rest[1] in ("status", "show", "list"):
                return None
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.NETWORK_CHANGE,
            operation_class=OperationClass.NETWORK_CHANGE,
            targets=rest[:2], is_mutation=True, confidence=0.94,
        )
    return None


def _classify_container(tokens: List[str],
                        idx: int) -> Optional[EffectiveActionResult]:
    tool = tokens[idx]
    rest = tokens[idx + 1:]
    verb = rest[0] if rest else ""
    # docker compose is a subcommand tree
    if tool == "docker" and verb == "compose":
        sub = rest[1] if len(rest) > 1 else ""
        if sub in ("up", "down", "start", "stop", "restart", "build",
                   "pull", "push", "run", "exec", "rm", "kill"):
            return EffectiveActionResult(
                effective_action_class=EffectiveActionClass.CONTAINER_CONTROL,
                operation_class=OperationClass.CONTAINER_CONTROL,
                targets=rest[2:4], is_mutation=True, confidence=0.97,
            )
        return None
    mutating = (_DOCKER_MUTATING_SUBCOMMANDS if tool in
                ("docker", "podman", "nerdctl", "containerd", "ctr")
                else _KUBECTL_MUTATING_SUBCOMMANDS)
    if verb in mutating:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.CONTAINER_CONTROL,
            operation_class=OperationClass.CONTAINER_CONTROL,
            targets=rest[1:3], is_mutation=True, confidence=0.97,
        )
    # docker ps / docker images / kubectl get are reads
    return None


def _classify_shell_invocation(tokens: List[str], idx: int,
                               cmdline: str) -> Optional[EffectiveActionResult]:
    """bash -c '...' / sh script.sh / bash script → EXECUTE_SCRIPT."""
    rest = tokens[idx + 1:]
    if not rest:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.EXECUTE_BINARY,
            operation_class=OperationClass.EXECUTE_BINARY,
            is_mutation=True, confidence=0.9,
        )
    if rest[0] == "-c" and len(rest) >= 2:
        inner = rest[1]
        inner_result = classify_command(inner)
        if inner_result.is_system_control:
            eff = EffectiveActionClass.INDIRECT_SYSTEM_CONTROL
        elif inner_result.is_mutation:
            eff = EffectiveActionClass.INDIRECT_SYSTEM_CONTROL \
                if inner_result.effective_action_class in (
                    EffectiveActionClass.SERVICE_CONTROL,
                    EffectiveActionClass.SERVICE_RESTART,
                    EffectiveActionClass.SERVICE_STOP,
                    EffectiveActionClass.PROCESS_CONTROL,
                    EffectiveActionClass.PROCESS_KILL,
                    EffectiveActionClass.PACKAGE_CHANGE,
                    EffectiveActionClass.NETWORK_CHANGE,
                    EffectiveActionClass.FIREWALL_CHANGE,
                    EffectiveActionClass.CONTAINER_CONTROL,
                    EffectiveActionClass.KERNEL_CONTROL,
                ) else inner_result.effective_action_class
        else:
            # bash -c always EXECUTES code — even benign code is a
            # script execution, never a bare READ
            eff = EffectiveActionClass.EXECUTE_SCRIPT
        return EffectiveActionResult(
            effective_action_class=eff,
            operation_class=inner_result.operation_class,
            targets=inner_result.targets,
            self_control=inner_result.self_control,
            is_mutation=True,
            wrappers=[tokens[idx]],
            confidence=0.95,
        )
    # bash script.sh — script execution
    script = rest[0] if rest and not rest[0].startswith("-") else None
    return EffectiveActionResult(
        effective_action_class=EffectiveActionClass.EXECUTE_SCRIPT,
        operation_class=OperationClass.EXECUTE_SCRIPT,
        targets=[script] if script else [],
        is_mutation=True,
        wrappers=[tokens[idx]],
        confidence=0.9,
    )


def _classify_python(tokens: List[str], idx: int,
                     cmdline: str) -> Optional[EffectiveActionResult]:
    rest = tokens[idx + 1:]
    code = ""
    if rest and rest[0] == "-c" and len(rest) >= 2:
        code = rest[1]
    elif rest and not rest[0].startswith("-"):
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.EXECUTE_SCRIPT,
            operation_class=OperationClass.EXECUTE_SCRIPT,
            targets=[rest[0]], is_mutation=True, wrappers=["python"],
            confidence=0.9,
        )
    if code:
        write = bool(_PY_WRITE_RE.search(code))
        sub = bool(_SUBPROCESS_RE.search(code))
        sys = bool(_EXEC_FAMILY_RE.search(code)) or sub
        self_control = "hermes-gateway" in code and \
            ("systemctl" in code or "restart" in code or "kill" in code)
        eff = EffectiveActionClass.INDIRECT_SYSTEM_CONTROL if sys \
            else (EffectiveActionClass.WRITE_FILE if write
                  else EffectiveActionClass.UNKNOWN)
        if self_control:
            eff = EffectiveActionClass.PROCESS_SELF_CONTROL
        return EffectiveActionResult(
            effective_action_class=eff,
            operation_class=OperationClass.EXECUTE_SCRIPT if sys
            else (OperationClass.WRITE if write else OperationClass.UNKNOWN),
            targets=["hermes-gateway"] if self_control else [],
            self_control=self_control,
            is_mutation=True,
            wrappers=["python"],
            confidence=0.92,
        )
    return None


def _classify_inline_code(tokens: List[str],
                          cmdline: str) -> EffectiveActionResult:
    """python -c CODE / bash -c CODE — classify the code body itself."""
    first = tokens[0]
    code = " ".join(tokens[2:]) if len(tokens) > 2 else ""
    if first in _SHELL_INVOKERS:
        return _classify_shell_invocation(tokens, 0, cmdline)
    if first.startswith("python") or first in ("pypy", "pypy3"):
        return _classify_python(tokens, 0, cmdline)
    # wrapper with -c (e.g. nohup python -c ...): classify the code
    inner = classify_command(" ".join(tokens[1:]))
    return EffectiveActionResult(
        effective_action_class=inner.effective_action_class,
        operation_class=inner.operation_class,
        targets=inner.targets,
        self_control=inner.self_control,
        is_mutation=inner.is_mutation,
        wrappers=[first] + inner.wrappers,
        confidence=inner.confidence,
    )


def _classify_wrapper(tokens: List[str], idx: int,
                      cmdline: str) -> Optional[EffectiveActionResult]:
    """nohup / env / setsid — pass-through wrappers."""
    rest = tokens[idx + 1:]
    if not rest:
        return None
    # env VAR=1 cmd ... → skip VAR= assignments
    j = 0
    while j < len(rest) and "=" in rest[j] and not rest[j].startswith("-"):
        j += 1
    inner = " ".join(rest[j:])
    if not inner:
        return None
    # an inner path (e.g. /tmp/hgw_reload.sh or ./run.sh) is a script
    # execution — classify by script semantics (§14)
    first = rest[j] if j < len(rest) else ""
    if "/" in first or first.endswith(".sh") or first.endswith(".py") \
            or first.endswith(".bash") or first.endswith(".pl"):
        eff = EffectiveActionClass.EXECUTE_SCRIPT
        op = OperationClass.EXECUTE_SCRIPT
        self_control = False
        # if the script artifact is known to contain a system-control
        # command, its lineage classifies it as INDIRECT_SYSTEM_CONTROL
        # (§13) — resolved by the artifact lineage store at boundary
        # level; the classifier marks it mutation-capable here.
        return EffectiveActionResult(
            effective_action_class=eff,
            operation_class=op,
            targets=[first],
            self_control=self_control,
            is_mutation=True,
            wrappers=[tokens[idx]],
            confidence=0.9,
        )
    inner_result = classify_command(inner)
    return EffectiveActionResult(
        effective_action_class=inner_result.effective_action_class,
        operation_class=inner_result.operation_class,
        targets=inner_result.targets,
        self_control=inner_result.self_control,
        is_mutation=inner_result.is_mutation,
        wrappers=[tokens[idx]] + inner_result.wrappers,
        confidence=inner_result.confidence,
    )


def _classify_sed_inplace(cmdline: str) -> bool:
    return bool(_SED_INPLACE_RE.match(cmdline.strip()))


def classify_command(command: str) -> EffectiveActionResult:
    """Classify one shell command line by its EFFECTIVE action.

    Deterministic; never raises; never returns a confident READ for an
    unknown mutation-capable command.
    """
    if not command or not command.strip():
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.READ,
            operation_class=OperationClass.READ,
            targets=[], is_mutation=False, confidence=1.0,
        )
    cmdline = command.strip()

    # trailing background '&' / '&>' — still the same effective command
    stripped = cmdline.rstrip()
    if stripped.endswith("&") and not stripped.endswith("&&"):
        stripped = stripped.rstrip("&").strip()

    # shell operators: capture the LEFT side as the primary command but
    # scan the whole line for mutation markers. NOTE: python/bash -c
    # bodies may contain ';' — handle those BEFORE splitting.
    first_token = stripped.split()[0] if stripped.split() else ""
    if first_token in _SHELL_INVOKERS or first_token.startswith("python") \
            or first_token in ("pypy", "pypy3") or first_token in (
                "nohup", "setsid", "env", "sudo", "doas", "su",
                "runuser", "systemd-run", "timeout", "watch", "xargs"):
        try:
            tokens0 = _tokenize(stripped)
        except Exception:
            tokens0 = []
        if tokens0 and len(tokens0) >= 3 and tokens0[1] == "-c":
            return _classify_inline_code(tokens0, cmdline)
        if tokens0 and tokens0[0] in ("bash", "sh", "zsh", "dash",
                                      "ksh", "ash", "fish"):
            return _classify_shell_invocation(tokens0, 0, cmdline)
        if tokens0 and (tokens0[0].startswith("python")
                        or tokens0[0] in ("pypy", "pypy3")):
            return _classify_python(tokens0, 0, cmdline)

    whole = cmdline
    for op in (";", "&&", "||"):
        if op in whole:
            parts = whole.split(op)
            # classify each segment; the union must be conservative
            results = [classify_command(p.strip()) for p in parts]
            any_mutation = any(r.is_mutation for r in results)
            any_self = any(r.self_control for r in results)
            targets: List[str] = []
            for r in results:
                for t in r.targets:
                    if t not in targets:
                        targets.append(t)
            if any_self:
                # multi-segment chain with self-control → the EFFECTIVE
                # action is indirect system control (§12): the script
                # body hides systemctl behind another command
                return EffectiveActionResult(
                    effective_action_class=EffectiveActionClass
                    .INDIRECT_SYSTEM_CONTROL,
                    operation_class=OperationClass.SERVICE_RESTART,
                    targets=targets, self_control=True,
                    is_mutation=True, confidence=0.99,
                )
            if any_mutation:
                first_mut = next(r for r in results if r.is_mutation)
                return EffectiveActionResult(
                    effective_action_class=first_mut
                    .effective_action_class,
                    operation_class=first_mut.operation_class,
                    targets=targets,
                    is_mutation=True,
                    confidence=0.95,
                )
            return results[0]

    # redirection write markers anywhere in the line — even echo/printf
    # with a redirect writes a file (§16: echo > file is a mutation)
    if _WRITE_REDIRECT_RE.search(whole):
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.WRITE_FILE,
            operation_class=OperationClass.WRITE,
            is_mutation=True, confidence=0.95,
        )

    try:
        tokens = _tokenize(stripped)
    except Exception:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.UNKNOWN,
            operation_class=OperationClass.UNKNOWN,
            is_mutation=True, confidence=0.5,
        )
    if not tokens:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.READ,
            operation_class=OperationClass.READ,
            is_mutation=False, confidence=1.0,
        )

    head = tokens[0]

    # wrappers that pass through to the inner command
    if head in ("nohup", "setsid", "env", "time", "nice", "ionice",
                "chrt", "stdbuf", "timeout", "xargs", "sudo", "doas",
                "su", "runuser", "systemd-run", "watch"):
        r = _classify_wrapper(tokens, 0, cmdline)
        if r is not None:
            return r

    if head in _SHELL_INVOKERS:
        return _classify_shell_invocation(tokens, 0, cmdline)

    if head.startswith("python") or head in ("pypy", "pypy3"):
        return _classify_python(tokens, 0, cmdline)

    if head == "systemctl":
        r = _classify_systemctl(tokens, 0)
        if r is not None:
            return r
        return _read_result()

    if head == "service":
        r = _classify_service(tokens, 0)
        if r is not None:
            return r
        return _read_result()

    if head in ("kill", "pkill", "killall", "skill", "pgrep -f"):
        return _classify_kill(tokens, 0, cmdline)

    if head in _PACKAGE_MANAGERS:
        r = _classify_package_manager(tokens, 0)
        if r is not None:
            return r
        return _read_result()

    if head in _NETWORK_MUTATORS:
        r = _classify_network(tokens, 0)
        if r is not None:
            return r
        return _read_result()

    if head in _MOUNT_OPS:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.KERNEL_CONTROL
            if head == "sysctl" else EffectiveActionClass.NETWORK_CHANGE,
            operation_class=_MOUNT_OPS[head],
            is_mutation=True, confidence=0.96,
        )

    if head in _KERNEL_OPS:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.KERNEL_CONTROL,
            operation_class=_KERNEL_OPS[head],
            is_mutation=True, confidence=0.97,
        )

    if head in _CONTAINER_TOOLS:
        r = _classify_container(tokens, 0)
        if r is not None:
            return r
        return _read_result()

    if head in _DELETE_TOOLS:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.DELETE_FILE,
            operation_class=OperationClass.DELETE,
            targets=tokens[1:3], is_mutation=True, confidence=0.98,
        )
    if head in _MOVE_TOOLS:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.MOVE_FILE,
            operation_class=OperationClass.MOVE,
            targets=tokens[1:3], is_mutation=True, confidence=0.98,
        )
    if head in _COPY_TOOLS:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.WRITE_FILE,
            operation_class=OperationClass.COPY,
            targets=tokens[1:3], is_mutation=True, confidence=0.95,
        )
    if head in _LINK_TOOLS:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.WRITE_FILE,
            operation_class=OperationClass.LINK,
            targets=tokens[1:3], is_mutation=True, confidence=0.95,
        )
    if head in _PERM_TOOLS:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.PERMISSION_CHANGE,
            operation_class=OperationClass.PERMISSION_CHANGE,
            targets=tokens[1:3], is_mutation=True, confidence=0.97,
        )
    if _SED_INPLACE_RE.match(cmdline.strip()):
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.WRITE_FILE,
            operation_class=OperationClass.PATCH,
            targets=tokens[1:3], is_mutation=True, confidence=0.95,
        )
    if head in _WRITE_TOOLS:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass.WRITE_FILE,
            operation_class=OperationClass.WRITE,
            targets=tokens[1:3], is_mutation=True, confidence=0.95,
        )
    if head in _READ_ONLY_COMMANDS:
        return _read_result()

    # unknown command → mutation-capable UNKNOWN (never confident READ)
    return EffectiveActionResult(
        effective_action_class=EffectiveActionClass.UNKNOWN,
        operation_class=OperationClass.UNKNOWN,
        targets=[], is_mutation=True, confidence=0.5,
    )


def _READ_ONLY_COMMANDS_contain(whole: str) -> bool:
    head = whole.strip().split()[0] if whole.strip() else ""
    return head in ("echo", "printf", "cat") and \
        (">" in whole)


def _read_result() -> EffectiveActionResult:
    return EffectiveActionResult(
        effective_action_class=EffectiveActionClass.READ,
        operation_class=OperationClass.READ,
        is_mutation=False, confidence=1.0,
    )


def classify_script(content: str,
                    artifact_path: str = "") -> EffectiveActionResult:
    """Classify a script's content — the artifact lineage case (§13):
    a generated script whose body contains a system-control command is
    an INDIRECT_SYSTEM_CONTROL even before it executes."""
    stripped = (content or "").strip()
    if not stripped:
        return _read_result()
    # ignore shebang line
    lines = [ln for ln in stripped.splitlines()
             if ln.strip() and not ln.strip().startswith("#!")]
    body = "\n".join(lines) if lines else stripped

    result = classify_command(body)
    if result.self_control:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass
            .INDIRECT_SYSTEM_CONTROL,
            operation_class=result.operation_class,
            targets=result.targets,
            self_control=True,
            is_mutation=True,
            wrappers=["script:" + artifact_path] + result.wrappers,
            confidence=0.99,
        )
    if result.is_mutation:
        return EffectiveActionResult(
            effective_action_class=EffectiveActionClass
            .INDIRECT_SYSTEM_CONTROL
            if result.is_system_control else result.effective_action_class,
            operation_class=result.operation_class,
            targets=result.targets,
            self_control=result.self_control,
            is_mutation=True,
            wrappers=["script:" + artifact_path] + result.wrappers,
            confidence=0.97,
        )
    return result


__all__ = [
    "classify_command",
    "classify_script",
]
