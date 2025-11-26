set -euo pipefail

NS="${NS:-openfaas-fn}"
REPLAYER="python3 workload_replayer.py"
MODES=(CFS FIFO CUSTOM)
RUNS=100
SLEEP_BETWEEN=5

hard_bounce() {
  kubectl -n "$NS" scale deploy -l faas_function --replicas=0
  kubectl -n "$NS" delete pod -l faas_function --force --grace-period=0 --ignore-not-found
  kubectl -n "$NS" delete rs -l faas_function --force --grace-period=0 --ignore-not-found
  kubectl -n "$NS" scale deploy -l faas_function --replicas=1
  kubectl -n "$NS" rollout status deploy -l faas_function --timeout=180s
}

to_mode() {
  case "$1" in
    CFS)    ./cfs_on.sh ;;
    FIFO)   ./fifo_on.sh ;;
    CUSTOM) ./custom_on.sh ;;
    *) echo "unknown mode $1"; exit 1;;
  esac
}

echo "[RunAll] start"
for M in "${MODES[@]}"; do
  echo "== Mode: $M =="
  to_mode "$M"
  sleep "$SLEEP_BETWEEN"
  hard_bounce
  sleep "$SLEEP_BETWEEN"

  rm -f "./$M/${M}_result.csv" "./$M/${M}_result_"*.csv 2>/dev/null || true

  for i in $(seq 1 $RUNS); do
    echo "[Run] $M #$i"
    $REPLAYER
    mv "./$M/${M}_result.csv" "./$M/${M}_result_${i}.csv"
    sleep 1
  done

  head -n1 "./$M/${M}_result_1.csv" > "./$M/${M}_result.csv"
  for i in $(seq 1 $RUNS); do
    tail -n +2 "./$M/${M}_result_${i}.csv" >> "./$M/${M}_result.csv"
  done
  echo "[Mode $M] merged -> ./$M/${M}_result.csv"
done

python3 compare_three.py

echo "[RunAll] done. Outputs in: compare_results/three  and  compare_results/three_runs"

