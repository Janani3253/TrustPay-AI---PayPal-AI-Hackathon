"""FastAPI router for Audit Trail and Tamper-Evident Integrity Verification."""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.schemas.audit import AuditEventResponse, AuditVerificationResponse
from app.services.audit_service import audit_service

router = APIRouter(prefix="/api/audit", tags=["Audit"])


def _extract_user_id(user: Any) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@router.get("", response_model=List[AuditEventResponse], summary="List Audit Events")
async def list_audit(user: Any = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Retrieve full chronological audit trail with cryptographic hash pointers."""
    user_id = _extract_user_id(user)
    return audit_service.get_audit_trail(user_id)


@router.post(
    "/verify-integrity",
    response_model=AuditVerificationResponse,
    summary="Verify Tamper-Evident Hash Chain Integrity",
)
async def verify_audit_integrity(user: Any = Depends(get_current_user)) -> Dict[str, Any]:
    """Cryptographically verifies the SHA-256 hash chain of all audit events."""
    user_id = _extract_user_id(user)
    return audit_service.verify_integrity(user_id)

