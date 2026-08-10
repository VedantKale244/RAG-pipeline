"""POST /feedback — inline thumbs up/down, feeding the SAME edge-reward loop as RAGAS.

Zero new learning infrastructure: a thumbs verdict becomes a per-edge reward (up=1.0,
down=0.0) over the answer's surviving_edges and is handed to the identical
adaptive.reweight_from_feedback the offline eval uses. This turns an offline eval loop
into online human feedback.
"""
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..core import adaptive
from ..errors import internal_error
from ..eval import history
from ..ratelimit import limiter
from ..schemas import FeedbackRequest, FeedbackResponse

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=FeedbackResponse)
@limiter.limit("30/minute")
async def feedback(request: Request, req: FeedbackRequest) -> FeedbackResponse:
    if not req.question.strip():
        raise HTTPException(400, "Question must not be empty")

    reward = 1.0 if req.helpful else 0.0
    edge_rewards = {(s, t): reward for s, t in req.edges}

    try:
        history.record_feedback(
            settings.feedback_path,
            {"question": req.question, "helpful": req.helpful, "n_edges": len(req.edges)},
        )
        # No edges (e.g. a graph-off answer) → nothing to reweight, but the vote is logged.
        updated = (
            await run_in_threadpool(adaptive.reweight_from_feedback, edge_rewards)
            if edge_rewards
            else 0
        )
    except Exception as exc:
        raise internal_error(exc) from exc

    return FeedbackResponse(updated_edges=updated)
