#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-../grn_analysis/grinferens/bin/python}"
SIZES="${SIZES:-3000 4000}"
SEED="${SEED:-1}"
SAMPLE_ID="${SAMPLE_ID:-${SAMPLING_STRATEGY:-low_degree_bfs}_seed${SEED}}"
SAMPLING_STRATEGY="${SAMPLING_STRATEGY:-low_degree_bfs}"
TOP_K="${TOP_K:-1}"
N_JOBS="${N_JOBS:-4}"
PAIR_TIMEOUT="${PAIR_TIMEOUT:-240}"
PAIR_WALL_TIMEOUT="${PAIR_WALL_TIMEOUT:-360}"
THIRD_TIMEOUT="${THIRD_TIMEOUT:-240}"
THIRD_WALL_TIMEOUT="${THIRD_WALL_TIMEOUT:-360}"
PATTERN_SIDES="${PATTERN_SIDES:-left}"
OUT_DIR="${OUT_DIR:-outputs/${SAMPLE_ID}}"

read -r -a SIZE_ARGS <<< "$SIZES"
read -r -a SIDE_ARGS <<< "$PATTERN_SIDES"

"$PYTHON_BIN" code/run_mcis_mcis_threeway.py \
  --out-dir "$OUT_DIR" \
  --solver symsplit/bin/run.o \
  --sizes "${SIZE_ARGS[@]}" \
  --sample-id "$SAMPLE_ID" \
  --seed "$SEED" \
  --sampling-strategy "$SAMPLING_STRATEGY" \
  --top-k "$TOP_K" \
  --n-jobs "$N_JOBS" \
  --pair-timeout "$PAIR_TIMEOUT" \
  --pair-wall-timeout "$PAIR_WALL_TIMEOUT" \
  --third-timeout "$THIRD_TIMEOUT" \
  --third-wall-timeout "$THIRD_WALL_TIMEOUT" \
  --pattern-sides "${SIDE_ARGS[@]}" \
  --reuse-samples \
  "$@"
