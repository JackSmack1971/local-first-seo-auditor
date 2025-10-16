"""Project management endpoints required by the PRD/FRD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ..dependencies import enforce_signed_request
from ..models import ProjectCreateRequest, ProjectResponse
from ..repositories.projects import ProjectsRepository


router = APIRouter(prefix="/projects", tags=["projects"])
_repository = ProjectsRepository()


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new SEO project",
)
async def create_project(
    payload: ProjectCreateRequest,
    _: None = Depends(enforce_signed_request),
) -> ProjectResponse:
    """Persist a new project configuration for later crawl/audit runs."""

    return _repository.create_project(payload)


@router.get(
    "",
    response_model=list[ProjectResponse],
    summary="List configured SEO projects",
)
async def list_projects(_: None = Depends(enforce_signed_request)) -> list[ProjectResponse]:
    """Return all stored project records ordered alphabetically."""

    return _repository.list_projects()
