import traceback
from uuid import UUID
from typing import Optional
from sqlalchemy.orm import load_only, selectinload
from fastapi import Path, status, Query
from schemas.payload.elements import CreateElementPayload
from fastapi_controller import controller
from apps.controller.core import CoreDependencies
from log import logging
from middlewares.lang import resolve_message
from error import BaseError, DataNotFoundError, DataValidationError, ServiceError
from schemas.response import PaginationResponse, Response
from services.mysql.model import (
    DfEngineElements,
    Employees,
    EntertainmentTaskSongs,
    Projects,
    ProjectSongLists,
    ProjectTaskPics,
    ProjectTasks,
)
from services.repository.projects import ProjectRepository
from utils.serializer import serialize


class ElementsController(CoreDependencies):
    @controller.get(
        "/projects/{project_uid}/elements",
        summary="See all elements in a project",
        description="Shows the list of all elements (such as characters, objects, or backgrounds) that have been added to a project. Results are split into pages and can be searched by name.",
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
        search: Optional[str] = Query(None, description="Filter by element name (prefix match)."),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=50, ge=1, le=200, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        try:
            response.data = PaginationResponse(paginated=[], totalData=0)
        except BaseError as e:
            raise
        except Exception:
            raise ServiceError()
        return response

    @controller.post(
        "/tasks/{task_uid}/elements",
        summary="Add a new element to a task",
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
            production_task = serialize(
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
                    raise_if_null=False,
                )
            )

            entertainment_task = serialize(
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
                    raise_if_null=False,
                )
            )
            if not production_task and not entertainment_task:
                raise DataValidationError(message="project_task_not_found")

            task_source = "production" if production_task else "entertainment"
            project_task = production_task or entertainment_task
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
                types=schema.type,  # type: ignore
                description=schema.description,
                project_id=project_task["project_id"],
                task_id=project_task["id"] if task_source == "production" else None,
                song_id=project_task["id"] if task_source == "entertainment" else None,
                created_by=int(self.user["user_id"]),
            )
            self.db.add(element)
            await self.db.flush()
            response.data = {"uid": element.uid}
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
        summary="Upload a file to an element",
        description="Uploads an image or file from your device and adds it to the selected element.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_to_upload_an_element(
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

    @controller.patch(
        "/elements/{element_uid}/set-archieve",
        summary="Archive an element",
        description="Moves an element out of the active list when you no longer need it. Nothing is deleted, and its files are kept.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_to_set_element_archieve(
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

    @controller.get(
        "/elements/{element_uid}",
        summary="See element details",
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
            pass
        except BaseError as e:
            raise
        except Exception:
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
        description="Changes the information of an element, such as its name or description. Anything you leave out stays as it was.",
        status_code=status.HTTP_200_OK,
        tags=["Elements"],
        response_model=Response,
    )
    async def elements_with_element_uid_to_update_an_element(
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
