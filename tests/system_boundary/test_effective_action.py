"""Sprint 1.3.3 §12/§14/§61/§28 — EFFECTIVE ACTION security (P0).

The immediate tool name is NOT enough: chained execution that hides a
system mutation inside a generated script / shell wrapper / background
launch must be classified by its EFFECTIVE action and blocked BEFORE
the adapter runs.

The canonical P0 scenario from §12:

    write_file("/tmp/hgw_reload.sh",
               "sleep 8; systemctl --user restart hermes-gateway")
        ↓
    background / shell launch
        ↓
    systemctl --user restart hermes-gateway

    → EXECUTE_SCRIPT → INDIRECT_SYSTEM_CONTROL → SERVICE_RESTART
      → target=hermes-gateway → PROCESS_SELF_CONTROL_FORBIDDEN
      → BLOCK, adapter calls = 0
"""

import pytest

from agent.system_boundary import effective_action as ea
from agent.system_boundary import models as m


# ── §61.A the canonical P0 script ───────────────────────────────────

def test_p0_write_file_script_with_systemctl_restart_gateway():
    """write_file('/tmp/hgw_reload.sh', 'sleep 8; systemctl --user
    restart hermes-gateway') → effective action SERVICE_RESTART of
    hermes-gateway → self-control forbidden."""
    script = "sleep 8; systemctl --user restart hermes-gateway"
    result = ea.classify_script(script, artifact_path="/tmp/hgw_reload.sh")
    assert result.effective_action_class == \
        m.EffectiveActionClass.INDIRECT_SYSTEM_CONTROL
    assert result.operation_class == m.OperationClass.SERVICE_RESTART
    assert "hermes-gateway" in result.targets
    assert result.self_control is True
    # The chain must be classified as mutation-capable and dangerous
    assert result.is_mutation


def test_p0_script_execution_rejected_by_boundary():
    """Executing the artifact must produce a BLOCK decision with
    PROCESS_SELF_CONTROL_FORBIDDEN and zero adapter calls."""
    from agent.system_boundary.boundary import SystemBoundaryLayer

    sbl = SystemBoundaryLayer(mode="enforce")
    script = "sleep 8; systemctl --user restart hermes-gateway"
    ea.classify_script(script, artifact_path="/tmp/hgw_reload.sh")
    # classify_script is deterministic; the boundary decides on it
    decision = sbl.authorize_command(
        command=script,
        tool_name="shell_exec",
        capability="SYSTEM_EXEC",
        cwd="/tmp",
    )
    assert decision.verdict == "BLOCK"
    assert decision.reason_code == "PROCESS_SELF_CONTROL_FORBIDDEN"
    assert decision.effective_action_class == \
        m.EffectiveActionClass.INDIRECT_SYSTEM_CONTROL


# ── §61.B bash -c wrapper ───────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "bash -c \"systemctl --user restart hermes-gateway\"",
    "sh -c 'systemctl --user restart hermes-gateway'",
    "bash -c 'systemctl restart hermes-gateway'",
])
def test_p0_bash_c_systemctl_restart_gateway_blocked(cmd):
    r = ea.classify_command(cmd)
    assert r.self_control is True
    assert r.effective_action_class == \
        m.EffectiveActionClass.INDIRECT_SYSTEM_CONTROL
    assert "hermes-gateway" in r.targets


# ── §61.C python subprocess ─────────────────────────────────────────

def test_p0_python_subprocess_systemctl_restart_gateway():
    cmd = ("python3 -c \"import subprocess; "
           "subprocess.run(['systemctl', '--user', 'restart', "
           "'hermes-gateway'])\"")
    r = ea.classify_command(cmd)
    assert r.self_control is True
    assert r.operation_class in (m.OperationClass.EXECUTE_SCRIPT,
                                 m.OperationClass.SERVICE_RESTART)


# ── §61.D nohup / background ────────────────────────────────────────

def test_p0_nohup_script_restart_gateway():
    cmd = "nohup /tmp/hgw_reload.sh"
    r = ea.classify_command(cmd)
    # EXECUTE_SCRIPT mutation is sufficient to BLOCK in enforce mode;
    # the artifact lineage (script content) is resolved at boundary
    # level — the classifier marks the chain mutation-capable.
    assert r.is_mutation is True
    assert r.effective_action_class == \
        m.EffectiveActionClass.EXECUTE_SCRIPT


def test_p0_background_ampersand_script():
    cmd = "/tmp/hgw_reload.sh &"
    r = ea.classify_command(cmd)
    assert r.is_mutation


# ── §61.E env / sh wrapper ──────────────────────────────────────────

def test_p0_env_wrapper_restart_gateway():
    cmd = "env VAR=x systemctl --user restart hermes-gateway"
    r = ea.classify_command(cmd)
    assert r.self_control is True
    assert "hermes-gateway" in r.targets


# ── §28 self-control prohibition ────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "systemctl --user restart hermes-gateway",
    "systemctl --user stop hermes-gateway",
    "systemctl --user kill hermes-gateway",
    "service hermes-gateway restart",
    "systemctl restart hermes-gateway.service",
    "pkill -f hermes-gateway",
    "kill $(pgrep -f hermes-gateway)",
])
def test_self_control_variants_blocked(cmd):
    r = ea.classify_command(cmd)
    assert r.self_control is True, f"should detect self control: {cmd}"


def test_self_control_by_pid_at_boundary_level():
    """kill <gateway_pid> is self-control — detected by the SBL with
    knowledge of the gateway PID set (the bare classifier cannot know
    which PID belongs to the gateway)."""
    from agent.system_boundary.boundary import SystemBoundaryLayer

    sbl = SystemBoundaryLayer(mode="enforce",
                              gateway_pids={309121, 424242})
    d = sbl.authorize_command("kill 309121", tool_name="shell_exec",
                              capability="SYSTEM_EXEC", cwd="/")
    assert d.verdict == "BLOCK"
    assert d.reason_code == "PROCESS_SELF_CONTROL_FORBIDDEN"
    assert d.affected_processes == ["309121"]


# ── read-only commands stay read ────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "systemctl status nginx",
    "systemctl --user show hermes-gateway -p MainPID",
    "ps aux | grep hermes",
    "cat /etc/nginx/nginx.conf",
    "grep restart /etc/config",
])
def test_read_only_commands_not_mutation(cmd):
    r = ea.classify_command(cmd)
    assert r.is_mutation is False, f"should be read-only: {cmd}"
    assert r.effective_action_class == m.EffectiveActionClass.READ


# ── §16 shell security matrix: mutation must be detected ────────────

@pytest.mark.parametrize("cmd", [
    "echo x > /etc/foo",
    "echo x >> /etc/foo",
    "cat > /etc/foo",
    "printf x > /etc/foo",
    "tee /etc/foo",
    "cp /a /etc/foo",
    "mv /a /etc/foo",
    "rm /etc/foo",
    "install /a /etc/foo",
    "ln -s /a /etc/foo",
    "chmod 777 /etc/foo",
    "chown root /etc/foo",
    "truncate -s 0 /etc/foo",
    "dd if=/dev/zero of=/etc/foo",
    "rsync /a /etc/foo",
    "sed -i s/x/y/ /etc/foo",
    "perl -pi -e s/x/y/ /etc/foo",
    "python3 -c \"open('/etc/foo','w')\"",
    "apt install nginx",
    "apt-get remove nginx",
    "dpkg -i x.deb",
    "yum install nginx",
    "dnf upgrade",
    "rpm -i x.rpm",
    "pacman -S nginx",
    "iptables -A INPUT -j DROP",
    "nft add rule inet filter input drop",
    "ufw enable",
    "ip link set eth0 down",
    "nmcli con up eth0",
    "sysctl -w net.ipv4.ip_forward=1",
    "mount /dev/sda1 /mnt",
    "umount /mnt",
    "docker run --rm nginx",
    "docker compose up -d",
    "docker exec -it app bash",
    "podman run nginx",
    "kubectl apply -f x.yaml",
])
def test_shell_security_matrix_mutations_detected(cmd):
    r = ea.classify_command(cmd)
    assert r.is_mutation is True, f"mutation not detected: {cmd}"
    assert r.effective_action_class != m.EffectiveActionClass.READ


def test_unknown_mutation_capable_command_blocks():
    """An unrecognized mutation-capable command must NOT silently pass
    — it classifies UNKNOWN (mutation-capable) and the boundary BLOCKs
    (§14/§16)."""
    r = ea.classify_command("some_obscure_tool --mangle /etc/foo")
    # The classifier must either recognize a mutation or return a
    # mutation-capable UNKNOWN — never a confident READ.
    assert r.is_mutation is True or r.effective_action_class == \
        m.EffectiveActionClass.UNKNOWN


# ── indirect execution wrappers (§14) ───────────────────────────────

@pytest.mark.parametrize("cmd", [
    "bash script.sh",
    "sh script.sh",
    "nohup script.sh",
    "setsid script.sh",
    "env FOO=1 script.sh",
    "python3 script.py",
    "bash -c 'echo hi'",
])
def test_indirect_execution_wrappers_recognized(cmd):
    r = ea.classify_command(cmd)
    # Wrappers are at minimum mutation-capable UNKNOWN or better
    # classified; a plain READ classification is a failure.
    assert r.effective_action_class in (
        m.EffectiveActionClass.EXECUTE_SCRIPT,
        m.EffectiveActionClass.EXECUTE_BINARY,
        m.EffectiveActionClass.UNKNOWN,
        m.EffectiveActionClass.INDIRECT_SYSTEM_CONTROL,
    ), f"unclassified wrapper: {cmd}"


def test_classify_script_content_deterministic():
    r1 = ea.classify_script("systemctl restart nginx")
    r2 = ea.classify_script("systemctl restart nginx")
    assert r1.effective_action_class == r2.effective_action_class
    assert r1.targets == r2.targets
