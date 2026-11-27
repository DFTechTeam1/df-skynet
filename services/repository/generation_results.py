from typing import Any, Optional
from sqlalchemy import and_
from sqlalchemy.orm import load_only, selectinload
from services.mysql.model import (
    DfEngineGenerationFavourites,
    DfEngineGenerationResults,
    DfEngineGenerations,
    DfEngineModelOptions,
    Employees,
    ProjectSongLists,
    ProjectTasks,
    Users,
)
from services.mysql.model.df_engine_generations import GenerationKinds, GenerationStatuses
from services.repository.base import BaseRepository


class GenerationResultRepository(BaseRepository):
    async def get_generation_file(
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
            DfEngineGenerationResults,
            (
                DfEngineGenerationResults.id,
                DfEngineGenerationResults.uid,
                DfEngineGenerationResults.path,
            ),
            "generation_result_not_found",
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
        return await self.get_generation_file(
            columns=(DfEngineGenerationResults,),
            filters=(
                DfEngineGenerationResults.is_main.is_(True),  # type: ignore
                DfEngineGenerationResults.generation.has(  # type: ignore
                    and_(
                        DfEngineGenerations.project_id == project_id,  # type: ignore
                        DfEngineGenerations.status == GenerationStatuses.success,  # type: ignore
                        DfEngineGenerations.kind.in_(  # type: ignore
                            [GenerationKinds.image, GenerationKinds.image_edit, GenerationKinds.video]
                        ),
                        *((DfEngineGenerations.created_by == viewer_id,) if only_viewer else ()),  # type: ignore
                    )
                ),
            ),
            options=(
                load_only(
                    DfEngineGenerationResults.uid,  # type: ignore
                    DfEngineGenerationResults.name,  # type: ignore
                    DfEngineGenerationResults.path,  # type: ignore
                    DfEngineGenerationResults.size,  # type: ignore
                    DfEngineGenerationResults.thumbnail,  # type: ignore
                    DfEngineGenerationResults.created_at,  # type: ignore
                    DfEngineGenerationResults.updated_at,  # type: ignore
                    DfEngineGenerationResults.archieved_at,  # type: ignore
                    DfEngineGenerationResults.is_main,  # type: ignore
                    DfEngineGenerationResults.created_by,  # type: ignore
                    DfEngineGenerationResults.updated_by,  # type: ignore
                    DfEngineGenerationResults.generation_id,  # type: ignore
                ),
                selectinload(DfEngineGenerationResults.generation).options(  # type: ignore
                    load_only(
                        DfEngineGenerations.uid,  # type: ignore
                        DfEngineGenerations.kind,  # type: ignore
                        DfEngineGenerations.model_id,  # type: ignore
                        DfEngineGenerations.task_id,  # type: ignore
                        DfEngineGenerations.song_id,  # type: ignore
                    ),
                    selectinload(DfEngineGenerations.model_option).load_only(DfEngineModelOptions.name),  # type: ignore
                    selectinload(DfEngineGenerations.task).load_only(ProjectTasks.uid, ProjectTasks.name),  # type: ignore
                    selectinload(DfEngineGenerations.song).load_only(ProjectSongLists.uid, ProjectSongLists.name),  # type: ignore
                ),
                selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
                .load_only(Users.image)  # type: ignore
                .selectinload(Users.employees)  # type: ignore
                .load_only(Employees.nickname),  # type: ignore
                selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
                .load_only(Users.image)  # type: ignore
                .selectinload(Users.employees)  # type: ignore
                .load_only(Employees.nickname),  # type: ignore
                selectinload(
                    DfEngineGenerationResults.favourites.and_(DfEngineGenerationFavourites.user_id == viewer_id)  # type: ignore
                ).load_only(DfEngineGenerationFavourites.favourited_at),  # type: ignore
            ),
            order_by=(DfEngineGenerationResults.created_at.desc(),),  # type: ignore
            fetch_one=False,
            raise_if_null=False,
        )
