from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import threading, time
from agent.sandbox_runtime.lock import ProcessLocalLock


def test_twenty_writers_one_resource_have_exactly_one_active():
    lock=ProcessLocalLock(); active=0; maximum=0; guard=threading.Lock()
    def worker(i):
        nonlocal active,maximum
        tok=lock.acquire("same",str(i),str(i),timeout_s=2)
        with guard: active+=1; maximum=max(maximum,active)
        time.sleep(.002)
        with guard: active-=1
        lock.release(tok)
    with ThreadPoolExecutor(max_workers=20) as p: list(p.map(worker,range(20)))
    assert maximum==1


def test_twenty_different_resources_can_run_in_parallel():
    lock=ProcessLocalLock(); barrier=threading.Barrier(20); seen=[]
    def worker(i):
        tok=lock.acquire(f"r{i}",str(i),str(i)); seen.append(i); barrier.wait(timeout=2); lock.release(tok)
    with ThreadPoolExecutor(max_workers=20) as p: list(p.map(worker,range(20)))
    assert len(seen)==20
