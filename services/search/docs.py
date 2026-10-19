from typing import Any
from sqlalchemy.orm import selectinload
from config.variables import USD_TO_IDR_RATE
from schemas.format.files import UserGeneratedFile, UserUploadedFile
from services.mysql.model import DfEngineGenerationResults, DfEngineGenerations, DfEngineUploadFiles, Employees, Users
from services.mysql.model.df_engine_generations import GenerationKinds, GenerationStatuses
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from utils.formatter import format_idr, format_usd, format_user_employees
from utils.serializer import serialize

MAIN_GENERATIONS = "main_generations"
UPLOADED_FILES = "uploaded_files"

# What the search endpoints rely on (see services/search/query.py); applied to both indexes by the search worker.
SEARCHABLE_FIELDS = ["name", "path", "task"]
FILTER_FIELDS = ["project_uid", "task_uid", "song_uid", "kind"]

GENERATION_KINDS = (GenerationKinds.image, GenerationKinds.image_edit, GenerationKinds.video)

# ponytail: relationships are eager-loaded here because `serialize` skips anything not loaded; add to this tuple
# when a new indexed field needs another relation.
_USERS = (
    selectinload(DfEngineGenerationResults.created_by_user)
    .load_only(Users.image)
    .selectinload(Users.employees)
    .load_only(Employees.nickname),  # type: ignore
    selectinload(DfEngineGenerationResults.updated_by_user)
    .load_only(Users.image)
    .selectinload(Users.employees)
    .load_only(Employees.nickname),  # type: ignore
)


def generation_load_options() -> tuple[Any, ...]:
    generation = selectinload(DfEngineGenerationResults.generation)  # type: ignore
    return (
        *_USERS,
        generation,
        generation.selectinload(DfEngineGenerations.model_option),  # type: ignore
        generation.selectinload(DfEngineGenerations.task),  # type: ignore
        generation.selectinload(DfEngineGenerations.song),  # type: ignore
        generation.selectinload(DfEngineGenerations.project),  # type: ignore
    )


def upload_load_options() -> tuple[Any, ...]:
    return (
        selectinload(DfEngineUploadFiles.created_by_user)
        .load_only(Users.image)
        .selectinload(Users.employees)
        .load_only(Employees.nickname),  # type: ignore
        selectinload(DfEngineUploadFiles.updated_by_user)
        .load_only(Users.image)
        .selectinload(Users.employees)
        .load_only(Employees.nickname),  # type: ignore
        selectinload(DfEngineUploadFiles.task),  # type: ignore
        selectinload(DfEngineUploadFiles.song),  # type: ignore
        selectinload(DfEngineUploadFiles.project),  # type: ignore
    )


def generation_qualifies(result: DfEngineGenerationResults) -> bool:
    """Only the main file of a successful image / image_edit / video generation is indexed."""
    generation = result.generation
    return bool(
        result.is_main
        and generation is not None
        and generation.kind in GENERATION_KINDS
        and generation.status == GenerationStatuses.success
    )


def upload_qualifies(file: DfEngineUploadFiles) -> bool:
    """Only image uploads are indexed (no videos, no folders)."""
    return file.type == UploadFileTypes.image


def build_generation_doc(result: DfEngineGenerationResults) -> dict[str, Any]:
    """The `main_generations` document: the same fields `get_generation_main_refactored` returns for this file, flat
    (no `variants` / `references`) and with `action=None`, since the action depends on who is viewing. `project_uid`
    is the only extra field, used for scoping."""
    row = serialize(result)
    generation = row["generation"]
    task = generation.get("task") or {}
    song = generation.get("song") or {}
    doc = UserGeneratedFile(
        id=row["id"],
        kind=generation["kind"],
        file_uid=row["uid"],
        generation_uid=generation["uid"],
        parent_id=row["parent_id"],
        name=row["name"],
        path=row["path"],
        size=row["size"],
        is_main=row["is_main"],
        version=row["version"],
        status=generation["status"],
        task_uid=task.get("uid"),
        song_uid=song.get("uid"),
        task=(task or song).get("name"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archieved_at=row["archieved_at"],
        cost_usd=format_usd(generation["cost"]),
        cost_idr=format_idr(generation["cost"], USD_TO_IDR_RATE),
        model=(generation.get("model_option") or {}).get("name"),
        prompt=generation["prompt"],
        full_prompt=generation["full_prompt"],
        parameter=generation["parameter"],
        creator=format_user_employees(row.get("created_by_user")),
        updater=format_user_employees(row.get("updated_by_user")),
        action=None,
    ).model_dump(mode="json", exclude={"variants", "references"})
    return {**doc, "objectID": row["uid"], "project_uid": (generation.get("project") or {}).get("uid")}


def build_upload_doc(file: DfEngineUploadFiles) -> dict[str, Any]:
    """The `uploaded_files` document: the same fields `get_user_uploaded_files_refactored` returns for this file, with
    `action=None` and `project_uid` added for scoping."""
    row = serialize(file)
    task = row.get("task") or {}
    song = row.get("song") or {}
    doc = UserUploadedFile(
        id=row["id"],
        file_uid=row["uid"],
        name=row["name"],
        path=row["path"],
        task_uid=task.get("uid"),
        song_uid=song.get("uid"),
        task=(task or song).get("name"),
        kind=row["type"],
        size=row["size"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        creator=format_user_employees(row.get("created_by_user")),
        updater=format_user_employees(row.get("updated_by_user")),
        action=None,
    ).model_dump(mode="json")
    return {**doc, "objectID": row["uid"], "project_uid": (row.get("project") or {}).get("uid")}
