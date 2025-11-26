import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import math
from typing import List, Dict, Optional

def now_ms() -> float:
    return time.time() * 1000.0

class EWMA:
    def __init__(self, alpha: float = 0.2, init: float = 120.0):
        self.alpha = alpha
        self.v = init
        self.lock = threading.Lock()
    def update(self, x: float):
        with self.lock:
            self.v = self.alpha * x + (1 - self.alpha) * self.v
    def value(self) -> float:
        with self.lock:
            return self.v

class TokenBucket:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cur = capacity
        self.cv = threading.Condition()
    def acquire(self):
        with self.cv:
            while self.cur <= 0:
                self.cv.wait()
            self.cur -= 1
    def release(self):
        with self.cv:
            self.cur += 1
            if self.cur > self.capacity:
                self.cur = self.capacity
            self.cv.notify()

class CustomDispatcher:
    """
    - EWMA로 함수별 지연 추정
    - 느려진 함수는 격리(사용 중단) 후 회복 감시
    - P95 지연(대략치)을 hedge 타임아웃으로 사용, 다른 빠른 후보에 1회 복제
    - 함수별 동시성 상한으로 큐 폭주 억제
    """
    def __init__(
        self,
        gateway_url: str,
        functions: List[str],
        session: Optional[requests.Session] = None,
        alpha: float = 0.25,
        hedge_ms: float = 40.0,      # 이 시간 기다리면 1회 복제 발사
        ewma_init: float = 120.0,
        ewma_slow_threshold: float = 180.0,   # EWMA가 이걸 넘으면 느리다고 판단
        quarantine_ms: float = 1000.0,        # 격리 유지 시간
        per_func_concurrency: int = 2,        # 함수별 동시 실행 상한
        request_timeout: int = 30
    ):
        self.base = gateway_url.rstrip("/")
        self.funcs = list(functions)
        self.session = session or requests.Session()
        self.timeout = request_timeout

        self.lat: Dict[str, EWMA] = {f: EWMA(alpha=alpha, init=ewma_init) for f in self.funcs}
        self.tb: Dict[str, TokenBucket] = {f: TokenBucket(per_func_concurrency) for f in self.funcs}

        self.slow_until: Dict[str, float] = {f: 0.0 for f in self.funcs}
        self.ewma_slow_threshold = ewma_slow_threshold
        self.quarantine_ms = quarantine_ms
        self.hedge_ms = hedge_ms

        self._rr = 0
        self._rr_lock = threading.Lock()

    def _mark_slow_if_needed(self, f: str):
        if self.lat[f].value() >= self.ewma_slow_threshold:
            self.slow_until[f] = now_ms() + self.quarantine_ms

    def _is_slow(self, f: str) -> bool:
        return now_ms() < self.slow_until[f]

    def _pick_fast_candidates(self, k: int = 2) -> List[str]:
        healthy = [f for f in self.funcs if not self._is_slow(f)]
        if not healthy:
            healthy = self.funcs[:] 
        healthy.sort(key=lambda f: self.lat[f].value())
        return healthy[:k]

    def _rr_next(self) -> str:
        with self._rr_lock:
            f = self.funcs[self._rr % len(self.funcs)]
            self._rr += 1
            return f

    def _post(self, f: str, payload: dict):
        url = f"{self.base}/function/{f}"
        self.tb[f].acquire()
        t0 = now_ms()
        try:
            r = self.session.post(url, json=payload, timeout=self.timeout)
            ok = (r.status_code == 200)
            data = r.json() if ok else {}
        except Exception:
            ok = False
            data = {}
        finally:
            self.tb[f].release()
        t1 = now_ms()
        elapsed = max(0.0, t1 - t0)

        self.lat[f].update(elapsed)
        self._mark_slow_if_needed(f)
        return ok, data, elapsed, f

    def invoke(self, payload: dict):
        """
        1) 빠른 후보 1개에 즉시 전송
        2) hedge_ms가 지나면 다른 빠른 후보에 1회 복제
        3) 먼저 성공한 쪽을 채택(나머지는 버림)
        """
        cands = self._pick_fast_candidates(k=3)
        primary = cands[0] if cands else self._rr_next()
        backup  = (cands[1] if len(cands) > 1 else self._rr_next())

        with ThreadPoolExecutor(max_workers=2) as ex:
            fut1 = ex.submit(self._post, primary, payload)

            t0 = now_ms()
            while True:
                if fut1.done():
                    break
                if now_ms() - t0 >= self.hedge_ms:
                    fut2 = ex.submit(self._post, backup, payload)
                    done, = next(as_completed([fut1, fut2], timeout=self.timeout), None),
                    
                    res1 = fut1.result() if fut1.done() else None
                    res2 = fut2.result() if fut2.done() else None

                    for res in [res1, res2]:
                        if res and res[0]:
                            return res

                    return res1 or res2

                time.sleep(0.001)
            return fut1.result()

