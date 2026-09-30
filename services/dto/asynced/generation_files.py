from uuid import UUID
from typing import Any, Optional
from services.redis import get_json, set_json
from sqlalchemy import or_, and_, func, select
from sqlalchemy.orm import selectinload
from services.mysql.model import (
    DfEngineGenerations,
    DfEngineGenerationReferences,
    DfEngineGenerationResults,
    DfEngineModelOptions,
    DfEngineUploadFiles,
    DfEngineUploadFileReferences,
    Users,
    Employees,
    Projects,
    ProjectTasks,
)
from services.mysql.model.df_engine_generations import GenerationKinds
from log import logging
from error import DataNotFoundError, DataValidationError
from services.mysql import query
from utils.serializer import serialize
from services.dto import ConnectionContext
from services.dto.format_response import GenerationResultRecord, GenerationReferenceRecord, UploadedReferenceRecord


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


def _drop(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        data.pop(key, None)
    return data


async def get_generation_main_files(
    ctx: ConnectionContext, user_id: int, task_id: int, owner_id: Optional[int] = None, search: Optional[str] = None
) -> list[dict[str, Any]]:
    generation_main_key = ctx.key.generation_files_main_list(task_id, owner_id, search)
    generation_main_files = await get_json(ctx.redis, generation_main_key)
    if generation_main_files is not None:
        logging.info(
            f"user={user_id} listed user galleries source=cache task_id={task_id} owner_id={owner_id} search={search}"
        )
        return generation_main_files

    filters = [
        DfEngineGenerations.task_id == task_id,
        DfEngineGenerations.results.any(DfEngineGenerationResults.is_main.is_(True)),  # type: ignore
    ]
    if search:
        term = f"{search.strip()}%"
        filters.append(
            or_(
                DfEngineGenerations.prompt.ilike(term),  # type: ignore
                DfEngineGenerations.model_option.has(DfEngineModelOptions.name.ilike(term)),  # type: ignore
                DfEngineGenerations.results.any(  # type: ignore
                    and_(DfEngineGenerationResults.is_main.is_(True), DfEngineGenerationResults.name.ilike(term))  # type: ignore
                ),
            )
        )
    if owner_id:
        filters.append(
            DfEngineGenerations.results.any(  # type: ignore
                and_(DfEngineGenerationResults.is_main.is_(True), DfEngineGenerationResults.created_by == owner_id)  # type: ignore
            )
        )

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
            selectinload(DfEngineGenerations.model_option).load_only(DfEngineModelOptions.name),  # type: ignore
        ),
        filters=tuple(filters),
        order_by=(DfEngineGenerations.created_at.desc(),),  # type: ignore
    )

    generation_main_files = [
        _drop(
            GenerationResultRecord.from_result(_with_generation(result, record), user_id).model_dump(mode="json"),
            "flag_created_at",
            "flag_favourited_at",
            "flag_archieved_at",
            "is_main",
            "version",
            "updated_at",
            "full_prompt",
            "parameter",
        )
        for record in serialize(generations)
        for result in record["results"]
    ]

    await set_json(ctx.redis, generation_main_key, generation_main_files)
    logging.info(
        f"user={user_id} listed user galleries source=db task_id={task_id} owner_id={owner_id} search={search} "
        f"count={len(generation_main_files)}"
    )
    return generation_main_files


async def get_archieved_files(ctx: ConnectionContext, project_id: int, user_id: int) -> list[dict[str, Any]]:
    archived_key = ctx.key.generation_files_archived_list(user_id, project_id)
    data = await get_json(ctx.redis, archived_key)
    if data:
        logging.info(f"user={user_id} listed archived generations source=cache project_id={project_id}")
        return data

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        options=(
            selectinload(
                DfEngineGenerations.results.and_(DfEngineGenerationResults.archieved_at.is_not(None))  # type: ignore
            ),
        ),
        filters=(
            DfEngineGenerations.project_id == project_id,
            DfEngineGenerations.created_by == user_id,
            DfEngineGenerations.results.any(DfEngineGenerationResults.archieved_at.is_not(None)),  # type: ignore
        ),
    )

    archieved_files = sorted(
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
                "parent_id",
            )
            for record in serialize(generations)
            for result in record["results"]
        ),
        key=lambda r: r["flag_archieved_at"],
        reverse=True,
    )

    await set_json(ctx.redis, archived_key, archieved_files)
    logging.info(
        f"user={user_id} listed archived generations source=db project_id={project_id} count={len(archieved_files)}"
    )
    return archieved_files


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
    project_id: Optional[int] = None,
    file_uids: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    if not file_uids and not user_id and not project_id:
        return []

    user_generation_files_key = ctx.key.generation_files_result_list(user_id, project_id, file_uids)
    data = await get_json(ctx.redis, user_generation_files_key)
    if data is not None:
        logging.info(f"user={user_id} listed generation files source=cache project_id={project_id}")
        return data

    filters = [DfEngineGenerations.results.any()]  # type: ignore
    if project_id:
        filters.append(DfEngineGenerations.project_id == project_id)  # type: ignore
    if file_uids:
        filters.append(
            DfEngineGenerations.results.any(DfEngineGenerationResults.uid.in_(file_uids))  # type: ignore
        )
    if user_id:
        filters.append(DfEngineGenerations.created_by == user_id)  # type: ignore

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        options=(selectinload(DfEngineGenerations.results),),  # type: ignore
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
                raise DataNotFoundError(message="file_not_found", error={f"file_uids.{idx}": ["file_not_found"]})

    await set_json(ctx.redis, user_generation_files_key, generation_files)
    logging.info(
        f"user={user_id} listed generation files source=db project_id={project_id} count={len(generation_files)}"
    )
    return generation_files


async def get_favourited_files(ctx: ConnectionContext, project_id: int, user_id: int) -> list[dict[str, Any]]:
    favourited_key = ctx.key.generation_files_favourited_list(user_id, project_id)
    data = await get_json(ctx.redis, favourited_key)
    if data is not None:
        logging.info(f"user={user_id} listed favourited generations source=cache project_id={project_id}")
        return data

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        options=(
            selectinload(
                DfEngineGenerations.results.and_(DfEngineGenerationResults.favourited_at.is_not(None))  # type: ignore
            ),
        ),
        filters=(
            DfEngineGenerations.project_id == project_id,
            DfEngineGenerations.created_by == user_id,
            DfEngineGenerations.results.any(DfEngineGenerationResults.favourited_at.is_not(None)),  # type: ignore
        ),
    )

    favourited_files = sorted(
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
                "parent_id",
            )
            for record in serialize(generations)
            for result in record["results"]
        ),
        key=lambda r: r["flag_favourited_at"],
        reverse=True,
    )

    await set_json(ctx.redis, favourited_key, favourited_files)
    logging.info(
        f"user={user_id} listed favourited generations source=db project_id={project_id} count={len(favourited_files)}"
    )
    return favourited_files


async def get_upload_references(
    ctx: ConnectionContext, user_id: int, project_id: Optional[int] = None, search: Optional[str] = None
) -> list[dict[str, Any]]:
    references_picker_key = ctx.key.generation_files_references_picker("uploads", user_id, project_id, search)
    data = await get_json(ctx.redis, references_picker_key)
    if data is not None:
        logging.info(
            f"user={user_id} listed upload references source=cache project_id={project_id} search={search} count={len(data)}"
        )
        return data

    filters = [DfEngineUploadFiles.created_by == user_id]  # type: ignore
    if project_id:
        filters.append(DfEngineUploadFiles.project_id == project_id)  # type: ignore
    if search:
        term = f"{search.strip()}%"
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

    await set_json(ctx.redis, references_picker_key, rows)

    logging.info(
        f"user={user_id} listed upload references source=db project_id={project_id} search={search} count={len(rows)}"
    )
    return rows


async def get_generation_references(
    ctx: ConnectionContext, user_id: int, project_id: Optional[int] = None, search: Optional[str] = None
) -> list[dict[str, Any]]:
    references_picker_key = ctx.key.generation_files_references_picker("generations", user_id, project_id, search)
    data = await get_json(ctx.redis, references_picker_key)
    if data is not None:
        logging.info(
            f"user={user_id} listed generation references source=cache project_id={project_id} search={search} count={len(data)}"
        )
        return data

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
            "favourited": result["favourited_at"] is not None and result["created_by"] == user_id,
            "file": GenerationReferenceRecord.from_result(_with_generation(result, record)).model_dump(mode="json"),
        }
        for record in serialize(generations)
        for result in record["results"]
    ]

    await set_json(ctx.redis, references_picker_key, rows)

    logging.info(
        f"user={user_id} listed generation references source=db project_id={project_id} search={search} count={len(rows)}"
    )
    return rows


async def get_generation_main_file_detail(
    ctx: ConnectionContext, file_uid: UUID, user_id: Optional[int] = None
) -> dict[str, Any]:
    generated_main_file_detail_key = ctx.key.generation_files_main_detail(file_uid)
    generated_main_file_detail_cached = await get_json(ctx.redis, generated_main_file_detail_key)
    if generated_main_file_detail_cached is not None:
        logging.info(f"file_uid={file_uid} fetched generation main file detail source=cache")
        return generated_main_file_detail_cached

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
    serialized["variants"] = await get_generation_main_variants(ctx, file_uid, user_id)
    serialized["references"] = _build_references(serialized_main_file.get("generation") or {})

    await set_json(ctx.redis, generated_main_file_detail_key, serialized)
    logging.info(
        f"file_uid={file_uid} fetched generation main file detail source=db is_main={serialized['is_main']} "
        f"references={len(serialized['references'])}"
    )
    return serialized


async def get_generation_main_variants(
    ctx: ConnectionContext, file_uid: UUID, user_id: Optional[int] = None
) -> list[dict[str, Any]]:
    generation_variants_key = ctx.key.generation_files_variants_detail(file_uid)
    generation_variants_cached = await get_json(ctx.redis, generation_variants_key)
    if generation_variants_cached is not None:
        logging.info(f"file_uid={file_uid} fetched generation variants source=cache")
        return generation_variants_cached

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
    return variants
