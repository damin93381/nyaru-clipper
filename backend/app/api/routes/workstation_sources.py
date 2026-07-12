"""Versioned source inspection and trusted local catalog endpoints."""

from __future__ import annotations

from pydantic import ConfigDict, Field, HttpUrl
from fastapi import APIRouter, HTTPException, Query

from app.api.schemas.workstation import WorkstationSchema
from app.models import CANONICAL_STAGES
from app.services.source_catalog import (
    LocalDirectoryListing,
    SourceCatalogError,
    SourceInspection,
    inspect_bilibili_source,
    list_local_entries,
    list_local_roots,
)


router = APIRouter(prefix="/v2", tags=["workstation-sources"])


class BilibiliInspectRequest(WorkstationSchema):
    """The Bilibili URL accepted by the source-inspection boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: HttpUrl


class BilibiliInspectionResponse(WorkstationSchema):
    """Safe Bilibili source metadata for task creation."""

    normalized_url: str
    source_video_id: str
    title: str | None
    uploader: str | None
    duration_seconds: float | None


class LocalRootResponse(WorkstationSchema):
    """An opaque trusted-root identity and display name."""

    id: str
    name: str


class LocalEntryResponse(WorkstationSchema):
    """A safe local catalog entry without a host-path disclosure."""

    name: str
    relative_path: str
    kind: str


class LocalDirectoryResponse(WorkstationSchema):
    """The discovered roots and entries for one optional selected directory."""

    roots: list[LocalRootResponse]
    root_id: str | None
    relative_path: str
    entries: list[LocalEntryResponse]


class ProcessingProfileResponse(WorkstationSchema):
    """A fixed first-phase processing profile."""

    id: str
    name: str
    stages: list[str]


class ProcessingProfilesResponse(WorkstationSchema):
    """The complete set of available processing profiles."""

    profiles: list[ProcessingProfileResponse]


@router.post("/sources/bilibili/inspect", response_model=BilibiliInspectionResponse)
def inspect_bilibili_source_endpoint(payload: BilibiliInspectRequest) -> BilibiliInspectionResponse:
    """Inspect one normalized Bilibili source without creating a task."""
    try:
        inspection = inspect_bilibili_source(str(payload.url))
    except SourceCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _inspection_response(inspection)


@router.get("/sources/local", response_model=LocalDirectoryResponse)
def local_source_catalog_endpoint(
    root_id: str | None = Query(default=None, min_length=1),
    relative_path: str = Query(default=""),
) -> LocalDirectoryResponse:
    """Browse only explicitly configured local-import roots and descendants."""
    try:
        listing = list_local_roots() if root_id is None else list_local_entries(root_id, relative_path)
    except SourceCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _listing_response(listing)


@router.get("/processing-profiles", response_model=ProcessingProfilesResponse)
def processing_profiles_endpoint() -> ProcessingProfilesResponse:
    """Return the sole first-phase profile without per-stage toggle decoration."""
    return ProcessingProfilesResponse(
        profiles=[ProcessingProfileResponse(id="standard", name="Standard", stages=list(CANONICAL_STAGES))]
    )


def _inspection_response(inspection: SourceInspection) -> BilibiliInspectionResponse:
    return BilibiliInspectionResponse(
        normalized_url=inspection.normalized_url,
        source_video_id=inspection.source_video_id,
        title=inspection.title,
        uploader=inspection.uploader,
        duration_seconds=inspection.duration_seconds,
    )


def _listing_response(listing: LocalDirectoryListing) -> LocalDirectoryResponse:
    return LocalDirectoryResponse(
        roots=[LocalRootResponse(id=root.id, name=root.name) for root in listing.roots],
        root_id=listing.root_id,
        relative_path=listing.relative_path,
        entries=[
            LocalEntryResponse(name=entry.name, relative_path=entry.relative_path, kind=entry.kind)
            for entry in listing.entries
        ],
    )
