"""Project management endpoints required by the PRD/FRD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ..dependencies import enforce_pin_verification, enforce_signed_request
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


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Retrieve a single project by identifier",
)
async def get_project(
    project_id: str,
    _: None = Depends(enforce_signed_request),
) -> ProjectResponse:
    """Fetch an individual project record by primary key."""

    return _repository.get_project(project_id)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project and purge its artefacts",
)
async def delete_project(
    project_id: str,
    _: None = Depends(enforce_signed_request),
    __: None = Depends(enforce_pin_verification),
) -> None:
    """Remove the project and associated artefacts after PIN verification."""

    _repository.delete_project(project_id)
