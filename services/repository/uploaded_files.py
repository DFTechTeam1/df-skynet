from typing import Any, Optional
from services.mysql.model import DfEngineUploadFiles
from services.repository.base import BaseRepository


class UploadedFileRepository(BaseRepository):
    async def get_uploaded_file(
        self,
        filters: Optional[tuple[Any, ...]] = None,
        columns: Optional[tuple[Any, ...]] = None,
        options: Optional[tuple[Any, ...]] = None,
        joins: Optional[tuple[Any, ...]] = None,
        raise_if_null: bool = True,
        context: Optional[dict[str, Any]] = None,
        fetch_one: bool = True,
        limit: Optional[int] = None,
        group_by: Optional[tuple[Any, ...]] = None,
        having: Optional[tuple[Any, ...]] = None,
    ) -> Any:
        return await self._get(
            DfEngineUploadFiles,
            (
                DfEngineUploadFiles.id,
                DfEngineUploadFiles.uid,
                DfEngineUploadFiles.path,
            ),
            "uploaded_file_not_found",
            filters,
            columns,
            options,
            joins,
            raise_if_null,
            context,
            fetch_one,
            limit,
            group_by,
            having,
        )
