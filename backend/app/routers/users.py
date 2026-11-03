from fastapi import APIRouter, Depends, status
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import UserProfileResponse

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get(
    "/profile",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Get user account profile details",
)
async def get_profile(
    current_user: User = Depends(get_current_user),
) -> UserProfileResponse:
    """Return user profile with account metadata."""
    return UserProfileResponse.model_validate(current_user)

