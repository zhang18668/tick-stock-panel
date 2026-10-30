"""Register the stateless chan.py adapter without changing core app wiring."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar
from app.services.chan_analysis import ChanBar, analyze
from app.vendor.chanpy.Common.ChanException import CChanException

EXTENSION_ID = "chan.analysis"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/custom/chan", tags=["chan-analysis"])


class AnalysisRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    period: Literal["day", "week"] = "day"
    rows: list[ChanBar] = Field(max_length=2000)


@router.post("/analyze")
def analyze_chart(body: AnalysisRequest) -> dict:
    try:
        return {"symbol": body.symbol, "period": body.period,
                **analyze([row.model_dump(mode="json") for row in body.rows], body.period)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (CChanException, AssertionError) as exc:
        logger.warning("chan.py calculation failed for %s", body.symbol, exc_info=True)
        raise HTTPException(status_code=422, detail="chan.py 无法可靠分析这组K线，请检查数据或缩短历史范围") from exc


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(router)
