"""Sprint 1.3.6.2 — canonical runner exit-code contract (RED first).

Every test invokes the REAL runner (`scripts/run_tests.sh` / 
`scripts/run_tests_parallel.py`) with controlled fixture files in a tmp dir
and asserts the raw exit contract:

    0 failed                -> exit 0
    >=1 failed              -> non-zero
    collection/import error -> non-zero
    timeout                 -> non-zero
    parallel failure        -> non-zero
    tee/pipeline            -> must NOT hide the failure (log carries
                              TEST_RUNNER_EXIT_CODE, PIPESTATUS[0] non-zero,
                              and pipefail pipeline is non-zero)
    summary text            -> must NOT override the real exit status
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNNER_PY = REPO / "scripts" / "run_tests_parallel.py"
RUNNER_SH = REPO / "scripts" / "run_tests.sh"

PASS_FILE = """\
def test_a():
    assert 1 + 1 == 2

def test_b():
    assert 2 * 3 == 6
"""

FAIL_FILE = """\
def test_ok():
    assert True

def test_bad():
    assert 1 + 1 == 3  # intentional
"""

COLLECTION_ERROR_FILE = """\
import definitely_missing_module_1362  # noqa: F401  -> collection error

def test_never_collected():
    assert True
"""

SLOW_FILE = """\
import time

def test_slow():
    time.sleep(30)
    assert True
"""

TEARDOWN_ERROR_FILE = """\
import pytest

@pytest.fixture
def boom():
    yield
    raise RuntimeError("teardown boom")

def test_passes(boom):
    assert True
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _run_py(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUNNER_PY), "--jobs", "2", *args],
        cwd=REPO, capture_output=True, text=True, timeout=timeout,
    )


def _run_sh(args: list[str], timeout: int = 240, pipefail: bool = False,
             tee_log: Path | None = None) -> dict:
    """Run run_tests.sh; return pipeline exit + PIPESTATUS[0] + merged output.

    PIPESTATUS[0] must be captured IMMEDIATELY after the pipeline — any
    intervening command (even `echo`) resets it.
    """
    tee_path = tee_log or Path("/tmp/rt-contract-tee.log")
    pipe = "set -o pipefail; " if pipefail else ""
    pf = "1" if pipefail else "0"
    shell = (
        "{pipe}bash {runner} {args} 2>&1 | tee {tee}\n"
        "ps=(${{PIPESTATUS[@]}})\n"
        "if [ \"{pf}\" = \"1\" ]; then\n"
        "  agg=0\n"
        "  for s in \"${{ps[@]}}\"; do if [ \"$s\" != 0 ]; then agg=$s; break; fi; done\n"
        "else\n"
        "  agg=${{ps[-1]}}\n"
        "fi\n"
        "echo __PIPE_EXIT__=$agg\n"
        "echo __PIPESTATUS0__=${{ps[0]}}"
    ).format(
        pipe=pipe, runner=RUNNER_SH, args=" ".join(str(a) for a in args),
        tee=tee_path, pf=pf,
    )
    proc = subprocess.run(
        ["bash", "-c", shell], cwd=REPO, capture_output=True, text=True,
        timeout=timeout,
    )
    out = proc.stdout + proc.stderr
    m_exit = re.search(r"__PIPE_EXIT__=(\d+)", out)
    m_ps0 = re.search(r"__PIPESTATUS0__=(\d+)", out)
    return {
        "exit": int(m_exit.group(1)) if m_exit else None,
        "pipestatus0": int(m_ps0.group(1)) if m_ps0 else None,
        "output": out,
    }


# ── 1. zero failures -> exit 0 ───────────────────────────────────────────────
def test_zero_failures_exit_zero(tmp_path):
    f = _write(tmp_path, "test_pass_ok.py", PASS_FILE)
    r = _run_py([str(f)])
    assert r.returncode == 0, r.stdout[-2000:]


# ── 2. one failure -> non-zero ───────────────────────────────────────────────
def test_one_failure_exit_nonzero(tmp_path):
    f = _write(tmp_path, "test_fail_one.py", FAIL_FILE)
    r = _run_py([str(f)])
    assert r.returncode != 0, r.stdout[-2000:]
    assert "1 failed" in r.stdout or "1 test failed" in r.stdout


# ── 3. collection/import error -> non-zero ───────────────────────────────────
def test_collection_error_exit_nonzero(tmp_path):
    f = _write(tmp_path, "test_coll_err.py", COLLECTION_ERROR_FILE)
    r = _run_py([str(f)])
    assert r.returncode != 0, r.stdout[-2000:]


# ── 4. timeout -> non-zero ───────────────────────────────────────────────────
def test_timeout_exit_nonzero(tmp_path):
    f = _write(tmp_path, "test_slow.py", SLOW_FILE)
    t0 = time.monotonic()
    r = _run_py(["--file-timeout", "2", str(f)], timeout=120)
    elapsed = time.monotonic() - t0
    assert r.returncode != 0, r.stdout[-2000:]
    assert elapsed < 20, f"timeout kill took too long: {elapsed:.1f}s"


# ── 5. parallel failure propagated (2 files, one fails) ──────────────────────
def test_parallel_failure_propagated(tmp_path):
    good = _write(tmp_path, "test_good.py", PASS_FILE)
    bad = _write(tmp_path, "test_bad.py", FAIL_FILE)
    r = _run_py([str(good), str(bad)])
    assert r.returncode != 0, r.stdout[-2000:]


# ── 6. tee must not hide the failure ─────────────────────────────────────────
def test_tee_does_not_hide_failure(tmp_path):
    f = _write(tmp_path, "test_tee_fail.py", FAIL_FILE)
    tee_log = tmp_path / "tee.log"
    res = _run_sh([str(f)], tee_log=tee_log)
    # the runner's own exit code survives the pipe (PIPESTATUS[0])
    assert res["pipestatus0"] != 0, res["output"][-3000:]
    # the log must carry a machine-readable exit marker (tee-proof)
    assert "TEST_RUNNER_EXIT_CODE=1" in res["output"], res["output"][-3000:]
    assert "TEST_RUNNER_EXIT_CODE=1" in tee_log.read_text(), tee_log.read_text()[-3000:]
    # with pipefail, the whole pipeline is non-zero
    res_pf = _run_sh([str(f)], pipefail=True, tee_log=tmp_path / "tee-pf.log")
    assert res_pf["exit"] != 0, res_pf["output"][-3000:]


# ── 7. summary text must not override the real exit status ───────────────────
def test_summary_does_not_override_exit_status(tmp_path):
    # teardown failure: "1 passed, 1 error" -> failed==0 but pytest exit != 0.
    # The runner must still exit non-zero (summary must not override it).
    f = _write(tmp_path, "test_teardown_err.py", TEARDOWN_ERROR_FILE)
    r = _run_py([str(f)])
    assert r.returncode != 0, r.stdout[-2000:]
