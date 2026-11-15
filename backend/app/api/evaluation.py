"""Recorded evaluation results, for the Evaluation screen. The files are produced by eval/run_eval.py and
eval/attacks.py and are shipped with the application; nothing here runs a model."""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.security.sessions import Principal

router = APIRouter(prefix="/api/eval", tags=["evaluation"])
RESULTS = Path(__file__).resolve().parents[2] / "eval" / "results"


@lru_cache(maxsize=1)
def _load(signature: tuple) -> dict:
    results, attacks = [], []
    for path in sorted(RESULTS.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if "cases" in data:
            attacks.append({k: data[k] for k in ("model", "at", "cases")})
        elif "metrics" in data:
            results.append({k: data[k] for k in ("name", "model", "split", "at", "n", "metrics", "by_kind")})
    return {"results": results, "attacks": attacks}


@router.get("/results")
async def results(_: Principal = Depends(current_user)) -> dict:
    signature = (
        tuple((p.name, p.stat().st_mtime_ns) for p in sorted(RESULTS.glob("*.json"))) if RESULTS.exists() else ()
    )
    return _load(signature)
