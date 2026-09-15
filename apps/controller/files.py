import time
import traceback
from typing import Any
from uuid import UUID
from fastapi import Path, Query, Request, status
from fastapi_controller import controller
from apps.controller.core import CoreDependencies
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL
from error import BaseError, ServiceError
from log import logging
from schemas.payload.files import (
    DeleteFilesPayload,
    DeleteFolderPayload,
    MoveFilesPayload,
    MoveFoldersPayload,
    NewFolderPayload,
    RenameFilePayload,
    RenameFolderPayload,
)
from schemas.response import Response
from services.api_caller import APICaller
from services.files import FilesService
from services.mysql.model import DfEngineExternalApiCalls
from services.mysql.model.df_engine_upload_files import DfEngineUploadFiles, UploadFileTypes


class FilesController(CoreDependencies):
    @controller.post(
        "/files/{task_uid}/uploads",
        summary="Uploads to Udin Storage.",
        description=(
            "Streams the multipart request body as-is to the storage engine's upload "
            "endpoint for the task `task_uid`. File validation (extension, size, count) "
            "is enforced by the storage engine itself. Returns every file uploaded so "
            "far for this task, each carrying the actions available to the current user "
            "(only the file's own uploader may rename/delete/move it)."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def upload_files(self, request: Request, task_uid: UUID = Path(..., description="Task UID.")) -> Response:
        response = Response()
        files_service = FilesService()
        logging.info(f"[upload-files] task_uid={task_uid} forwarding to udin")
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            project_uid = project_task["project"]["uid"]

            upload_path = f"/engine/storage/upload-files/{project_uid}"
            start = time.perf_counter()
            async with APICaller(
                base_url=UDIN_BASE_URL,
                headers={"X-API-Key": UDIN_API_KEY, "Content-Type": request.headers.get("content-type", "")},
            ) as caller:
                upstream = await caller.call(
                    "POST",
                    upload_path,
                    content=request.stream(),
                    raise_for_status=False,
                )

            try:
                body: dict[str, Any] = upstream.json() if upstream.content else {}
            except ValueError:
                body = {}

            try:
                name = await files_service.employee_nickname(self.db, int(self.user["user_id"]))
                self.db.add(
                    DfEngineExternalApiCalls(
                        name=name,
                        type="udin",
                        method="POST",
                        endpoint=str(upstream.request.url),
                        request_payload=None,  # streamed multipart body, not capturable verbatim
                        response_status_code=upstream.status_code,
                        response_headers=dict(upstream.headers),
                        response_body=body,
                        error_message="upload_failed" if upstream.status_code >= status.HTTP_400_BAD_REQUEST else None,
                        duration_ms=int((time.perf_counter() - start) * 1000),
                    )
                )
                await self.db.flush()
            except Exception:
                logging.error(
                    f"[upload-files] task_uid={task_uid} failed to write udin call log\n{traceback.format_exc()}"
                )

            if upstream.status_code >= status.HTTP_400_BAD_REQUEST:
                raise BaseError(
                    status_code=upstream.status_code,
                    message="upload_failed",
                    error=body.get("error"),
                )
            uploaded: list[dict[str, Any]] = body.get("data") or []
            if uploaded:
                for item in uploaded:
                    file_type = UploadFileTypes.video if "/videos/" in item["path"] else UploadFileTypes.image
                    self.db.add(
                        DfEngineUploadFiles(
                            name=item["name"],
                            type=file_type,
                            path=item["path"],
                            md5=item.get("md5"),
                            size=item["size"],
                            project_id=project_task["project_id"],
                            task_id=project_task["id"],
                            created_by=int(self.user["user_id"]),
                        )
                    )
                await self.db.flush()

            user_id = int(self.user["user_id"])

            response.data = await files_service.invalidate_and_refresh(self.db, self.redis, project_task, user_id)
            response.message = "Files successfully uploaded."
            logging.info(f"[upload-files] task_uid={task_uid} succeeded, status={upstream.status_code}")
        except BaseError as e:
            logging.warning(f"[upload-files] task_uid={task_uid} rejected ({e.status_code}): {e.message}")
            raise
        except Exception:
            logging.error(f"[upload-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}",
        summary="Get files.",
        description=(
            "Returns the same file tree as the upload endpoint, without uploading "
            "anything. Served from cache when available so a client only needs to "
            "hit the upload endpoint again after it actually uploads files."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def get_files(self, task_uid: UUID = Path(..., description="Task UID.")) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])

            response.data = await files_service.get_tree(self.db, self.redis, project_task, user_id)
            response.message = "Files successfully fetched."
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/detail",
        summary="Get a single folder's detail.",
        description=(
            "Returns one folder node (its own files and immediate child folders) from the "
            "file tree, by its exact `folder` path."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def get_folder_detail(
        self,
        task_uid: UUID = Path(..., description="Task UID."),
        folder_path: str = Query(..., description="Folder path, matching a `folder` value from the file tree."),
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])

            response.data = await files_service.get_folder_detail(
                self.db, self.redis, project_task, user_id, folder_path
            )
            response.message = "Folder detail successfully fetched."
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-folder-detail] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/file/{file_uid}",
        summary="Get a single file's detail.",
        description="Returns one file entry (by its `uid`) from the file tree.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def get_file_detail(
        self,
        task_uid: UUID = Path(..., description="Task UID."),
        file_uid: UUID = Path(..., description="File UID, matching a `uid` value from the file tree."),
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])

            response.data = await files_service.get_file_detail(
                self.db, self.redis, project_task, user_id, str(file_uid)
            )
            response.message = "File detail successfully fetched."
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-file-detail] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.post(
        "/files/{task_uid}/folder",
        summary="Create a subfolder.",
        description=(
            "Creates `name` under `current_path`. Rejects folders nested deeper than the "
            "admin-configured `folder_depth_limit` (see `/setting`) below a type root "
            "(`upload`/`generated` -> `images`/`videos`)."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def create_folder(
        self, schema: NewFolderPayload, task_uid: UUID = Path(..., description="Task UID.")
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])

            response.data = await files_service.create_folder(
                self.db, self.redis, project_task, user_id, schema.current_path, schema.name
            )
            response.message = "Folder successfully created."
        except BaseError:
            raise
        except Exception:
            logging.error(f"[create-folder] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.delete(
        "/files/{task_uid}/folder",
        summary="Delete a folder.",
        description="Non-destructive: nested files are promoted to the parent folder, then the empty folder tree is removed.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def delete_folder(
        self, schema: DeleteFolderPayload, task_uid: UUID = Path(..., description="Task UID.")
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])

            response.data = await files_service.delete_folder(
                self.db, self.redis, project_task, user_id, schema.folder_path
            )
            response.message = "Folder successfully deleted."
        except BaseError:
            raise
        except Exception:
            logging.error(f"[delete-folder] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.delete(
        "/files/{task_uid}/files",
        summary="Delete multiple files.",
        description="Deletes every listed file by `uid`, all-or-nothing. Generated files can never be targeted.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def delete_files(
        self, schema: DeleteFilesPayload, task_uid: UUID = Path(..., description="Task UID.")
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])

            response.data = await files_service.delete_files(
                self.db, self.redis, project_task, user_id, schema.file_uids
            )
            response.message = "Files successfully deleted."
        except BaseError:
            raise
        except Exception:
            logging.error(f"[delete-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/file",
        summary="Rename a file.",
        description="Renames one file by `uid`; the original extension is always preserved.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def rename_file(
        self, schema: RenameFilePayload, task_uid: UUID = Path(..., description="Task UID.")
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])

            response.data = await files_service.rename_file(
                self.db, self.redis, project_task, user_id, schema.file_uid, schema.name
            )
            response.message = "File successfully renamed."
        except BaseError:
            raise
        except Exception:
            logging.error(f"[rename-file] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/folder",
        summary="Rename a folder.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def rename_folder(
        self, schema: RenameFolderPayload, task_uid: UUID = Path(..., description="Task UID.")
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])

            response.data = await files_service.rename_folder(
                self.db, self.redis, project_task, user_id, schema.folder_path, schema.name
            )
            response.message = "Folder successfully renamed."
        except BaseError:
            raise
        except Exception:
            logging.error(f"[rename-folder] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/files/move",
        summary="Move multiple files.",
        description="Moves every listed file (by `uid`) into `destination`. Source and destination must share the same upload/generated family and images/videos type.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def move_files(
        self, schema: MoveFilesPayload, task_uid: UUID = Path(..., description="Task UID.")
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])

            response.data = await files_service.move_files(
                self.db, self.redis, project_task, user_id, schema.file_uids, schema.destination
            )
            response.message = "Files successfully moved."
        except BaseError:
            raise
        except Exception:
            logging.error(f"[move-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/folders/move",
        summary="Move multiple folders.",
        description="Moves every listed folder (by `uid`) into `destination`. Source and destination must share the same upload/generated family and images/videos type.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def move_folders(
        self, schema: MoveFoldersPayload, task_uid: UUID = Path(..., description="Task UID.")
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])

            response.data = await files_service.move_folders(
                self.db,
                self.redis,
                project_task,
                user_id,
                schema.folder_paths,
                schema.destination,
            )
            response.message = "Folders successfully moved."
        except BaseError:
            raise
        except Exception:
            logging.error(f"[move-folders] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response
