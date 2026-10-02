from typing import Any
from sqlalchemy.orm import selectinload
from services.mysql import query
from services.mysql.model import DfEngineUploadFiles, Users, Employees
from services.dto import ConnectionContext
from services.dto.format_response import UploadedFileRecord
from services.redis import get_json, set_json
from error import DataNotFoundError
from utils.serializer import serialize


async def get_uploaded_files(ctx: ConnectionContext, file_uids: list[str]) -> list[dict[str, Any]]:
    cache_key = ctx.key.uploaded_files(file_uids)
    data = await get_json(ctx.redis, cache_key)
    if data is not None:
        return data

    files = await query(
        ctx.db,
        DfEngineUploadFiles,
        filters=(DfEngineUploadFiles.uid.in_(file_uids),),  # type: ignore
        options=(
            selectinload(DfEngineUploadFiles.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineUploadFiles.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        ),
    )
    serialized = serialize(files)

    found_uids = {str(file["uid"]) for file in serialized}
    for idx, file_uid in enumerate(file_uids):
        if file_uid not in found_uids:
            raise DataNotFoundError(message="file_not_found", error={f"references.{idx}.upload": ["file_not_found"]})

    result = [UploadedFileRecord.from_result(file).model_dump(mode="json") for file in serialized]
    await set_json(ctx.redis, cache_key, result)
    return result
