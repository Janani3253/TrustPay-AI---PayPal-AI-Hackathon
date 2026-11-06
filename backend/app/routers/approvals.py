"""FastAPI router for Customer Approvals."""

from typing import Any, Dict
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.schemas.approval import ApprovalRequest, ApprovalResponse
from app.services.approval_service import ApprovalService

router = APIRouter(prefix="/api/approvals", tags=["Approvals"])


def _extract_user_id(user: Any) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@router.post("/{order_id}/approve", response_model=ApprovalResponse)
async def approve_order(
    order_id: str,
    payload: ApprovalRequest,
    user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Approve a verified order for checkout execution."""
    user_id = _extract_user_id(user)
    return await ApprovalService.approve_order(
        order_id=order_id,
        order_version=payload.order_version,
        user_id=user_id,
    )
