set -euo pipefail
NS=openfaas-fn

for i in $(seq -w 00 14); do
  F=func-$i
  echo "==== $F ===="
  kubectl -n "$NS" set env deploy/$F fprocess="chrt -f 50 python index.py" SCHED_MODE=CFS >/dev/null

  kubectl -n "$NS" scale deploy/$F --replicas=0
  kubectl -n "$NS" delete pod -l faas_function=$F --force --grace-period=0 --ignore-not-found
  kubectl -n "$NS" delete rs  -l faas_function=$F --force --grace-period=0 --ignore-not-found
  kubectl -n "$NS" scale deploy/$F --replicas=1
  kubectl -n "$NS" rollout status deploy/$F --timeout=180s
done

echo "FIFO" > SCHEDULER_MODE.txt
echo "[FIFO] done. SCHEDULER_MODE.txt -> FIFO"

