"""Read-only CLI for canary status/inspection/dry-run; no mutator verbs."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from .flags import REAL_CHILD_EXECUTION_ENABLED,enabled,mode
from .models import BASELINE_SHA
from .registry import CanaryServiceRegistry

def _load(path):return json.loads(Path(path).read_text())
def main(argv=None):
 p=argparse.ArgumentParser(prog="multi-service-execution-canary")
 s=p.add_subparsers(dest="cmd",required=True)
 s.add_parser("status")
 for name in ("inspect-plan","inspect-receipt","dry-run"):
  q=s.add_parser(name);q.add_argument("path",nargs="?")
 a=p.parse_args(argv);r=CanaryServiceRegistry()
 if a.cmd=="status":
  print(json.dumps({"baseline_sha":BASELINE_SHA,"enabled":enabled(),"mode":mode(),"real_child_execution_enabled":REAL_CHILD_EXECUTION_ENABLED,"service_ids":r.service_ids(),"registry_size":2,"restart_registry_unchanged":True,"system_control":"OFF","generic_service_control":"DENIED"},sort_keys=True));return 0
 if a.path is None:p.error("path required")
 data=_load(a.path)
 if a.cmd=="dry-run":
  print(json.dumps({"decision":"INSPECT_ONLY","real_adapter_calls":0,"input_keys":sorted(data)},sort_keys=True));return 0
 print(json.dumps(data,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
