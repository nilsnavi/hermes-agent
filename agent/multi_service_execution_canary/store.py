"""Atomic durable claims/receipts for canary simulation evidence."""
from __future__ import annotations
import json,os,threading,time
from pathlib import Path
class CanaryStore:
    _locks_guard=threading.Lock();_locks={}
    def __init__(self, root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/"canary-store.json"
        key=str(self.path.resolve())
        with self._locks_guard:self._lock=self._locks.setdefault(key,threading.RLock())
        if not self.path.exists():self._write({"claims":{},"receipts":{},"events":{},"active_slot":None,"kill_switch":False,"budget_attempts":0,"budget_success":0,"approvals":[]})
    def _read(self):
        try:return json.loads(self.path.read_text())
        except (FileNotFoundError,json.JSONDecodeError):return {"claims":{},"receipts":{},"events":{},"active_slot":None,"kill_switch":False,"budget_attempts":0,"budget_success":0,"approvals":[]}
    def _write(self,data):
        tmp=self.path.with_suffix(".tmp");tmp.write_text(json.dumps(data,sort_keys=True,separators=(",",":")));os.replace(tmp,self.path)
    def claim(self,key):
        with self._lock:
            d=self._read()
            if key in d["receipts"]:return "TERMINAL",d["receipts"][key]
            if key in d["claims"]:return "OWNED",None
            d["claims"][key]="ACTIVE";self._write(d);return "CLAIMED",None
    def wait_terminal(self,key,timeout_s=2.0):
        deadline=time.monotonic()+timeout_s
        while time.monotonic()<deadline:
            with self._lock:
                prior=self._read().get("receipts",{}).get(key)
                if prior is not None:return prior
            time.sleep(0.001)
        return None
    def reserve_simulation_slot(self,key):
        with self._lock:
            d=self._read()
            if d.get("kill_switch") or d.get("active_slot") not in (None,key):return False
            d["active_slot"]=key;self._write(d);return True
    def release_simulation_slot(self,key):
        with self._lock:
            d=self._read()
            if d.get("active_slot")==key:d["active_slot"]=None;self._write(d)
    def terminal(self,key,receipt,*,success=False,approval_id=""):
        with self._lock:
            d=self._read();d["claims"].pop(key,None);d["receipts"][key]=receipt
            d["budget_attempts"]+=1;d["budget_success"]+=int(success)
            if approval_id:d["approvals"].append(approval_id)
            d["kill_switch"]=True;d["active_slot"]=None;self._write(d)
    def fail_before_simulation(self,key):
        with self._lock:
            d=self._read();d["claims"].pop(key,None)
            if d.get("active_slot")==key:d["active_slot"]=None
            self._write(d)
    def append_event(self,key,event):
        with self._lock:
            d=self._read();d.setdefault("events",{}).setdefault(key,[]).append(str(event));self._write(d)
    def events(self,key):
        with self._lock:return tuple(self._read().get("events",{}).get(key,()))
    def kill_switch(self):
        with self._lock:return bool(self._read().get("kill_switch"))
    def budget(self):
        with self._lock:
            d=self._read();return int(d.get("budget_attempts",0)),int(d.get("budget_success",0))
