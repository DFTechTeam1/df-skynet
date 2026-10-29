from uuid import UUID
from typing import Any, Optional
from services.redis import get_json, set_json
from sqlalchemy import or_, and_, func, select
from sqlalchemy.orm import selectinload
from services.mysql.model import (
    DfEngineGenerationFavourites,
    DfEngineGenerations,
    DfEngineGenerationReferences,
    DfEngineGenerationResults,
    DfEngineGenerationUploads,
    DfEngineModelOptions,
    DfEngineUploadFiles,
    DfEngineUploadFileReferences,
    Users,
    Employees,
    Projects,
    ProjectSongLists,
    ProjectTasks,
)
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.mysql.model.df_engine_generations import GenerationKinds, GenerationStatuses
from log import logging
from error import DataNotFoundError, DataValidationError
from services.mysql import query
from config.variables import USD_TO_IDR_RATE
from schemas.format.action import FailedUploadAction, GeneratedFileAction
from utils.formatter import format_datetime, format_idr, format_usd, format_user_employees
from utils.serializer import serialize
from services.dto import ConnectionContext
from schemas.format.files import GenerationReference, GenerationVariant, UserGeneratedFile
from services.dto.format_response import (
    grant_generation_override,
    GenerationResultRecord,
    GenerationReferenceRecord,
    favourited_at_of,
    UploadedReferenceRecord,
)


def _viewer_favourites(viewer_id: int) -> Any:
    """Loader option: a result's `favourites`, narrowed to the viewer's own row (0 or 1)."""
    return DfEngineGenerationResults.favourites.and_(DfEngineGenerationFavourites.user_id == viewer_id)  # type: ignore


def _build_variant(
    variant: dict[str, Any], fallback_kind: Optional[str], task_name: Optional[str]
) -> GenerationVariant:
    generation = variant.get("generation") or {}
    return GenerationVariant(
        id=variant["id"],
        kind=generation.get("kind") or fallback_kind,
        file_uid=variant["uid"],
        generation_uid=generation.get("uid"),
        parent_id=variant["parent_id"],
        name=variant["name"],
        path=variant["path"],
        size=variant["size"],
        is_main=variant["is_main"],
        version=variant["version"],
        status=generation.get("status"),
        task_uid=(generation.get("task") or {}).get("uid"),
        song_uid=(generation.get("song") or {}).get("uid"),
        task=task_name,
        created_at=variant["created_at"],
        updated_at=variant["updated_at"],
        favourited_at=favourited_at_of(variant),
        archieved_at=variant["archieved_at"],
        cost_usd=format_usd(generation.get("cost")),
        cost_idr=format_idr(generation.get("cost"), USD_TO_IDR_RATE),
        model=(generation.get("model_option") or {}).get("name"),
        prompt=generation.get("prompt"),
        full_prompt=generation.get("full_prompt"),
        parameter=generation.get("parameter"),
        creator=format_user_employees(variant.get("created_by_user")),
        updater=format_user_employees(variant.get("updated_by_user")),
    )


async def overlay_favourites(
    ctx: ConnectionContext, records: Any, user_id: Optional[int], key: Optional[str] = None
) -> Any:
    """Stamp the viewer's own favourite onto records read from a viewer-neutral (shared) cache: `favourited_at` and the
    `can_set_favorite` flag. Nested `variants` are covered too. No-op without a viewer."""
    if user_id is None:
        return records
    items: list[dict[str, Any]] = []

    def collect(record: dict[str, Any]) -> None:
        items.append(record)
        for variant in record.get("variants") or []:
            collect(variant)

    for record in [records] if isinstance(records, dict) else records:
        collect(record[key] if key else record)
    uids = {item["file_uid"] for item in items if item.get("file_uid")}
    if not uids:
        return records
    rows = await query(
        ctx.db,
        DfEngineGenerationFavourites,
        columns=(DfEngineGenerationFavourites.favourited_at, DfEngineGenerationResults.uid),
        joins=((DfEngineGenerationResults, DfEngineGenerationResults.id == DfEngineGenerationFavourites.result_id),),
        filters=(
            DfEngineGenerationFavourites.user_id == user_id,  # type: ignore
            DfEngineGenerationResults.uid.in_(uids),  # type: ignore
        ),
    )
    favourited = {row[1]: row[0] for row in rows}
    if key:  # the references picker also flags the row itself
        for record in records:
            record["favourited"] = (record[key].get("file_uid") or "") in favourited
    for item in items:
        if not item.get("file_uid"):
            continue
        at = favourited.get(item["file_uid"])
        item["favourited_at"] = format_datetime(at)
        if action := item.get("action"):
            action["can_set_favorite"] = at is None
    return records


async def get_generation_main_refactored(
    ctx: ConnectionContext,
    viewer_id: int,
    project_id: Optional[int] = None,
    task_id: Optional[int] = None,
    song_id: Optional[int] = None,
    personal_file: bool = False,
    has_override: bool = False,
) -> list[dict[str, Any]]:
    main_generation_key = ctx.key.main_generations_refactored(
        viewer_id,
        project_id,
        task_id,
        song_id,
        personal_file,
        has_override,
    )
    main_generation = await get_json(ctx.redis, main_generation_key)
    if main_generation:
        return await overlay_favourites(ctx, main_generation, viewer_id)

    filters = [
        DfEngineGenerations.status.in_([GenerationStatuses.processing, GenerationStatuses.success]),  # type: ignore
        DfEngineGenerations.kind.in_(["image", "image_edit", "video"]),  # type: ignore
        or_(
            DfEngineGenerations.results.any(DfEngineGenerationResults.is_main.is_(True)),  # type: ignore
            and_(
                ~DfEngineGenerations.results.any(),  # type: ignore
                or_(
                    DfEngineGenerations.kind != "image_edit",  # type: ignore
                    ~DfEngineGenerations.generation_references.any(),  # type: ignore
                ),
            ),
        ),
    ]

    if personal_file:
        filters.append(DfEngineGenerations.created_by == viewer_id)
    if project_id:
        filters.append(DfEngineGenerations.project_id == project_id)
    if task_id:
        filters.append(DfEngineGenerations.task_id == task_id)
    if song_id:
        filters.append(DfEngineGenerations.song_id == song_id)

    options = [
        selectinload(DfEngineGenerations.model_option).load_only(DfEngineModelOptions.name),  # type: ignore
        selectinload(DfEngineGenerations.results.and_(DfEngineGenerationResults.is_main.is_(True)))  # type: ignore
        .selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
        .load_only(Users.image)  # type: ignore
        .selectinload(Users.employees)  # type: ignore
        .load_only(Employees.nickname),  # type: ignore
        selectinload(DfEngineGenerations.results.and_(DfEngineGenerationResults.is_main.is_(True)))  # type: ignore
        .selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
        .load_only(Users.image)  # type: ignore
        .selectinload(Users.employees)  # type: ignore
        .load_only(Employees.nickname),  # type: ignore
        selectinload(DfEngineGenerations.results.and_(DfEngineGenerationResults.is_main.is_(True))).selectinload(  # type: ignore
            _viewer_favourites(viewer_id)
        ),
        selectinload(DfEngineGenerations.generation_references)  # type: ignore
        .selectinload(DfEngineGenerationReferences.result)  # type: ignore
        .selectinload(DfEngineGenerationResults.generation)  # type: ignore
        .load_only(
            DfEngineGenerations.uid,  # type: ignore
            DfEngineGenerations.kind,  # type: ignore
            DfEngineGenerations.prompt,  # type: ignore
            DfEngineGenerations.full_prompt,  # type: ignore
            DfEngineGenerations.parameter,  # type: ignore
            DfEngineGenerations.task_id,  # type: ignore
            DfEngineGenerations.song_id,  # type: ignore
        ),
        selectinload(DfEngineGenerations.generation_references)  # type: ignore
        .selectinload(DfEngineGenerationReferences.result)  # type: ignore
        .selectinload(DfEngineGenerationResults.generation)  # type: ignore
        .selectinload(DfEngineGenerations.model_option)  # type: ignore
        .load_only(DfEngineModelOptions.name),  # type: ignore
        selectinload(DfEngineGenerations.generation_references)  # type: ignore
        .selectinload(DfEngineGenerationReferences.result)  # type: ignore
        .selectinload(DfEngineGenerationResults.generation)  # type: ignore
        .selectinload(DfEngineGenerations.task)  # type: ignore
        .load_only(ProjectTasks.name),  # type: ignore
        selectinload(DfEngineGenerations.generation_references)  # type: ignore
        .selectinload(DfEngineGenerationReferences.result)  # type: ignore
        .selectinload(DfEngineGenerationResults.generation)  # type: ignore
        .selectinload(DfEngineGenerations.song)  # type: ignore
        .load_only(ProjectSongLists.name),  # type: ignore
        selectinload(DfEngineGenerations.generation_references)  # type: ignore
        .selectinload(DfEngineGenerationReferences.result)  # type: ignore
        .selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
        .load_only(Users.image)  # type: ignore
        .selectinload(Users.employees)  # type: ignore
        .load_only(Employees.nickname),  # type: ignore
        selectinload(DfEngineGenerations.generation_references)  # type: ignore
        .selectinload(DfEngineGenerationReferences.result)  # type: ignore
        .selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
        .load_only(Users.image)  # type: ignore
        .selectinload(Users.employees)  # type: ignore
        .load_only(Employees.nickname),  # type: ignore
        selectinload(DfEngineGenerations.upload_file_references)  # type: ignore
        .selectinload(DfEngineUploadFileReferences.file)  # type: ignore
        .selectinload(DfEngineUploadFiles.created_by_user)  # type: ignore
        .load_only(Users.image)  # type: ignore
        .selectinload(Users.employees)  # type: ignore
        .load_only(Employees.nickname),  # type: ignore
        selectinload(DfEngineGenerations.upload_file_references)  # type: ignore
        .selectinload(DfEngineUploadFileReferences.file)  # type: ignore
        .selectinload(DfEngineUploadFiles.updated_by_user)  # type: ignore
        .load_only(Users.image)  # type: ignore
        .selectinload(Users.employees)  # type: ignore
        .load_only(Employees.nickname),  # type: ignore
        selectinload(DfEngineGenerations.upload_file_references)  # type: ignore
        .selectinload(DfEngineUploadFileReferences.file)  # type: ignore
        .selectinload(DfEngineUploadFiles.task)  # type: ignore
        .load_only(ProjectTasks.name),  # type: ignore
        selectinload(DfEngineGenerations.upload_file_references)  # type: ignore
        .selectinload(DfEngineUploadFileReferences.file)  # type: ignore
        .selectinload(DfEngineUploadFiles.song)  # type: ignore
        .load_only(ProjectSongLists.name),  # type: ignore
    ]
    if task_id or not song_id:
        options.append(selectinload(DfEngineGenerations.task).load_only(ProjectTasks.uid, ProjectTasks.name))  # type: ignore
    if song_id or not task_id:
        options.append(selectinload(DfEngineGenerations.song).load_only(ProjectSongLists.uid, ProjectSongLists.name))  # type: ignore

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        options=tuple(options),
        filters=tuple(filters),
        order_by=(
            DfEngineGenerations.created_at.desc(),  # type: ignore
            DfEngineGenerations.created_by.desc(),  # type: ignore
        ),
    )
    records = serialize(generations)

    families = {}
    roots = {result["parent_id"] or result["id"] for record in records for result in record["results"]}
    if roots:
        variant_rows = await query(
            ctx.db,
            DfEngineGenerationResults,
            filters=(
                or_(
                    DfEngineGenerationResults.id.in_(roots),  # type: ignore
                    DfEngineGenerationResults.parent_id.in_(roots),  # type: ignore
                ),
                DfEngineGenerationResults.archieved_at.is_(None),  # type: ignore
            ),
            options=(
                selectinload(DfEngineGenerationResults.generation).load_only(  # type: ignore
                    DfEngineGenerations.uid,  # type: ignore
                    DfEngineGenerations.kind,  # type: ignore
                    DfEngineGenerations.status,  # type: ignore
                    DfEngineGenerations.prompt,  # type: ignore
                    DfEngineGenerations.full_prompt,  # type: ignore
                    DfEngineGenerations.parameter,  # type: ignore
                    DfEngineGenerations.cost,  # type: ignore
                    DfEngineGenerations.task_id,  # type: ignore
                    DfEngineGenerations.song_id,  # type: ignore
                ),
                selectinload(DfEngineGenerationResults.generation)  # type: ignore
                .selectinload(DfEngineGenerations.model_option)  # type: ignore
                .load_only(DfEngineModelOptions.name),  # type: ignore
                selectinload(DfEngineGenerationResults.generation)  # type: ignore
                .selectinload(DfEngineGenerations.task)  # type: ignore
                .load_only(ProjectTasks.uid),  # type: ignore
                selectinload(DfEngineGenerationResults.generation)  # type: ignore
                .selectinload(DfEngineGenerations.song)  # type: ignore
                .load_only(ProjectSongLists.uid),  # type: ignore
                selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
                .load_only(Users.image)  # type: ignore
                .selectinload(Users.employees)  # type: ignore
                .load_only(Employees.nickname),  # type: ignore
                selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
                .load_only(Users.image)  # type: ignore
                .selectinload(Users.employees)  # type: ignore
                .load_only(Employees.nickname),  # type: ignore
                selectinload(_viewer_favourites(viewer_id)),
            ),
            order_by=(DfEngineGenerationResults.version.asc(),),  # type: ignore
        )
        for variant in serialize(variant_rows):
            families.setdefault(variant["parent_id"] or variant["id"], []).append(variant)

    files = []
    for record in records:
        task = (record.get("task") or record.get("song") or {}).get("name")
        references = []
        for ref in record["generation_references"]:
            source = ref["result"]
            source_generation = source["generation"]
            references.append(
                GenerationReference(
                    id=source["id"],
                    kind=source_generation["kind"],
                    file_uid=source["uid"],
                    task=(source_generation.get("task") or source_generation.get("song") or {}).get("name"),
                    name=source["name"],
                    path=source["path"],
                    size=source["size"],
                    version=source["version"],
                    created_at=source["created_at"],
                    model=(source_generation.get("model_option") or {}).get("name"),
                    prompt=source_generation.get("prompt"),
                    full_prompt=source_generation.get("full_prompt"),
                    parameter=source_generation.get("parameter"),
                    creator=format_user_employees(source.get("created_by_user")),
                    updater=format_user_employees(source.get("updated_by_user")),
                )
            )
        for ref in record["upload_file_references"]:
            file = ref["file"]
            references.append(
                GenerationReference(
                    id=file["id"],
                    kind=file["type"],
                    type="uploaded",
                    file_uid=file["uid"],
                    task=(file.get("task") or file.get("song") or {}).get("name"),
                    name=file["name"],
                    path=file["path"],
                    size=file["size"],
                    created_at=file["created_at"],
                    creator=format_user_employees(file.get("created_by_user")),
                    updater=format_user_employees(file.get("updated_by_user")),
                )
            )

        for result in record["results"] or [{}]:
            variants = []
            for variant in families.get(result.get("parent_id") or result.get("id"), []):
                variants.append(_build_variant(variant, record["kind"], task))

            files.append(
                UserGeneratedFile(
                    id=result.get("id"),
                    kind=record["kind"],
                    file_uid=result.get("uid"),
                    generation_uid=record["uid"],
                    parent_id=result.get("parent_id"),
                    name=result.get("name"),
                    path=result.get("path"),
                    size=result.get("size"),
                    is_main=result.get("is_main", False),
                    version=result.get("version"),
                    status=record["status"],
                    task_uid=(record.get("task") or {}).get("uid"),
                    song_uid=(record.get("song") or {}).get("uid"),
                    task=task,
                    created_at=result.get("created_at") or record["created_at"],
                    updated_at=result.get("updated_at"),
                    favourited_at=favourited_at_of(result),
                    archieved_at=result.get("archieved_at"),
                    cost_usd=format_usd(record["cost"]),
                    cost_idr=format_idr(record["cost"], USD_TO_IDR_RATE),
                    model=(record["model_option"] or {}).get("name"),
                    prompt=record["prompt"],
                    full_prompt=record["full_prompt"],
                    parameter=record["parameter"],
                    references=references,
                    variants=variants,
                    action=(
                        GeneratedFileAction.action(result["created_by"] == viewer_id, has_override, result)
                        if result
                        else GeneratedFileAction.disabled()
                    ),
                    creator=format_user_employees(result.get("created_by_user")),
                    updater=format_user_employees(result.get("updated_by_user")),
                ).model_dump(mode="json")
            )

    await set_json(ctx.redis, main_generation_key, files)
    return await overlay_favourites(ctx, files, viewer_id)


def _scope(task_id: Optional[int], song_id: Optional[int]) -> Any:
    """Generations belong to a project task (`task_id`) or a song (`song_id`), never both."""
    return DfEngineGenerations.song_id == song_id if song_id is not None else DfEngineGenerations.task_id == task_id


def _with_generation(result: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "generation": {
            "uid": record.get("uid"),
            "kind": record.get("kind"),
            "status": record.get("status"),
            "prompt": record.get("prompt"),
            "full_prompt": record.get("full_prompt"),
            "parameter": record.get("parameter"),
            "cost": record.get("cost"),
            "model_option": record.get("model_option"),
        },
    }


def _build_references(generation: dict[str, Any]) -> list[dict[str, Any]]:
    references = []
    for ref in generation.get("generation_references") or []:
        if result := ref.get("result"):
            references.append(GenerationReferenceRecord.from_result(result).model_dump(mode="json"))
    for ref in generation.get("upload_file_references") or []:
        if file := ref.get("file"):
            references.append(UploadedReferenceRecord.from_result(file).model_dump(mode="json"))
    return references


def _grant(records: list[dict[str, Any]], can_override: bool, key: Optional[str] = None) -> list[dict[str, Any]]:
    """Apply the override-role widening to records on their way out. Always called after the cache write/read, so the
    cached copy stays viewer-neutral."""
    if can_override:
        for record in records:
            grant_generation_override(record[key] if key else record)
    return records


def _grant_detail(detail: dict[str, Any], can_override: bool) -> dict[str, Any]:
    if can_override:
        grant_generation_override(detail)
        _grant(detail.get("variants") or [], True)
    return detail


def _drop(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        data.pop(key, None)
    return data


_MAIN_FILE_INTERNAL_KEYS = (
    "flag_created_at",
    "flag_favourited_at",
    "flag_archieved_at",
    "is_main",
    "version",
    "updated_at",
    "full_prompt",
    "parameter",
)


async def get_generation_main_files(
    ctx: ConnectionContext,
    user_id: int,
    task_id: int,
    my_task: bool = False,
    search: Optional[str] = None,
    can_override: bool = False,
    song_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Main files of one task (`task_id`) or one song (`song_id`)."""
    generation_main_key = ctx.key.generation_files_main_list(task_id, user_id if my_task else None, search, song_id)
    generation_main_files = await get_json(ctx.redis, generation_main_key)
    if generation_main_files is not None:
        logging.info(
            f"user={user_id} listed user galleries source=cache task_id={task_id} my_task={my_task} search={search}"
        )
        return await overlay_favourites(ctx, _grant(generation_main_files, can_override), user_id)

    filters = [
        _scope(task_id, song_id),
        DfEngineGenerations.status.in_([GenerationStatuses.success, GenerationStatuses.processing]),  # type: ignore
        DfEngineGenerations.kind.in_(["image", "image_edit", "video"]),  # type: ignore
        or_(
            DfEngineGenerations.results.any(DfEngineGenerationResults.is_main.is_(True)),  # type: ignore
            ~DfEngineGenerations.results.any(),  # type: ignore
        ),
    ]
    if search:
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                DfEngineGenerations.prompt.ilike(term),  # type: ignore
                DfEngineGenerations.model_option.has(DfEngineModelOptions.name.ilike(term)),  # type: ignore
                DfEngineGenerations.results.any(  # type: ignore
                    and_(DfEngineGenerationResults.is_main.is_(True), DfEngineGenerationResults.name.ilike(term))  # type: ignore
                ),
            )
        )
    if my_task:
        filters.append(DfEngineGenerations.created_by == user_id)  # type: ignore

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        options=(
            selectinload(
                DfEngineGenerations.results.and_(DfEngineGenerationResults.is_main.is_(True))  # type: ignore
            )
            .selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(
                DfEngineGenerations.results.and_(DfEngineGenerationResults.is_main.is_(True))  # type: ignore
            )
            .selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(
                DfEngineGenerations.results.and_(DfEngineGenerationResults.is_main.is_(True))  # type: ignore
            ).selectinload(_viewer_favourites(user_id)),
            selectinload(DfEngineGenerations.model_option).load_only(DfEngineModelOptions.name),  # type: ignore
            selectinload(DfEngineGenerations.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        ),
        filters=tuple(filters),
        order_by=(DfEngineGenerations.created_at.desc(),),  # type: ignore
    )

    generation_main_files = []
    for record in serialize(generations):
        results = record["results"]
        if results:
            for result in results:
                generation_main_files.append(
                    {
                        **_drop(
                            GenerationResultRecord.from_result(_with_generation(result, record), user_id).model_dump(
                                mode="json"
                            ),
                            *_MAIN_FILE_INTERNAL_KEYS,
                        ),
                        "updater": format_user_employees(result.get("updated_by_user")),  # shown in the file tree
                    }
                )
        else:
            generation_main_files.append(
                _drop(GenerationResultRecord.pending(record).model_dump(mode="json"), *_MAIN_FILE_INTERNAL_KEYS)
            )

    await set_json(ctx.redis, generation_main_key, generation_main_files)
    logging.info(
        f"user={user_id} listed user galleries source=db task_id={task_id} my_task={my_task} search={search} "
        f"count={len(generation_main_files)}"
    )
    return await overlay_favourites(ctx, _grant(generation_main_files, can_override), user_id)


def _failed_upload_variant(record: dict[str, Any]) -> dict[str, Any]:
    """A generation whose result never reached Udin: no result row, so only generation-level fields are filled."""
    task = record.get("task") or record.get("song") or {}
    return GenerationVariant(
        kind=record["kind"],
        generation_uid=record["uid"],
        is_main=False,
        status=record["status"],
        task_uid=(record.get("task") or {}).get("uid"),
        song_uid=(record.get("song") or {}).get("uid"),
        task=task.get("name"),
        created_at=record["created_at"],
        cost_usd=format_usd(record["cost"]),
        cost_idr=format_idr(record["cost"], USD_TO_IDR_RATE),
        model=(record["model_option"] or {}).get("name"),
        prompt=record["prompt"],
        full_prompt=record["full_prompt"],
        parameter=record["parameter"],
        creator=format_user_employees(record.get("created_by_user")),
    ).model_dump(mode="json")


async def get_failed_upload_generations(
    ctx: ConnectionContext,
    user_id: int,
    can_override: bool,
    project_id: Optional[int] = None,
    task_id: Optional[int] = None,
    song_id: Optional[int] = None,
    search: Optional[str] = None,
    generation_uid: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Generations whose Udin upload exhausted every automatic retry (`upload_status == failed`): the manual re-upload
    list. Not cached: it must reflect a re-upload the moment it succeeds."""
    filters = [
        DfEngineGenerationUploads.upload_status == UploadStatuses.failed,  # type: ignore
        DfEngineGenerations.kind.in_(["image", "image_edit", "video"]),  # type: ignore
    ]
    if not can_override:
        filters.append(DfEngineGenerations.created_by == user_id)  # type: ignore
    if generation_uid:
        filters.append(DfEngineGenerations.uid == generation_uid)  # type: ignore
    if project_id:
        filters.append(DfEngineGenerations.project_id == project_id)  # type: ignore
    if task_id:
        filters.append(DfEngineGenerations.task_id == task_id)  # type: ignore
    if song_id:
        filters.append(DfEngineGenerations.song_id == song_id)  # type: ignore
    if search:
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                DfEngineGenerations.model_option.has(DfEngineModelOptions.name.ilike(term)),  # type: ignore
                DfEngineGenerations.prompt.ilike(term),  # type: ignore
                DfEngineGenerations.song.has(ProjectSongLists.name.ilike(term)),  # type: ignore
                DfEngineGenerations.task.has(ProjectTasks.name.ilike(term)),  # type: ignore
            )
        )

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        joins=((DfEngineGenerationUploads, DfEngineGenerationUploads.generation_id == DfEngineGenerations.id),),
        options=(
            selectinload(DfEngineGenerations.model_option).load_only(DfEngineModelOptions.name),  # type: ignore
            selectinload(DfEngineGenerations.task).load_only(ProjectTasks.uid, ProjectTasks.name),  # type: ignore
            selectinload(DfEngineGenerations.song).load_only(ProjectSongLists.uid, ProjectSongLists.name),  # type: ignore
            selectinload(DfEngineGenerations.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        ),
        filters=tuple(filters),
        order_by=(DfEngineGenerations.created_at.desc(),),  # type: ignore
    )
    items = [_failed_upload_variant(record) for record in serialize(generations)]
    if items:
        # the lock is the source of truth for "an upload is queued or running" (sweep or manual)
        ids = [generation.id for generation in generations]
        locks = await ctx.redis.mget([ctx.key.generation_reupload_lock(gid) for gid in ids])
        for item, lock in zip(items, locks):
            item["action"] = FailedUploadAction(can_reupload=lock is None).model_dump()
    logging.info(f"user={user_id} listed failed upload generations count={len(items)} override={can_override}")
    return items


async def get_archieved_files(
    ctx: ConnectionContext,
    user_id: int,
    project_id: Optional[int] = None,
    task_id: Optional[int] = None,
    song_id: Optional[int] = None,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Every file `user_id` created and archived, newest archive first. `project_id`, `task_id` and `song_id`
    narrow it when given (combined with AND). `search` matches the file name or path, the project name, or the
    task name."""
    archived_key = ctx.key.generation_files_archived_list(user_id, project_id, task_id, song_id, search)
    data = await get_json(ctx.redis, archived_key)
    if data is not None:
        logging.info(f"user={user_id} listed archived generations source=cache project_id={project_id}")
        return await overlay_favourites(ctx, data, user_id)

    mine = and_(
        DfEngineGenerationResults.archieved_at.is_not(None),  # type: ignore
        DfEngineGenerationResults.created_by == user_id,  # type: ignore
    )
    filters = []
    if search and search.strip():
        term = f"%{search.strip()}%"
        mine = and_(
            mine,
            or_(
                DfEngineGenerationResults.name.ilike(term),  # type: ignore
                DfEngineGenerationResults.path.ilike(term),  # type: ignore
                DfEngineGenerationResults.generation.has(  # type: ignore
                    or_(
                        DfEngineGenerations.project.has(Projects.name.ilike(term)),  # type: ignore
                        DfEngineGenerations.task.has(ProjectTasks.name.ilike(term)),  # type: ignore
                    )
                ),
            ),
        )
    for column, value in (
        (DfEngineGenerations.project_id, project_id),
        (DfEngineGenerations.task_id, task_id),
        (DfEngineGenerations.song_id, song_id),
    ):
        if value is not None:
            filters.append(column == value)

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        options=(
            selectinload(DfEngineGenerations.results.and_(mine)).selectinload(  # type: ignore
                _viewer_favourites(user_id)
            ),
            selectinload(DfEngineGenerations.project),
            selectinload(DfEngineGenerations.task),
            selectinload(DfEngineGenerations.song),
            selectinload(DfEngineGenerations.model_option),
        ),
        filters=(
            *filters,
            DfEngineGenerations.results.any(mine),  # type: ignore
        ),
    )

    archieved_files = []
    for record in serialize(generations):
        for result in record["results"]:
            file = UserGeneratedFile(
                id=result["id"],
                kind=record["kind"],
                file_uid=result["uid"],
                generation_uid=record["uid"],
                parent_id=result.get("parent_id"),
                name=result["name"],
                path=result["path"],
                size=result["size"],
                is_main=result["is_main"],
                version=result["version"],
                status=record["status"],
                task_uid=(record.get("task") or {}).get("uid"),
                song_uid=(record.get("song") or {}).get("uid"),
                task=(record.get("task") or record.get("song") or {}).get("name"),
                created_at=result["created_at"],
                updated_at=result["updated_at"],
                favourited_at=favourited_at_of(result),
                archieved_at=result["archieved_at"],
                cost_usd=format_usd(record["cost"]),
                cost_idr=format_idr(record["cost"], USD_TO_IDR_RATE),
                model=(record.get("model_option") or {}).get("name"),
                prompt=record["prompt"],
                full_prompt=record["full_prompt"],
                parameter=record["parameter"],
                action=GeneratedFileAction.action(True, False, result),  # only the viewer's own files are listed
                creator=format_user_employees(result.get("created_by_user")),
                updater=format_user_employees(result.get("updated_by_user")),
            ).model_dump(mode="json", exclude={"variants", "references"})
            archieved_files.append({**file, "project": (record.get("project") or {}).get("name")})
    archieved_files.sort(key=lambda r: r["archieved_at"] or "", reverse=True)

    await set_json(ctx.redis, archived_key, archieved_files)
    logging.info(
        f"user={user_id} listed archived generations source=db project_id={project_id} task_id={task_id} "
        f"song_id={song_id} count={len(archieved_files)}"
    )
    return await overlay_favourites(ctx, archieved_files, user_id)


async def get_enhance_prompt(ctx: ConnectionContext, enhance_uid: UUID) -> dict[str, Any]:
    enhancer_key = ctx.key.enhancer_detail(str(enhance_uid))
    cached = await get_json(ctx.redis, enhancer_key)
    if cached is not None:
        logging.info(f"enhance_uid={enhance_uid} fetched enhanced prompt source=cache")
        return cached

    generation = await query(
        ctx.db,
        DfEngineGenerations,
        filters=(
            DfEngineGenerations.uid == str(enhance_uid),  # type: ignore
            DfEngineGenerations.kind == GenerationKinds.enhancer,  # type: ignore
        ),
        fetch_one=True,
    )
    if not generation:
        raise DataNotFoundError(message="enhanced_prompt_not_found")

    data = {
        "id": generation.id,
        "prompt": generation.prompt,
        "full_prompt": generation.full_prompt,
        "enhance_uid": str(generation.uid),
        "response": generation.response,
    }
    await set_json(ctx.redis, enhancer_key, data)
    logging.info(f"enhance_uid={enhance_uid} fetched enhanced prompt source=db")
    return data


async def get_generation_files(
    ctx: ConnectionContext,
    user_id: Optional[int] = None,
    task_id: Optional[int] = None,
    song_id: Optional[int] = None,
    file_uids: Optional[list[str]] = None,
    can_override: bool = False,
) -> list[dict[str, Any]]:
    if not file_uids and not user_id and task_id is None and song_id is None:
        return []

    user_generation_files_key = ctx.key.generation_files_result_list(user_id, task_id, song_id, file_uids)
    data = await get_json(ctx.redis, user_generation_files_key) if user_id else None
    if data is not None:
        logging.info(f"user={user_id} listed generation files source=cache task_id={task_id} song_id={song_id}")
        return await overlay_favourites(ctx, _grant(data, can_override), user_id)

    filters = [DfEngineGenerations.results.any()]  # type: ignore
    if task_id is not None or song_id is not None:
        filters.append(_scope(task_id, song_id))
    if file_uids:
        filters.append(
            DfEngineGenerations.results.any(DfEngineGenerationResults.uid.in_(file_uids))  # type: ignore
        )
    if user_id:
        filters.append(DfEngineGenerations.created_by == user_id)  # type: ignore

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        options=(
            (selectinload(DfEngineGenerations.results).selectinload(_viewer_favourites(user_id)),)  # type: ignore
            if user_id
            else (selectinload(DfEngineGenerations.results),)  # type: ignore
        ),
        filters=tuple(filters),
    )

    generation_files = sorted(
        (
            _drop(
                GenerationResultRecord.from_result(_with_generation(result, record), user_id).model_dump(mode="json"),
                "updated_at",
                "status",
                "creator",
                "cost_usd",
                "cost_idr",
                "model",
                "prompt",
                "full_prompt",
                "parameter",
            )
            for record in serialize(generations)
            for result in record["results"]
            if not file_uids or result["uid"] in file_uids
        ),
        key=lambda r: r["flag_created_at"],
        reverse=True,
    )

    if file_uids:
        found_uids = {file["file_uid"] for file in generation_files}
        for idx, file_uid in enumerate(file_uids):
            if file_uid not in found_uids:
                raise DataNotFoundError(
                    message="file_not_found", error={f"references.{idx}.generated": ["file_not_found"]}
                )

    if user_id:
        await set_json(ctx.redis, user_generation_files_key, generation_files)
    logging.info(
        f"user={user_id} listed generation files source=db task_id={task_id} song_id={song_id} count={len(generation_files)}"
    )
    return await overlay_favourites(ctx, _grant(generation_files, can_override), user_id)


async def get_favourited_files(
    ctx: ConnectionContext,
    user_id: int,
    project_id: Optional[int] = None,
    task_id: Optional[int] = None,
    song_id: Optional[int] = None,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Every generated file `user_id` favourited (own or someone else's), newest favourite first, as flat
    `UserGeneratedFile`s (no variants/references) with the `project` name. `project_id`, `task_id` and `song_id`
    narrow it when given. `search` matches the file name or path, the project name, or the task name."""
    favourited_key = ctx.key.generation_files_favourited_list(user_id, project_id, task_id, song_id, search)
    data = await get_json(ctx.redis, favourited_key)
    if data is not None:
        logging.info(f"user={user_id} listed favourited generations source=cache project_id={project_id}")
        return data

    generation_filters = [DfEngineGenerations.kind.in_(["image", "image_edit", "video"])]  # type: ignore
    for column, value in (
        (DfEngineGenerations.project_id, project_id),
        (DfEngineGenerations.task_id, task_id),
        (DfEngineGenerations.song_id, song_id),
    ):
        if value is not None:
            generation_filters.append(column == value)
    result_filters = [DfEngineGenerationResults.favourites.any(DfEngineGenerationFavourites.user_id == user_id)]  # type: ignore
    if search and search.strip():
        term = f"%{search.strip()}%"
        result_filters.append(
            or_(
                DfEngineGenerationResults.name.ilike(term),  # type: ignore
                DfEngineGenerationResults.path.ilike(term),  # type: ignore
                DfEngineGenerationResults.generation.has(  # type: ignore
                    or_(
                        DfEngineGenerations.project.has(Projects.name.ilike(term)),  # type: ignore
                        DfEngineGenerations.task.has(ProjectTasks.name.ilike(term)),  # type: ignore
                    )
                ),
            )
        )

    rows = await query(
        ctx.db,
        DfEngineGenerationResults,
        options=(
            selectinload(_viewer_favourites(user_id)),
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .load_only(
                DfEngineGenerations.uid,  # type: ignore
                DfEngineGenerations.kind,  # type: ignore
                DfEngineGenerations.status,  # type: ignore
                DfEngineGenerations.prompt,  # type: ignore
                DfEngineGenerations.full_prompt,  # type: ignore
                DfEngineGenerations.parameter,  # type: ignore
                DfEngineGenerations.cost,  # type: ignore
                DfEngineGenerations.task_id,  # type: ignore
                DfEngineGenerations.song_id,  # type: ignore
            )
            .selectinload(DfEngineGenerations.model_option)  # type: ignore
            .load_only(DfEngineModelOptions.name),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.project)  # type: ignore
            .load_only(Projects.name),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.task)  # type: ignore
            .load_only(ProjectTasks.uid, ProjectTasks.name),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.song)  # type: ignore
            .load_only(ProjectSongLists.uid, ProjectSongLists.name),  # type: ignore
            selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        ),
        filters=(
            *result_filters,
            DfEngineGenerationResults.generation.has(and_(*generation_filters)),  # type: ignore
        ),
    )

    serialized = sorted(serialize(rows), key=lambda row: row["favourites"][0]["favourited_at"], reverse=True)
    favourited_files = []
    for row in serialized:
        generation = row["generation"]
        file = UserGeneratedFile(
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
            task_uid=(generation.get("task") or {}).get("uid"),
            song_uid=(generation.get("song") or {}).get("uid"),
            task=(generation.get("task") or generation.get("song") or {}).get("name"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            favourited_at=favourited_at_of(row),
            archieved_at=row["archieved_at"],
            cost_usd=format_usd(generation.get("cost")),
            cost_idr=format_idr(generation.get("cost"), USD_TO_IDR_RATE),
            model=(generation.get("model_option") or {}).get("name"),
            prompt=generation.get("prompt"),
            full_prompt=generation.get("full_prompt"),
            parameter=generation.get("parameter"),
            action=GeneratedFileAction.action(row["created_by"] == user_id, False, row),
            creator=format_user_employees(row.get("created_by_user")),
            updater=format_user_employees(row.get("updated_by_user")),
        ).model_dump(mode="json", exclude={"variants", "references"})
        favourited_files.append({**file, "project": (generation.get("project") or {}).get("name")})

    await set_json(ctx.redis, favourited_key, favourited_files)
    logging.info(
        f"user={user_id} listed favourited generations source=db project_id={project_id} task_id={task_id} "
        f"song_id={song_id} count={len(favourited_files)}"
    )
    return favourited_files


async def get_upload_references(
    ctx: ConnectionContext, user_id: int, project_id: Optional[int] = None, search: Optional[str] = None
) -> list[dict[str, Any]]:
    """Uploads of one project (anyone's) when `project_id` is given, else the caller's across all projects. The
    project-wide list is not cached: it is keyed and invalidated per user, so another member's upload would leave it stale."""
    references_picker_key = ctx.key.generation_files_references_picker("uploads", user_id, project_id, search)
    data = None if project_id else await get_json(ctx.redis, references_picker_key)
    if data is not None:
        logging.info(
            f"user={user_id} listed upload references source=cache project_id={project_id} search={search} count={len(data)}"
        )
        return data

    filters = [
        DfEngineUploadFiles.project_id == project_id if project_id else DfEngineUploadFiles.created_by == user_id
    ]  # type: ignore
    if search:
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                DfEngineUploadFiles.name.ilike(term),  # type: ignore
                DfEngineUploadFiles.project.has(Projects.name.ilike(term)),  # type: ignore
                DfEngineUploadFiles.task.has(ProjectTasks.name.ilike(term)),  # type: ignore
            )
        )

    uploads = await query(
        ctx.db,
        DfEngineUploadFiles,
        options=(
            selectinload(DfEngineUploadFiles.project),  # type: ignore
            selectinload(DfEngineUploadFiles.task),  # type: ignore
            selectinload(DfEngineUploadFiles.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        ),
        filters=tuple(filters),
        order_by=(DfEngineUploadFiles.created_at.desc(),),  # type: ignore
    )

    rows = [
        {
            "project_id": record["project_id"],
            "project_name": record["project"]["name"] if record["project"] else None,
            "task_id": record["task_id"],
            "task_name": record["task"]["name"] if record["task"] else None,
            "kind": record["type"],
            "file": UploadedReferenceRecord.from_result(record).model_dump(mode="json"),
        }
        for record in serialize(uploads)
    ]

    if not project_id:
        await set_json(ctx.redis, references_picker_key, rows)

    logging.info(
        f"user={user_id} listed upload references source=db project_id={project_id} search={search} count={len(rows)}"
    )
    return rows


async def get_generation_references(
    ctx: ConnectionContext,
    user_id: int,
    project_id: Optional[int] = None,
    search: Optional[str] = None,
    can_override: bool = False,
) -> list[dict[str, Any]]:
    references_picker_key = ctx.key.generation_files_references_picker("generations", user_id, project_id, search)
    data = await get_json(ctx.redis, references_picker_key)
    if data is not None:
        logging.info(
            f"user={user_id} listed generation references source=cache project_id={project_id} search={search} count={len(data)}"
        )
        return await overlay_favourites(ctx, _grant(data, can_override, "file"), user_id, "file")

    filters = [
        DfEngineGenerations.results.any(DfEngineGenerationResults.is_main.is_(True)),  # type: ignore
    ]
    if project_id:
        filters.append(DfEngineGenerations.project_id == project_id)  # type: ignore
    if search:
        term = f"{search.strip()}%"
        filters.append(
            or_(
                DfEngineGenerations.prompt.ilike(term),  # type: ignore
                DfEngineGenerations.project.has(Projects.name.ilike(term)),  # type: ignore
                DfEngineGenerations.task.has(ProjectTasks.name.ilike(term)),  # type: ignore
                DfEngineGenerations.model_option.has(DfEngineModelOptions.name.ilike(term)),  # type: ignore
                DfEngineGenerations.results.any(  # type: ignore
                    and_(DfEngineGenerationResults.is_main.is_(True), DfEngineGenerationResults.name.ilike(term))  # type: ignore
                ),
            )
        )

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        options=(
            selectinload(DfEngineGenerations.project),  # type: ignore
            selectinload(DfEngineGenerations.task),  # type: ignore
            selectinload(DfEngineGenerations.model_option).load_only(DfEngineModelOptions.name),  # type: ignore
            selectinload(
                DfEngineGenerations.results.and_(DfEngineGenerationResults.is_main.is_(True))  # type: ignore
            )
            .selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(
                DfEngineGenerations.results.and_(DfEngineGenerationResults.is_main.is_(True))  # type: ignore
            ).selectinload(_viewer_favourites(user_id)),
        ),
        filters=tuple(filters),
        order_by=(DfEngineGenerations.created_at.desc(),),  # type: ignore
    )

    rows = [
        {
            "project_id": record["project_id"],
            "project_name": record["project"]["name"] if record["project"] else None,
            "task_id": record["task_id"],
            "task_name": record["task"]["name"] if record["task"] else None,
            "kind": record["kind"],
            "favourited": favourited_at_of(result) is not None,
            "file": _drop(
                GenerationResultRecord.from_result(_with_generation(result, record), user_id).model_dump(mode="json"),
                *_MAIN_FILE_INTERNAL_KEYS,
                "cost_usd",
                "cost_idr",
                "prompt",
            ),
        }
        for record in serialize(generations)
        for result in record["results"]
    ]

    await set_json(ctx.redis, references_picker_key, rows)

    logging.info(
        f"user={user_id} listed generation references source=db project_id={project_id} search={search} count={len(rows)}"
    )
    return await overlay_favourites(ctx, _grant(rows, can_override, "file"), user_id, "file")


async def get_generation_main_file_detail(
    ctx: ConnectionContext, file_uid: UUID, user_id: Optional[int] = None, can_override: bool = False
) -> dict[str, Any]:
    generated_main_file_detail_key = ctx.key.generation_files_main_detail(file_uid)
    generated_main_file_detail_cached = await get_json(ctx.redis, generated_main_file_detail_key)
    if generated_main_file_detail_cached is not None:
        logging.info(f"file_uid={file_uid} fetched generation main file detail source=cache")
        return await overlay_favourites(ctx, _grant_detail(generated_main_file_detail_cached, can_override), user_id)

    group_id = (
        select(func.coalesce(DfEngineGenerationResults.parent_id, DfEngineGenerationResults.id))
        .where(DfEngineGenerationResults.uid == str(file_uid))  # type: ignore
        .scalar_subquery()
    )

    main_file = await query(
        ctx.db,
        DfEngineGenerationResults,
        filters=(
            or_(
                DfEngineGenerationResults.id == group_id,  # type: ignore
                DfEngineGenerationResults.parent_id == group_id,  # type: ignore
            ),
            DfEngineGenerationResults.is_main.is_(True),  # type: ignore
        ),
        options=(
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .load_only(
                DfEngineGenerations.uid,  # type: ignore
                DfEngineGenerations.kind,  # type: ignore
                DfEngineGenerations.prompt,  # type: ignore
                DfEngineGenerations.full_prompt,  # type: ignore
                DfEngineGenerations.parameter,  # type: ignore
                DfEngineGenerations.cost,  # type: ignore
            )
            .selectinload(DfEngineGenerations.model_option)  # type: ignore
            .load_only(DfEngineModelOptions.name),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.generation_references)  # type: ignore
            .selectinload(DfEngineGenerationReferences.result)  # type: ignore
            .selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.model_option),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.generation_references)  # type: ignore
            .selectinload(DfEngineGenerationReferences.result)  # type: ignore
            .selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.upload_file_references)  # type: ignore
            .selectinload(DfEngineUploadFileReferences.file),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.upload_file_references)  # type: ignore
            .selectinload(DfEngineUploadFileReferences.file)  # type: ignore
            .selectinload(DfEngineUploadFiles.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(_viewer_favourites(user_id or -1)),
            selectinload(DfEngineGenerationResults.children)  # type: ignore
            .selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .load_only(
                DfEngineGenerations.kind,  # type: ignore
                DfEngineGenerations.prompt,  # type: ignore
                DfEngineGenerations.full_prompt,  # type: ignore
                DfEngineGenerations.parameter,  # type: ignore
                DfEngineGenerations.cost,  # type: ignore
            ),
        ),
        fetch_one=True,
        order_by=(DfEngineGenerationResults.created_at.desc(),),  # type: ignore
    )
    if not main_file:
        logging.warning(f"file_uid={file_uid} main generation file not found")
        raise DataNotFoundError(message="main_generation_file_not_found")

    serialized_main_file = serialize(main_file)
    serialized = _drop(
        GenerationResultRecord.from_result(serialized_main_file, user_id).model_dump(mode="json"),
        "flag_created_at",
        "flag_favourited_at",
        "flag_archieved_at",
    )
    # archived versions stay fetchable by their own uid but are not listed as variants of the main file
    serialized["variants"] = [
        variant for variant in await get_generation_main_variants(ctx, file_uid, user_id) if not variant["archieved_at"]
    ]
    serialized["references"] = _build_references(serialized_main_file.get("generation") or {})

    await set_json(ctx.redis, generated_main_file_detail_key, serialized)
    logging.info(
        f"file_uid={file_uid} fetched generation main file detail source=db is_main={serialized['is_main']} "
        f"references={len(serialized['references'])}"
    )
    return await overlay_favourites(ctx, _grant_detail(serialized, can_override), user_id)


async def get_generation_main_variants(
    ctx: ConnectionContext, file_uid: UUID, user_id: Optional[int] = None, can_override: bool = False
) -> list[dict[str, Any]]:
    generation_variants_key = ctx.key.generation_files_variants_detail(file_uid)
    generation_variants_cached = await get_json(ctx.redis, generation_variants_key)
    if generation_variants_cached is not None:
        logging.info(f"file_uid={file_uid} fetched generation variants source=cache")
        return await overlay_favourites(ctx, _grant(generation_variants_cached, can_override), user_id)

    group_id = (
        select(func.coalesce(DfEngineGenerationResults.parent_id, DfEngineGenerationResults.id))
        .where(DfEngineGenerationResults.uid == str(file_uid))  # type: ignore
        .scalar_subquery()
    )

    variant_rows = await query(
        ctx.db,
        DfEngineGenerationResults,
        filters=(
            or_(
                DfEngineGenerationResults.id == group_id,  # type: ignore
                DfEngineGenerationResults.parent_id == group_id,  # type: ignore
            ),
        ),
        options=(
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .load_only(
                DfEngineGenerations.kind,  # type: ignore
                DfEngineGenerations.prompt,  # type: ignore
                DfEngineGenerations.full_prompt,  # type: ignore
                DfEngineGenerations.parameter,  # type: ignore
                DfEngineGenerations.cost,  # type: ignore
            )
            .selectinload(DfEngineGenerations.model_option)  # type: ignore
            .load_only(DfEngineModelOptions.name),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.generation_references)  # type: ignore
            .selectinload(DfEngineGenerationReferences.result)  # type: ignore
            .selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.model_option),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.generation_references)  # type: ignore
            .selectinload(DfEngineGenerationReferences.result)  # type: ignore
            .selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.upload_file_references)  # type: ignore
            .selectinload(DfEngineUploadFileReferences.file),  # type: ignore
            selectinload(DfEngineGenerationResults.generation)  # type: ignore
            .selectinload(DfEngineGenerations.upload_file_references)  # type: ignore
            .selectinload(DfEngineUploadFileReferences.file)  # type: ignore
            .selectinload(DfEngineUploadFiles.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(_viewer_favourites(user_id or -1)),
        ),
        order_by=(DfEngineGenerationResults.version.asc(),),  # type: ignore
    )
    if not variant_rows:
        logging.warning(f"file_uid={file_uid} generation variants not found")
        raise DataNotFoundError(message="main_generation_file_not_found")

    variants = []
    for row in serialize(variant_rows):
        variant = _drop(
            GenerationResultRecord.from_result(row, user_id).model_dump(mode="json"),
            "flag_created_at",
            "flag_favourited_at",
            "flag_archieved_at",
        )
        variant["references"] = _build_references(row.get("generation") or {})
        variants.append(variant)

    await set_json(ctx.redis, generation_variants_key, variants)
    logging.info(f"file_uid={file_uid} fetched generation variants source=db count={len(variants)}")
    return await overlay_favourites(ctx, _grant(variants, can_override), user_id)
