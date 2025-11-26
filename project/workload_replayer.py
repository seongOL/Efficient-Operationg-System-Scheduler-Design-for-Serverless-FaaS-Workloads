import argparse, time, os, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import numpy as np
from typing import Optional
from custom_scheduler import CustomDispatcher

def _safe_float(x):
    try: return float(x)
    except Exception: return None

class WorkloadReplayer:
    def __init__(self, workload_file, gateway_url="http://127.0.0.1:8080",
                 max_workers=200, request_timeout=30, warmup_drop=50):
        self.workload_file = workload_file
        self.base = gateway_url.rstrip("/")
        self.timeout = request_timeout
        self.max_workers = max_workers
        self.warmup_drop = warmup_drop
        self.funcs = [f"func-{i:02d}" for i in range(15)]
        self.session = requests.Session()
        self.results = []

        self.mode = "CFS"
        if os.path.exists("SCHEDULER_MODE.txt"):
            try:
                m = open("SCHEDULER_MODE.txt").read().strip().upper()
                if "FIFO" in m: self.mode = "FIFO"
                elif "CUSTOM" in m: self.mode = "CUSTOM"
            except: pass

        if self.mode == "CUSTOM":
            self.custom = CustomDispatcher(
                gateway_url=self.base,
                functions=self.funcs,
                session=self.session,
                alpha=0.25,             
                hedge_ms=40.0,          
                ewma_init=120.0,
                ewma_slow_threshold=180.0,
                quarantine_ms=1000.0,
                per_func_concurrency=2, 
                request_timeout=self.timeout
            )
        else:
            self.custom = None
        self._rr = 0

    def _rr_next(self):
        f = self.funcs[self._rr % len(self.funcs)]
        self._rr += 1
        return f

    def _prewarm(self):
        for f in self.funcs:
            try:
                self.session.post(f"{self.base}/function/{f}", json={"arg":"warm"}, timeout=5)
            except Exception:
                pass

    def _call_one(self, func_name: str, arg: str):
        t0 = time.time()
        ok = False; data = {}
        try:
            r = self.session.post(f"{self.base}/function/{func_name}",
                                  json={"arg": arg}, timeout=self.timeout)
            ok = (r.status_code == 200)
            data = r.json() if ok else {}
        except Exception:
            ok = False
        t1 = time.time()
        trun = (t1 - t0) * 1000.0
        exec_ms = _safe_float(data.get("elapsed_ms"))
        res_ms = trun - exec_ms if exec_ms is not None else None
        if res_ms is not None and res_ms < 0: res_ms = 0.0

        ctx = data.get("ctxsw", {}).get("delta", {})
        ctot = _safe_float(ctx.get("total"))
        cvol = _safe_float(ctx.get("voluntary"))
        cinv = _safe_float(ctx.get("nonvoluntary"))

        self.results.append({
            "timestamp": time.time(), "function": func_name, "arg": arg,
            "trun_around_ms": trun, "exec_ms": exec_ms, "res_ms": res_ms,
            "ctxsw_delta_total": ctot, "ctxsw_delta_vol": cvol, "ctxsw_delta_invol": cinv,
            "success": ok
        })

    def _call_one_custom(self, arg: str):
        ok, data, elapsed_ms, used = self.custom.invoke({"arg": arg})
        exec_ms = _safe_float(data.get("elapsed_ms"))
        res_ms = elapsed_ms - exec_ms if exec_ms is not None else None
        if res_ms is not None and res_ms < 0: res_ms = 0.0

        ctx = data.get("ctxsw", {}).get("delta", {})
        ctot = _safe_float(ctx.get("total"))
        cvol = _safe_float(ctx.get("voluntary"))
        cinv = _safe_float(ctx.get("nonvoluntary"))

        self.results.append({
            "timestamp": time.time(), "function": used, "arg": arg,
            "trun_around_ms": elapsed_ms, "exec_ms": exec_ms, "res_ms": res_ms,
            "ctxsw_delta_total": ctot, "ctxsw_delta_vol": cvol, "ctxsw_delta_invol": cinv,
            "success": bool(ok)
        })

    def replay(self, max_items: Optional[int] = 500):
        print(f"[Replayer] Mode={self.mode}  Start: {self.workload_file}")
        self._prewarm()

        lines = open(self.workload_file).read().strip().splitlines()
        if max_items:
            lines = lines[:max_items]

        start = time.time()
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futs = []
            for i, line in enumerate(lines):
                try:
                    ia, arg = line.strip().split()
                    ia = float(ia)
                except Exception:
                    continue
                if ia > 0: time.sleep(ia)

                if self.mode == "CUSTOM":
                    futs.append(ex.submit(self._call_one_custom, arg))
                else:
                    f = self._rr_next()
                    futs.append(ex.submit(self._call_one, f, arg))

            for _ in as_completed(futs):
                pass

        print(f"[Replayer] Done. Sent {len(lines)} in {time.time()-start:.2f}s")
        self._save()

    def _save(self):
        succ = [r for r in self.results if r["success"]]
        drop = min(self.warmup_drop, len(succ))
        succ = succ[drop:]

        mode = self.mode
        out_dir = f"./{mode}"
        os.makedirs(out_dir, exist_ok=True)
        out_path = f"{out_dir}/{mode}_result.csv"

        import csv
        with open(out_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp","function","arg",
                        "trun_around_ms","exec_ms","res_ms",
                        "ctxsw_delta_total","ctxsw_delta_vol","ctxsw_delta_invol"])
            for r in succ:
                w.writerow([
                    r["timestamp"], r["function"], r["arg"],
                    r["trun_around_ms"], r["exec_ms"], r["res_ms"],
                    r["ctxsw_delta_total"], r["ctxsw_delta_vol"], r["ctxsw_delta_invol"]
                ])
                
        def N(col): 
            xs = [ _safe_float(r[col]) for r in succ if r[col] is not None ]
            xs = [x for x in xs if x is not None]
            return np.mean(xs) if xs else 0.0
        print("[Summary] avg turn=%.2f, exec=%.2f, resp=%.2f" %
              (N("trun_around_ms"), N("exec_ms"), N("res_ms")))
        print(f"[Saved] {out_path}")

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", default="workload_dur.txt")
    ap.add_argument("--gateway", default="http://127.0.0.1:8080")
    ap.add_argument("--workers", type=int, default=200)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--max-items", type=int, default=500)
    ap.add_argument("--warmup-drop", type=int, default=50)
    return ap.parse_args()

if __name__ == "__main__":
    a = parse_args()
    WorkloadReplayer(
        workload_file=a.workload, gateway_url=a.gateway,
        max_workers=a.workers, request_timeout=a.timeout,
        warmup_drop=a.warmup_drop
    ).replay(max_items=a.max_items)

