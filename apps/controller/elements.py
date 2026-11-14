import traceback
from uuid import UUID
from pathlib import PurePosixPath
from typing import Any, Optional
from sqlalchemy import func
from sqlalchemy.orm import load_only, selectinload
from fastapi import Path, Request, status, Query
from httpx import TimeoutException
from enums.elements import ElementTypes
from schemas.format.elements import Element
from schemas.payload.elements import CreateElementPayload, RenameElementFilePayload
from fastapi_controller import controller
from apps.controller.core import CoreDependencies
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL
from log import logging
from middlewares.lang import current_lang, resolve_message
from error import AuthorizationError, BaseError, DataConflictError, DataNotFoundError, DataValidationError, ServiceError
from schemas.response import PaginationResponse, Response
from services.api_caller import APICaller
from services.files import call_udin_folder
from services.mysql import query
from services.repository.projects import ProjectRepository
from utils import local_time
from utils.formatter import format_udin_url
from utils.serializer import serialize
from services.mysql.model import (
    DfEngineElementGenerations,
    DfEngineElements,
    DfEngineElementUploads,
    DfEngineGenerationResults,
    Employees,
    EntertainmentTaskSongs,
    Projects,
    ProjectSongLists,
    ProjectTaskPics,
    ProjectTasks,
    Users,
)


class ElementsController(CoreDependencies):
    @controller.get(
        "/projects/{project_uid}/elements",
        summary="See all elements in a project",
        description="Shows the list of all elements that have been added to a project. Results are split into pages and can be searched by name.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_project_uid_to_get_list_elements(
        self,
        project_uid: UUID = Path(
            ...,
            description="Project UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
        search: Optional[str] = Query(None, description="Filter by element name (matches anywhere in the name)."),
        type: Optional[ElementTypes] = Query(
            None, description="Only return elements of this type. Leave empty to return every type."
        ),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=50, ge=1, le=200, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        try:
            project_id = await ProjectRepository(self.db).get_project(
                filters=(Projects.uid == str(project_uid),), columns=(Projects.id,)
            )
            filters = (DfEngineElements.project_id == project_id,)
            if search:
                filters += (DfEngineElements.name.contains(search, autoescape=True),)  # type: ignore
            if type:
                filters += (DfEngineElements.type == type,)  # type: ignore

            total = (
                await query(
                    self.db,
                    DfEngineElements,
                    columns=(func.count(DfEngineElements.id),),  # type: ignore
                    filters=filters,
                    fetch_one=True,
                )
                or 0
            )
            elements = await query(
                self.db,
                DfEngineElements,
                filters=filters,
                order_by=(DfEngineElements.id.desc(),),  # type: ignore
                options=(
                    selectinload(DfEngineElements.created_by_user)  # type: ignore
                    .load_only(Users.image)  # type: ignore
                    .selectinload(Users.employees)  # type: ignore
                    .load_only(Employees.nickname),  # type: ignore
                    selectinload(DfEngineElements.updated_by_user)  # type: ignore
                    .load_only(Users.image)  # type: ignore
                    .selectinload(Users.employees)  # type: ignore
                    .load_only(Employees.nickname),  # type: ignore
                    selectinload(DfEngineElements.source_upload)  # type: ignore
                    .load_only(
                        DfEngineElementUploads.uid,  # type: ignore
                        DfEngineElementUploads.name,  # type: ignore
                        DfEngineElementUploads.path,  # type: ignore
                        DfEngineElementUploads.size,  # type: ignore
                        DfEngineElementUploads.created_by,  # type: ignore
                        DfEngineElementUploads.updated_by,  # type: ignore
                    )
                    .options(
                        selectinload(DfEngineElementUploads.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineElementUploads.updated_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                    ),
                    selectinload(DfEngineElements.source_generation_result)  # type: ignore
                    .load_only(
                        DfEngineGenerationResults.uid,  # type: ignore
                        DfEngineGenerationResults.name,  # type: ignore
                        DfEngineGenerationResults.path,  # type: ignore
                        DfEngineGenerationResults.size,  # type: ignore
                        DfEngineGenerationResults.created_by,  # type: ignore
                        DfEngineGenerationResults.updated_by,  # type: ignore
                    )
                    .options(
                        selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                    ),
                    selectinload(DfEngineElements.uploads)  # type: ignore
                    .load_only(
                        DfEngineElementUploads.uid,  # type: ignore
                        DfEngineElementUploads.name,  # type: ignore
                        DfEngineElementUploads.path,  # type: ignore
                        DfEngineElementUploads.size,  # type: ignore
                        DfEngineElementUploads.created_by,  # type: ignore
                        DfEngineElementUploads.updated_by,  # type: ignore
                    )
                    .options(
                        selectinload(DfEngineElementUploads.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineElementUploads.updated_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                    ),
                ),
                limit=itemsPerPage,
                offset=(page - 1) * itemsPerPage,
            )
            paginated = []
            for element in serialize(elements):
                element["images"] = [
                    {**upload, "source": "uploaded"} for upload in element.get("uploads") or []
                ] or None
                if element.get("source_upload"):
                    element["main_image"] = {**element["source_upload"], "source": "uploaded"}
                elif element.get("source_generation_result"):
                    element["main_image"] = {**element["source_generation_result"], "source": "generated"}
                paginated.append(
                    Element.model_validate(
                        element, context={"user_id": self.user["user_id"], "is_overrider": self.user["is_overrider"]}
                    ).model_dump()
                )
            response.data = PaginationResponse(paginated=paginated, totalData=total)
            response.message = resolve_message("elements_fetched", current_lang.get())
            logging.info(
                f"[get-project-elements] user={self.user['user_id']} project_uid={project_uid} search={search!r} type={type} page={page} items_per_page={itemsPerPage} returned={len(paginated)} total={total}"
            )
        except BaseError as e:
            reason = resolve_message(e.message)
            if e.context:
                reason = reason.format(**e.context)
            logging.warning(
                f"[get-project-elements] user={self.user['user_id']} project_uid={project_uid} rejected: {reason} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"[get-project-elements] user={self.user['user_id']} project_uid={project_uid} unexpected error\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.get(
        "/tasks/{task_uid}/elements",
        summary="Get task elements",
        description="Shows all elements that belong to a task, such as characters, objects, environments, or styles, together with their details.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_task_uid_to_fetch_element_gallery(
        self,
        search: Optional[str] = Query(None, description="Filter by element name (matches anywhere in the name)."),
        type: Optional[ElementTypes] = Query(
            None, description="Only return elements of this type. Leave empty to return every type."
        ),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=50, ge=1, le=200, description="Number of records to return per page."),
        task_uid: UUID = Path(
            ...,
            description="Task UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ):
        response = Response()
        project_repo = ProjectRepository(self.db)
        try:
            project_task = await project_repo.get_task(str(task_uid))
            column = DfEngineElements.task_id if project_task["type"] == "production" else DfEngineElements.song_id
            filters = (column == project_task["id"],)
            if search:
                filters += (DfEngineElements.name.contains(search, autoescape=True),)  # type: ignore
            if type:
                filters += (DfEngineElements.type == type,)  # type: ignore
            total = (
                await query(
                    self.db,
                    DfEngineElements,
                    columns=(func.count(DfEngineElements.id),),  # type: ignore
                    filters=filters,
                    fetch_one=True,
                )
                or 0
            )
            elements = await query(
                self.db,
                DfEngineElements,
                filters=filters,
                order_by=(DfEngineElements.id.desc(),),  # type: ignore
                options=(
                    selectinload(DfEngineElements.created_by_user)  # type: ignore
                    .load_only(Users.image)  # type: ignore
                    .selectinload(Users.employees)  # type: ignore
                    .load_only(Employees.nickname),  # type: ignore
                    selectinload(DfEngineElements.updated_by_user)  # type: ignore
                    .load_only(Users.image)  # type: ignore
                    .selectinload(Users.employees)  # type: ignore
                    .load_only(Employees.nickname),  # type: ignore
                    selectinload(DfEngineElements.source_upload)  # type: ignore
                    .load_only(
                        DfEngineElementUploads.uid,  # type: ignore
                        DfEngineElementUploads.name,  # type: ignore
                        DfEngineElementUploads.path,  # type: ignore
                        DfEngineElementUploads.size,  # type: ignore
                        DfEngineElementUploads.created_by,  # type: ignore
                        DfEngineElementUploads.updated_by,  # type: ignore
                    )
                    .options(
                        selectinload(DfEngineElementUploads.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineElementUploads.updated_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                    ),
                    selectinload(DfEngineElements.source_generation_result)  # type: ignore
                    .load_only(
                        DfEngineGenerationResults.uid,  # type: ignore
                        DfEngineGenerationResults.name,  # type: ignore
                        DfEngineGenerationResults.path,  # type: ignore
                        DfEngineGenerationResults.size,  # type: ignore
                        DfEngineGenerationResults.created_by,  # type: ignore
                        DfEngineGenerationResults.updated_by,  # type: ignore
                    )
                    .options(
                        selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                    ),
                    selectinload(DfEngineElements.uploads)  # type: ignore
                    .load_only(
                        DfEngineElementUploads.uid,  # type: ignore
                        DfEngineElementUploads.name,  # type: ignore
                        DfEngineElementUploads.path,  # type: ignore
                        DfEngineElementUploads.size,  # type: ignore
                        DfEngineElementUploads.created_by,  # type: ignore
                        DfEngineElementUploads.updated_by,  # type: ignore
                    )
                    .options(
                        selectinload(DfEngineElementUploads.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineElementUploads.updated_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                    ),
                ),
                limit=itemsPerPage,
                offset=(page - 1) * itemsPerPage,
            )
            paginated = []
            for element in serialize(elements):
                element["images"] = [
                    {**upload, "source": "uploaded"} for upload in element.get("uploads") or []
                ] or None
                if element.get("source_upload"):
                    element["main_image"] = {**element["source_upload"], "source": "uploaded"}
                elif element.get("source_generation_result"):
                    element["main_image"] = {**element["source_generation_result"], "source": "generated"}
                paginated.append(
                    Element.model_validate(
                        element, context={"user_id": self.user["user_id"], "is_overrider": self.user["is_overrider"]}
                    ).model_dump()
                )
            response.data = PaginationResponse(paginated=paginated, totalData=total)
            response.message = resolve_message("elements_fetched", current_lang.get())
            logging.info(
                f"[get-task-elements] user={self.user['user_id']} task_uid={task_uid} source={project_task['type']} search={search!r} type={type} page={page} items_per_page={itemsPerPage} returned={len(paginated)} total={total}"
            )
        except BaseError as e:
            reason = resolve_message(e.message)
            if e.context:
                reason = reason.format(**e.context)
            logging.warning(
                f"[get-task-elements] user={self.user['user_id']} task_uid={task_uid} rejected: {reason} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"[get-task-elements] user={self.user['user_id']} task_uid={task_uid} unexpected error\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.post(
        "/tasks/{task_uid}/elements",
        summary="Create element to task",
        description="Adds a new, empty element to a task. You can upload images or other files to it afterwards.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_project_uid_and_task_uid_to_create_element(
        self,
        schema: CreateElementPayload,
        task_uid: UUID = Path(
            ...,
            description="Task UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        project_repo = ProjectRepository(self.db)

        PROJECT_STATUS_ONGOING = 1
        ENTERTAINMENT_TASK_STATUS_COMPLETED = 6
        PRODUCTION_TASK_STATUS_COMPLETED = 4

        try:
            task_source = (await project_repo.get_task(str(task_uid)))["type"]
            if task_source == "production":
                project_task = serialize(
                    await project_repo.get_production_task(
                        filters=(ProjectTasks.uid == str(task_uid),),
                        columns=(ProjectTasks,),
                        options=(
                            load_only(ProjectTasks.id, ProjectTasks.project_id, ProjectTasks.name, ProjectTasks.status),  # type: ignore
                            selectinload(ProjectTasks.project).load_only(Projects.status),  # type: ignore
                            selectinload(ProjectTasks.project_task_pics)  # type: ignore
                            .load_only(ProjectTaskPics.employee_id)  # type: ignore
                            .selectinload(ProjectTaskPics.employees)  # type: ignore
                            .load_only(Employees.user_id),  # type: ignore
                        ),
                    )
                )
            else:
                project_task = serialize(
                    await project_repo.get_entertainment_task(
                        filters=(ProjectSongLists.uid == str(task_uid),),
                        columns=(ProjectSongLists,),
                        options=(
                            load_only(ProjectSongLists.id, ProjectSongLists.project_id, ProjectSongLists.name),  # type: ignore
                            selectinload(ProjectSongLists.task_songs)  # type: ignore
                            .load_only(EntertainmentTaskSongs.status, EntertainmentTaskSongs.employee_id)  # type: ignore
                            .selectinload(EntertainmentTaskSongs.employees)  # type: ignore
                            .load_only(Employees.user_id),  # type: ignore
                            selectinload(ProjectSongLists.project).load_only(Projects.status),  # type: ignore
                        ),
                    )
                )

            project = project_task.get("project")
            if not project:
                raise DataValidationError(message="project_not_found")

            if project["status"] != PROJECT_STATUS_ONGOING:
                raise DataValidationError(message="project_not_ongoing")

            if task_source == "production":
                if project_task["status"] == PRODUCTION_TASK_STATUS_COMPLETED:
                    raise DataValidationError(
                        message="production_task_already_completed",
                        context={"name": project_task["name"]},
                    )
            else:
                songs = project_task["task_songs"]
                if not songs:
                    raise DataValidationError(
                        message="project_song_has_no_entertainment_task_songs",
                        context={"name": project_task["name"]},
                    )
                if all(song["status"] == ENTERTAINMENT_TASK_STATUS_COMPLETED for song in songs):
                    raise DataValidationError(
                        message="entertainment_task_already_completed",
                        context={"name": project_task["name"]},
                    )

            if not self.user["is_overrider"]:
                if task_source == "production":
                    assignments = project_task["project_task_pics"]
                else:
                    assignments = project_task["task_songs"]

                is_assigned = False
                for assignment in assignments:
                    employee = assignment["employees"]
                    if employee and int(employee["user_id"]) == int(self.user["user_id"]):
                        is_assigned = True
                        break

                if not is_assigned:
                    raise DataNotFoundError(message="employee_not_assigned_task")

            element = DfEngineElements(
                name=schema.name,
                type=schema.type,  # type: ignore
                description=schema.description,
                project_id=project_task["project_id"],
                task_id=project_task["id"] if task_source == "production" else None,
                song_id=project_task["id"] if task_source == "entertainment" else None,
                created_by=int(self.user["user_id"]),
            )
            self.db.add(element)
            await self.db.flush()
            response.message = resolve_message("element_created", current_lang.get())
            logging.info(
                f"[create-element] user={self.user['user_id']} task_uid={task_uid} source={task_source} element_uid={element.uid} created"
            )
        except BaseError as e:
            reason = resolve_message(e.message)
            if e.context:
                reason = reason.format(**e.context)
            logging.warning(
                f"[create-element] user={self.user['user_id']} task_uid={task_uid} rejected: {reason} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"[create-element] user={self.user['user_id']} task_uid={task_uid} unexpected error\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.post(
        "/elements/{element_uid}/upload",
        summary="Upload an images to an element",
        description="Uploads one or more images (JPG, JPEG or PNG) from your device and adds them to the selected element. Send them as multipart form-data. Only the creator or an overrider can upload.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_to_upload_an_element(
        self,
        request: Request,
        element_uid: UUID = Path(
            ...,
            description="Element UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])

        ELEMENT_UPLOAD_MIME_TYPES = {"image/jpeg", "image/png"}
        ELEMENT_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png"}
        try:
            element = await query(
                db=self.db,
                table=DfEngineElements,
                options=(
                    load_only(
                        DfEngineElements.id,  # type: ignore
                        DfEngineElements.project_id,  # type: ignore
                        DfEngineElements.task_id,  # type: ignore
                        DfEngineElements.song_id,  # type: ignore
                        DfEngineElements.created_by,  # type: ignore
                        DfEngineElements.sourceable_id,  # type: ignore
                        DfEngineElements.sourceable_type,  # type: ignore
                    ),
                    selectinload(DfEngineElements.project).load_only(Projects.uid, Projects.name),  # type: ignore
                ),
                filters=(DfEngineElements.uid == str(element_uid),),
                fetch_one=True,
            )
            if not element:
                raise DataNotFoundError(message="element_not_found")

            if not self.user["is_overrider"] and element.created_by != user_id:
                raise AuthorizationError(message="element_action_not_permitted")

            project = element.project
            if not project:
                raise DataValidationError(message="project_not_found")

            form = await request.form()
            files = [(key, value) for key, value in form.multi_items() if not isinstance(value, str)]
            if not files:
                raise DataValidationError(
                    message="element_upload_no_files", error={"files": ["element_upload_no_files"]}
                )
            for key, file in files:
                extension = PurePosixPath(file.filename or "").suffix.lower()
                if file.content_type not in ELEMENT_UPLOAD_MIME_TYPES or extension not in ELEMENT_UPLOAD_EXTENSIONS:
                    raise DataValidationError(
                        message="element_upload_image_only", error={key: ["element_upload_image_only"]}
                    )

            try:
                async with APICaller(
                    base_url=UDIN_BASE_URL,
                    headers={"X-API-Key": UDIN_API_KEY},
                    timeout=10,
                ) as caller:
                    upstream = await caller.udin(
                        "POST",
                        f"/engine/storage/upload-files/{project.uid}",
                        user_id=user_id,
                        params={"project_name": project.name},
                        files=[(key, (file.filename, file.file, file.content_type)) for key, file in files],
                    )
            except TimeoutException:
                logging.error(f"[upload-element] user={user_id} element_uid={element_uid} udin timed out")
                raise BaseError(status_code=status.HTTP_504_GATEWAY_TIMEOUT, message="element_upload_timeout")

            try:
                body: dict[str, Any] = upstream.json() if upstream.content else {}
            except ValueError:
                body = {}
            if upstream.is_error:
                logging.warning(
                    f"[upload-element] user={user_id} element_uid={element_uid} udin rejected "
                    f"status={upstream.status_code} error={body.get('error')}"
                )
                raise BaseError(status_code=upstream.status_code, message="upload_failed", error=body.get("error"))

            rows = [
                DfEngineElementUploads(
                    name=item["name"],
                    path=item["path"],
                    md5=item.get("md5"),
                    size=item["size"],
                    project_id=element.project_id,
                    element_id=element.id,
                    created_by=user_id,
                )
                for item in body.get("data") or []
            ]
            self.db.add_all(rows)
            element.updated_by = user_id
            await self.db.flush()

            if rows and element.sourceable_id is None:
                element.sourceable_type = DfEngineElementUploads.__name__
                element.sourceable_id = rows[0].id
                await self.db.flush()

            response.message = resolve_message("element_uploaded", current_lang.get())
            logging.info(f"[upload-element] user={user_id} element_uid={element_uid} uploaded={len(rows)}")
        except BaseError as e:
            reason = resolve_message(e.message)
            if e.context:
                reason = reason.format(**e.context)
            logging.warning(
                f"[upload-element] user={user_id} element_uid={element_uid} rejected: {reason} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"[upload-element] user={user_id} element_uid={element_uid} unexpected error\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.patch(
        "/elements/files/rename/{file_uid}",
        summary="Rename an element's file",
        description="Changes the name of an image uploaded to an element. A typed extension is ignored: the file's real extension is always kept. Letters, numbers, spaces and _ - . # ( ) @ & only. Only the creator of the file can do this.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_file_uid_to_rename_an_element_file(
        self,
        schema: RenameElementFilePayload,
        file_uid: UUID = Path(
            ...,
            description="Element file UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        try:
            file = await query(
                db=self.db,
                table=DfEngineElementUploads,
                filters=(DfEngineElementUploads.uid == str(file_uid),),
                options=(selectinload(DfEngineElementUploads.project).load_only(Projects.uid, Projects.name),),  # type: ignore
                fetch_one=True,
            )
            if not file:
                raise DataNotFoundError(message="element_file_not_found")

            if file.created_by != user_id:
                raise AuthorizationError(message="element_file_not_creator")

            project = file.project
            if not project:
                raise DataValidationError(message="project_not_found")

            new_name = schema.name + PurePosixPath(file.path).suffix

            if new_name != file.name:
                pairs = await call_udin_folder(
                    "PATCH",
                    "rename-file",
                    project.uid,
                    project.name,
                    user_id,
                    {"filepath": file.path, "name": new_name},
                    "file_rename_failed",
                    "rename-element-file",
                )
                renamed = next((pair["to"] for pair in pairs or [] if pair["from"]["path"] == file.path), None)
                if renamed is None:
                    raise ServiceError(message="file_rename_failed")
                file.path, file.name = renamed["path"], renamed["name"]
                file.updated_by, file.updated_at = user_id, local_time()
                await self.db.flush()

            response.message = resolve_message("element_file_renamed", current_lang.get())
            logging.info(f"[rename-element-file] user={user_id} file_uid={file_uid} name={file.name!r}")
        except BaseError as e:
            reason = resolve_message(e.message)
            if e.context:
                reason = reason.format(**e.context)
            logging.warning(
                f"[rename-element-file] user={user_id} file_uid={file_uid} rejected: {reason} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"[rename-element-file] user={user_id} file_uid={file_uid} unexpected error\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.patch(
        "/elements/{element_uid}/set-main/{file_uid}",
        summary="Choose the main file of an element",
        description="Picks which file is shown as the main one for this element. The file chosen before will no longer be the main one.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_and_file_uid_to_set_element_main(
        self,
        element_uid: UUID = Path(
            ...,
            description="Element UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
        file_uid: UUID = Path(
            ...,
            description="Element file UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            pass
        except BaseError as e:
            raise
        except Exception:
            raise ServiceError()
        return response

    @controller.patch(
        "/elements/{element_uid}/set-edit-main/{file_uid}",
        summary="Choose the main edited version of an element",
        description="Picks which edited version is used as the final result for this element. The edited version chosen before will no longer be the main one.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_and_file_uid_to_set_edit_element_main(
        self,
        element_uid: UUID = Path(
            ...,
            description="Element UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
        file_uid: UUID = Path(
            ...,
            description="Element file UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            pass
        except BaseError as e:
            raise
        except Exception:
            raise ServiceError()
        return response

    @controller.get(
        "/elements/{element_uid}",
        summary="Get element details",
        description="Shows everything about one element, including its information and all files added to it.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_to_get_an_element_detail(
        self,
        element_uid: UUID = Path(
            ...,
            description="Element UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            element = serialize(
                await query(
                    db=self.db,
                    table=DfEngineElements,
                    filters=(DfEngineElements.uid == str(element_uid),),
                    options=(
                        selectinload(DfEngineElements.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineElements.updated_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineElements.generations),  # type: ignore
                        selectinload(DfEngineElements.source_upload)  # type: ignore
                        .load_only(
                            DfEngineElementUploads.uid,  # type: ignore
                            DfEngineElementUploads.name,  # type: ignore
                            DfEngineElementUploads.path,  # type: ignore
                            DfEngineElementUploads.size,  # type: ignore
                            DfEngineElementUploads.created_by,  # type: ignore
                            DfEngineElementUploads.updated_by,  # type: ignore
                        )
                        .options(
                            selectinload(DfEngineElementUploads.created_by_user)  # type: ignore
                            .load_only(Users.image)  # type: ignore
                            .selectinload(Users.employees)  # type: ignore
                            .load_only(Employees.nickname),  # type: ignore
                            selectinload(DfEngineElementUploads.updated_by_user)  # type: ignore
                            .load_only(Users.image)  # type: ignore
                            .selectinload(Users.employees)  # type: ignore
                            .load_only(Employees.nickname),  # type: ignore
                        ),
                        selectinload(DfEngineElements.source_generation_result)  # type: ignore
                        .load_only(
                            DfEngineGenerationResults.uid,  # type: ignore
                            DfEngineGenerationResults.name,  # type: ignore
                            DfEngineGenerationResults.path,  # type: ignore
                            DfEngineGenerationResults.size,  # type: ignore
                            DfEngineGenerationResults.created_by,  # type: ignore
                            DfEngineGenerationResults.updated_by,  # type: ignore
                        )
                        .options(
                            selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
                            .load_only(Users.image)  # type: ignore
                            .selectinload(Users.employees)  # type: ignore
                            .load_only(Employees.nickname),  # type: ignore
                            selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
                            .load_only(Users.image)  # type: ignore
                            .selectinload(Users.employees)  # type: ignore
                            .load_only(Employees.nickname),  # type: ignore
                        ),
                        selectinload(DfEngineElements.uploads)  # type: ignore
                        .load_only(
                            DfEngineElementUploads.uid,  # type: ignore
                            DfEngineElementUploads.name,  # type: ignore
                            DfEngineElementUploads.path,  # type: ignore
                            DfEngineElementUploads.size,  # type: ignore
                            DfEngineElementUploads.created_by,  # type: ignore
                            DfEngineElementUploads.updated_by,  # type: ignore
                        )
                        .options(
                            selectinload(DfEngineElementUploads.created_by_user)  # type: ignore
                            .load_only(Users.image)  # type: ignore
                            .selectinload(Users.employees)  # type: ignore
                            .load_only(Employees.nickname),  # type: ignore
                            selectinload(DfEngineElementUploads.updated_by_user)  # type: ignore
                            .load_only(Users.image)  # type: ignore
                            .selectinload(Users.employees)  # type: ignore
                            .load_only(Employees.nickname),  # type: ignore
                        ),
                    ),
                    fetch_one=True,
                )
            )
            if not element:
                raise DataNotFoundError(message="element_not_found")

            element["images"] = [{**upload, "source": "uploaded"} for upload in element.get("uploads") or []] or None
            if element.get("source_upload"):
                element["main_image"] = {**element["source_upload"], "source": "uploaded"}
            if element.get("source_generation_result"):
                element["main_image"] = {**element["source_generation_result"], "source": "generated"}
            response.data = Element.model_validate(
                element, context={"user_id": self.user["user_id"], "is_overrider": self.user["is_overrider"]}
            ).model_dump()
            response.message = resolve_message("element_fetched", current_lang.get())
            logging.info(f"[get-element-detail] user={self.user['user_id']} element_uid={element_uid} fetched")
        except BaseError as e:
            reason = resolve_message(e.message)
            if e.context:
                reason = reason.format(**e.context)
            logging.warning(
                f"[get-element-detail] user={self.user['user_id']} element_uid={element_uid} rejected: {reason} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"[get-element-detail] user={self.user['user_id']} element_uid={element_uid} unexpected error\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.get(
        "/elements/files/{file_uid}",
        summary="See file details of an element",
        description="Shows the details of one file that belongs to an element, such as the image itself and its information.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_file_uid_to_get_an_element_file_detail(
        self,
        file_uid: UUID = Path(
            ...,
            description="Element file UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            pass
        except BaseError as e:
            raise
        except Exception:
            raise ServiceError()
        return response

    @controller.post(
        "/elements/{element_uid}/edit/{file_uid}",
        summary="Edit an element's image with AI",
        description="Uses AI to change an existing image of the element based on your instructions. The new result is saved as an edited version, and the original stays untouched.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_and_file_uid_to_edit_an_element_generation(
        self,
        element_uid: UUID = Path(
            ...,
            description="Element UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
        file_uid: UUID = Path(
            ...,
            description="Element file UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            pass
        except BaseError as e:
            raise
        except Exception:
            raise ServiceError()
        return response

    @controller.post(
        "/elements/{element_uid}/generate",
        summary="Create an element's image with AI",
        description="Uses AI to create a new image for the element based on your description. The result is saved in the element so you can review it.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_to_create_an_element_generation(
        self,
        element_uid: UUID = Path(
            ...,
            description="Element UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            pass
        except BaseError as e:
            raise
        except Exception:
            raise ServiceError()
        return response

    @controller.patch(
        "/elements/{element_uid}",
        summary="Update an element",
        description="Changes the name, type or description of an element. Send the same fields as when creating one; the description can be left out and stays as it was.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_to_update_an_element(
        self,
        schema: CreateElementPayload,
        element_uid: UUID = Path(
            ...,
            description="Element UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            element = await query(
                db=self.db,
                options=(load_only(DfEngineElements.id, DfEngineElements.uid, DfEngineElements.created_by),),  # type: ignore
                table=DfEngineElements,
                filters=(DfEngineElements.uid == str(element_uid),),
                fetch_one=True,
            )
            if not element:
                raise DataNotFoundError(message="element_not_found")

            if not self.user["is_overrider"] and element.created_by != int(self.user["user_id"]):
                raise AuthorizationError(message="element_action_not_permitted")

            changes = schema.model_dump(exclude_unset=True)
            for field, value in changes.items():
                setattr(element, field, value)
            element.updated_by = int(self.user["user_id"])
            await self.db.flush()

            response.message = resolve_message("element_updated", current_lang.get())
            logging.info(
                f"[update-element] user={self.user['user_id']} element_uid={element_uid} updated fields={list(changes)}"
            )
        except BaseError as e:
            reason = resolve_message(e.message)
            if e.context:
                reason = reason.format(**e.context)
            logging.warning(
                f"[update-element] user={self.user['user_id']} element_uid={element_uid} rejected: {reason} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"[update-element] user={self.user['user_id']} element_uid={element_uid} unexpected error\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.delete(
        "/elements/{element_uid}",
        summary="Delete an element",
        description="Permanently deletes an element and every file uploaded to it, including the files stored in Udin. This cannot be undone. Only the creator or an overrider can delete it, and an element that already has generations cannot be deleted.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_to_delete_an_element(
        self,
        element_uid: UUID = Path(
            ...,
            description="Element UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            element = await query(
                db=self.db,
                table=DfEngineElements,
                filters=(DfEngineElements.uid == str(element_uid),),
                options=(
                    load_only(
                        DfEngineElements.id,  # type: ignore
                        DfEngineElements.project_id,  # type: ignore
                        DfEngineElements.created_by,  # type: ignore
                    ),
                    selectinload(DfEngineElements.generations).load_only(DfEngineElementGenerations.id),  # type: ignore
                    selectinload(DfEngineElements.uploads).load_only(DfEngineElementUploads.path),  # type: ignore
                    selectinload(DfEngineElements.project).load_only(Projects.uid, Projects.name),  # type: ignore
                ),
                fetch_one=True,
            )
            if not element:
                raise DataNotFoundError(message="element_not_found")

            if not self.user["is_overrider"] and element.created_by != int(self.user["user_id"]):
                raise AuthorizationError(message="element_action_not_permitted")

            if element.generations:
                raise DataConflictError(message="element_has_generations")

            uploads = element.uploads
            if uploads:
                """Files live in Udin, so remove them there first; the element is only deleted once Udin has agreed."""
                await call_udin_folder(
                    "DELETE",
                    "delete-files",
                    element.project.uid,
                    element.project.name,
                    int(self.user["user_id"]),
                    {"sources": [upload.path for upload in uploads]},
                    "files_delete_failed",
                    "delete-element-files",
                )
                for upload in uploads:
                    await self.db.delete(upload)

            await self.db.delete(element)
            await self.db.flush()

            response.message = resolve_message("element_deleted", current_lang.get())
            logging.info(f"[delete-element] user={self.user['user_id']} element_uid={element_uid} deleted")
        except BaseError as e:
            reason = resolve_message(e.message)
            if e.context:
                reason = reason.format(**e.context)
            logging.warning(
                f"[delete-element] user={self.user['user_id']} element_uid={element_uid} rejected: {reason} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"[delete-element] user={self.user['user_id']} element_uid={element_uid} unexpected error\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response
