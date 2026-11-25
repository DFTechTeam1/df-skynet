from typing import Any, Optional
from sqlalchemy.orm import load_only, selectinload
from services.mysql.model import DfEngineUploadFiles, Employees, ProjectSongLists, ProjectTasks, Users
from services.mysql.model.df_engine_upload_files import UploadFileTypes
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
        order_by: Optional[tuple[Any, ...]] = None,
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
            order_by,
        )

    async def get_picker_files(self, project_id: int, viewer_id: int, only_viewer: bool) -> list[dict[str, Any]]:
        return await self.get_uploaded_file(
            columns=(DfEngineUploadFiles,),
            filters=(
                DfEngineUploadFiles.project_id == project_id,  # type: ignore
                DfEngineUploadFiles.type == UploadFileTypes.image,  # type: ignore
                *((DfEngineUploadFiles.created_by == viewer_id,) if only_viewer else ()),  # type: ignore
            ),
            options=(
                load_only(
                    DfEngineUploadFiles.uid,  # type: ignore
                    DfEngineUploadFiles.name,  # type: ignore
                    DfEngineUploadFiles.type,  # type: ignore
                    DfEngineUploadFiles.path,  # type: ignore
                    DfEngineUploadFiles.size,  # type: ignore
                    DfEngineUploadFiles.created_at,  # type: ignore
                    DfEngineUploadFiles.updated_at,  # type: ignore
                    DfEngineUploadFiles.created_by,  # type: ignore
                    DfEngineUploadFiles.updated_by,  # type: ignore
                    DfEngineUploadFiles.task_id,  # type: ignore
                    DfEngineUploadFiles.song_id,  # type: ignore
                ),
                selectinload(DfEngineUploadFiles.task).load_only(ProjectTasks.uid, ProjectTasks.name),  # type: ignore
                selectinload(DfEngineUploadFiles.song).load_only(ProjectSongLists.uid, ProjectSongLists.name),  # type: ignore
                selectinload(DfEngineUploadFiles.created_by_user)  # type: ignore
                .load_only(Users.image)  # type: ignore
                .selectinload(Users.employees)  # type: ignore
                .load_only(Employees.nickname),  # type: ignore
                selectinload(DfEngineUploadFiles.updated_by_user)  # type: ignore
                .load_only(Users.image)  # type: ignore
                .selectinload(Users.employees)  # type: ignore
                .load_only(Employees.nickname),  # type: ignore
            ),
            order_by=(DfEngineUploadFiles.created_at.desc(),),  # type: ignore
            fetch_one=False,
            raise_if_null=False,
        )
