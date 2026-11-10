"""FastAPI router for Transaction management."""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.repositories.transaction_repository import TransactionRepository

router = APIRouter(prefix="/api/transactions", tags=["Transactions"])


def _extract_user_id(user: Any) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@router.get("", response_model=List[Dict[str, Any]], summary="List User Transactions")
async def list_transactions(user: Any = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Retrieve full chronological transaction history for the authenticated user."""
    user_id = _extract_user_id(user)
    return await TransactionRepository.get_user_transactions(user_id)

