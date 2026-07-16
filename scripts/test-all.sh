#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> hardcoded identity check"
python3 scripts/check-hardcoded-identities.py

for package in packages/contracts services/semantic services/runtime services/export; do
  echo "==> pytest: $package"
  (cd "$package" && uv run pytest)
done

echo "==> frontend lint"
(cd apps/web && npm run lint)

echo "==> frontend production build"
(cd apps/web && npm run build)

if [[ "${SQBI_RUN_LIVE_EVAL:-0}" == "1" ]]; then
  echo "==> live Harness benchmark"
  uv run python scripts/evaluate_queries.py benchmarks/tms_sim_harness_cases.json \
    --output .local/evaluation/tms-sim.json
fi

