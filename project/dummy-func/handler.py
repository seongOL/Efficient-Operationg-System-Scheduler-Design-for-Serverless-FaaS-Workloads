import json
import os
import time
import random
import hashlib
import logging
import ctypes

logging.basicConfig(level=logging.INFO)

_SCHED_LAST = None

def _apply_scheduler_if_needed():
    global _SCHED_LAST
    mode = os.environ.get("SCHED_MODE", "CFS").upper()
    if mode == _SCHED_LAST:
        return
    try:
        if mode == "FIFO":
            SCHED_FIFO = 1
            class sched_param(ctypes.Structure):
                _fields_ = [("sched_priority", ctypes.c_int)]
            param = sched_param(50)
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            ret = libc.sched_setscheduler(0, SCHED_FIFO, ctypes.byref(param))
            if ret == 0:
                logging.info("[SCHED] SCHED_FIFO enabled (rtprio=50)")
                _SCHED_LAST = "FIFO"
            else:
                err = ctypes.get_errno()
                logging.warning(f"[SCHED] sched_setscheduler failed: errno={err}")
                _SCHED_LAST = "CFS"
        else:
            logging.info("[SCHED] Using default CFS (SCHED_OTHER)")
            _SCHED_LAST = "CFS"
    except Exception as e:
        logging.warning(f"[SCHED] Error while setting scheduler: {e}")
        _SCHED_LAST = "CFS"

# 환경변수
MODE            = os.getenv("MODE", "cpu")            # cpu | sleep | fib
SCALE_MS        = float(os.getenv("SCALE_MS", "3"))   # arg 1당 목표 ms
BASE_DELAY_MS   = float(os.getenv("BASE_DELAY_MS", "0"))
JITTER_MS       = float(os.getenv("JITTER_MS", "0"))
MAX_ARG         = int(os.getenv("MAX_ARG", "1000"))
RESPONSE_BYTES  = int(os.getenv("RESPONSE_BYTES", "0"))

def _parse_event(event):
    body_text = ""
    try:
        if isinstance(event.body, (bytes, bytearray)):
            body_text = event.body.decode("utf-8", errors="ignore") if event.body else ""
        else:
            body_text = event.body or ""
    except Exception:
        body_text = ""

    data = {}
    if body_text:
        try:
            data = json.loads(body_text)
        except Exception:
            data = {"raw": body_text}

    q = getattr(event, "queryString", {}) or {}
    if "arg" in q and "arg" not in data:
        data["arg"] = q["arg"]
    return data

def _busy_cpu_ms(target_ms: float):
    end = time.perf_counter() + target_ms / 1000.0
    blob = b"openfaas"
    h = hashlib.sha256
    while time.perf_counter() < end:
        blob = h(blob).digest()

def _fib_linear(n: int) -> int:
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, (a + b)
    return b

def _random_sleep_ms(base_ms: float, jitter_ms: float):
    if base_ms <= 0 and jitter_ms <= 0:
        return
    delay = base_ms + random.random() * max(jitter_ms, 0.0)
    time.sleep(delay / 1000.0)

# 컨텍스트 스위칭 측정
def _ctx_read():
    try:
        import resource
        RUSAGE_THREAD = getattr(resource, "RUSAGE_THREAD", None)
        if RUSAGE_THREAD is not None:
            ru = resource.getrusage(RUSAGE_THREAD)
        else:
            ru = resource.getrusage(resource.RUSAGE_SELF)
        vol = getattr(ru, "ru_nvcsw", 0)     # voluntary ctx switches
        inv = getattr(ru, "ru_nivcsw", 0)    # involuntary ctx switches
        return {"voluntary": int(vol), "nonvoluntary": int(inv), "total": int(vol + inv)}
    except Exception:
        return {"voluntary": 0, "nonvoluntary": 0, "total": 0}

def handle(event, context):
    _apply_scheduler_if_needed()

    start = time.perf_counter()
    data = _parse_event(event)

    ctx_before = _ctx_read()

    arg_raw = data.get("arg", 0)
    try:
        arg = int(arg_raw)
    except Exception:
        try:
            arg = int(str(arg_raw).split("-")[-1])
        except Exception:
            arg = int(hashlib.md5(str(arg_raw).encode()).hexdigest(), 16) % 50 + 25
    arg = max(0, min(arg, MAX_ARG))

    target_ms = max(arg * SCALE_MS, 0.0)

    _random_sleep_ms(BASE_DELAY_MS, JITTER_MS)

    work_result = None
    if MODE == "sleep":
        _random_sleep_ms(target_ms, 0.0)
        work_kind = "sleep"
    elif MODE == "fib":
        n = min(arg, MAX_ARG)
        work_result = _fib_linear(n)
        work_kind = "fib"
    else:
        _busy_cpu_ms(target_ms)
        work_kind = "cpu"

    elapsed_ms = (time.perf_counter() - start) * 1000.0

    ctx_after = _ctx_read()
    ctx_delta = {
        "voluntary": max(0, ctx_after["voluntary"] - ctx_before["voluntary"]),
        "nonvoluntary": max(0, ctx_after["nonvoluntary"] - ctx_before["nonvoluntary"]),
        "total": max(0, ctx_after["total"] - ctx_before["total"]),
    }

    resp = {
        "ok": True,
        "sched_mode": os.environ.get("SCHED_MODE", "CFS"),
        "mode": MODE,
        "arg": arg,
        "target_ms": target_ms,
        "base_delay_ms": BASE_DELAY_MS,
        "jitter_ms": JITTER_MS,
        "work_kind": work_kind,
        "elapsed_ms": round(elapsed_ms, 3),
        "ctxsw": { "before": ctx_before, "after": ctx_after, "delta": ctx_delta },
        "ts": time.time(),
        "echo": data
    }
    if work_result is not None:
        try:
            resp["fib_digits"] = len(str(work_result))
        except Exception:
            resp["fib_result"] = str(work_result)[:64]
    if RESPONSE_BYTES > 0:
        resp["padding"] = "x" * min(RESPONSE_BYTES, 1_000_000)

    return {"statusCode": 200, "body": json.dumps(resp), "headers": {"Content-Type": "application/json"}}

