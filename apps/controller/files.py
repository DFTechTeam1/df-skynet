import time
import traceback
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID
from fastapi import Path, Query, Request, status
from fastapi.responses import StreamingResponse
from fastapi_controller import controller
from apps.controller.core import CoreDependencies
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL
from error import BaseError, ServiceError
from log import logging
from middlewares.lang import current_lang, resolve_message
from schemas.payload.files import (
    DeleteFilesPayload,
    DeleteFolderPayload,
    MoveFilesPayload,
    MoveFoldersPayload,
    NewFolderPayload,
    RenameFilePayload,
    RenameFolderPayload,
    SetArchivedPayload,
    SetFavoritedPayload,
)
from schemas.response import Response
from services.api_caller import APICaller
from services.files import FileCtx, FilesService
from services.mysql.model import DfEngineExternalApiCalls
from services.mysql.model.df_engine_upload_files import DfEngineUploadFiles, UploadFileTypes


class FilesController(CoreDependencies):
    @controller.post(
        "/files/{task_uid}/uploads",
        summary="Upload files.",
        description="Uploads one or more files to this task and returns the full, updated file list.",
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.invalidate_and_refresh(ctx)
            response.message = resolve_message("files_uploaded", current_lang.get())
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
        summary="View files.",
        description="Shows all files and folders for this task.",
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.get_tree(ctx)
            response.message = resolve_message("files_fetched", current_lang.get())
            logging.info(f"[get-files] user={user_id} task_uid={task_uid} fetched")
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/detail",
        summary="View a folder.",
        description="Shows the files and subfolders inside one specific folder.",
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.get_folder_detail(ctx, folder_path)
            response.message = resolve_message("folder_detail_fetched", current_lang.get())
            logging.info(f"[get-folder-detail] user={user_id} task_uid={task_uid} folder_path={folder_path}")
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-folder-detail] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/file/{file_uid}",
        summary="View a file.",
        description="Shows the details of one specific file, whether it was uploaded or generated.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def get_file_detail(
        self,
        task_uid: UUID = Path(..., description="Task UID."),
        file_uid: UUID = Path(..., description="File UID, matching a `uid` value from the file tree."),
        type: Literal["upload", "generated"] = Query("upload", description="`upload` or `generated`."),
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.get_file_detail(ctx, str(file_uid), kind=type)
            response.message = resolve_message("file_detail_fetched", current_lang.get())
            logging.info(f"[get-file-detail] user={user_id} task_uid={task_uid} file_uid={file_uid} type={type}")
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-file-detail] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/archieved",
        summary="View archived files.",
        description="Shows files that have been archived (hidden from the main view). Optionally filter by image or video.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def get_archived_files(
        self,
        task_uid: UUID = Path(..., description="Task UID."),
        type: Literal["image", "video"] | None = Query(None, description="Filter by file type. Omit for all."),
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.get_archived_files(ctx, file_type=type)
            response.message = resolve_message("archived_files_fetched", current_lang.get())
            logging.info(f"[get-archived-files] user={user_id} task_uid={task_uid} type={type}")
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-archived-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/favourited",
        summary="View favorited files.",
        description="Shows files you've marked as favorites. Optionally filter by image or video.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def get_favourited_files(
        self,
        task_uid: UUID = Path(..., description="Task UID."),
        type: Literal["image", "video"] | None = Query(None, description="Filter by file type. Omit for all."),
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.get_favourited_files(ctx, file_type=type)
            response.message = resolve_message("favourited_files_fetched", current_lang.get())
            logging.info(f"[get-favourited-files] user={user_id} task_uid={task_uid} type={type}")
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-favourited-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/archieve",
        summary="Archive or unarchive files.",
        description="Hides the selected files from the main view, or brings them back.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def archive_file(
        self, schema: SetArchivedPayload, task_uid: UUID = Path(..., description="Task UID.")
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.set_archived_generation(
                ctx, [str(uid) for uid in schema.file_uids], schema.is_archieved
            )
            key = "files_archived" if schema.is_archieved else "files_unarchived"
            response.message = resolve_message(key, current_lang.get())
            logging.info(
                f"[archive-file] user={user_id} task_uid={task_uid} "
                f"file_uids={schema.file_uids} is_archieved={schema.is_archieved}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[archive-file] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/download/{source}/{file_uid}",
        summary="Download a file.",
        description="Downloads one of your files to your device.",
        tags=["Files"],
    )
    async def files_with_uid_to_download_source_file(
        self,
        task_uid: UUID = Path(..., description="Task UID."),
        source: Literal["generated", "upload"] = Path(..., description="Table to look `file_uid` up in."),
        file_uid: UUID = Path(..., description="File UID to download."),
    ) -> StreamingResponse:
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            download = await files_service.download_file(ctx, str(file_uid), source)
            logging.info(f"[download-file] user={user_id} task_uid={task_uid} file_uid={file_uid} source={source}")
            return StreamingResponse(
                download.body,
                media_type=download.content_type,
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(download.filename)}"},
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[download-file] task_uid={task_uid} file_uid={file_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()

    @controller.patch(
        "/files/{task_uid}/favorite",
        summary="Favorite or unfavorite files.",
        description="Marks the selected files as favorites, or removes them from favorites.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def favorite_file(
        self, schema: SetFavoritedPayload, task_uid: UUID = Path(..., description="Task UID.")
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.set_favorited_generation(
                ctx, [str(uid) for uid in schema.file_uids], schema.is_favorited
            )
            key = "files_favorited" if schema.is_favorited else "files_unfavorited"
            response.message = resolve_message(key, current_lang.get())
            logging.info(
                f"[favorite-file] user={user_id} task_uid={task_uid} "
                f"file_uids={schema.file_uids} is_favorited={schema.is_favorited}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[favorite-file] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/set-main/{file_uid}",
        summary="Set a file as the main version.",
        description="Makes this file the featured version among its related versions.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def set_main_generation(
        self,
        task_uid: UUID = Path(..., description="Task UID."),
        file_uid: UUID = Path(..., description="Generation result UID to set as main."),
    ) -> Response:
        response = Response()
        files_service = FilesService()
        try:
            project_task = await files_service.get_project_task(self.db, task_uid)
            user_id = int(self.user["user_id"])
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.set_main_generation_result(ctx, str(file_uid))
            response.message = resolve_message("main_generation_set", current_lang.get())
            logging.info(f"[set-main-generation] user={user_id} task_uid={task_uid} file_uid={file_uid}")
        except BaseError:
            raise
        except Exception:
            logging.error(f"[set-main-generation] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.post(
        "/files/{task_uid}/folder",
        summary="Create a folder.",
        description="Adds a new folder inside the current folder.",
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.create_folder(ctx, schema.current_path, schema.name)
            response.message = resolve_message("folder_created", current_lang.get())
            logging.info(
                f"[create-folder] user={user_id} task_uid={task_uid} "
                f"current_path={schema.current_path} name={schema.name}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[create-folder] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.delete(
        "/files/{task_uid}/folder",
        summary="Delete a folder.",
        description="Removes a folder. Files inside it are kept and moved up a level, not deleted.",
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.delete_folder(ctx, schema.folder_path)
            response.message = resolve_message("folder_deleted", current_lang.get())
            logging.info(f"[delete-folder] user={user_id} task_uid={task_uid} folder_path={schema.folder_path}")
        except BaseError:
            raise
        except Exception:
            logging.error(f"[delete-folder] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.delete(
        "/files/{task_uid}/files",
        summary="Delete files.",
        description="Permanently removes the selected files. Generated files can't be deleted this way.",
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.delete_files(ctx, schema.file_uids)
            response.message = resolve_message("files_deleted", current_lang.get())
            logging.info(f"[delete-files] user={user_id} task_uid={task_uid} file_uids={schema.file_uids}")
        except BaseError:
            raise
        except Exception:
            logging.error(f"[delete-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/file",
        summary="Rename a file.",
        description="Changes a file's name. Its file type stays the same.",
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.rename_file(ctx, schema.file_uid, schema.name)
            response.message = resolve_message("file_renamed", current_lang.get())
            logging.info(
                f"[rename-file] user={user_id} task_uid={task_uid} file_uid={schema.file_uid} name={schema.name}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[rename-file] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/folder",
        summary="Rename a folder.",
        description="Changes a folder's name. Everything inside it stays the same.",
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.rename_folder(ctx, schema.folder_path, schema.name)
            response.message = resolve_message("folder_renamed", current_lang.get())
            logging.info(
                f"[rename-folder] user={user_id} task_uid={task_uid} folder_path={schema.folder_path} name={schema.name}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[rename-folder] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/files/move",
        summary="Move files.",
        description="Moves the selected files into a different folder.",
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.move_files(ctx, schema.file_uids, schema.destination)
            response.message = resolve_message("files_moved", current_lang.get())
            logging.info(
                f"[move-files] user={user_id} task_uid={task_uid} "
                f"file_uids={schema.file_uids} destination={schema.destination}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[move-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/folders/move",
        summary="Move folders.",
        description="Moves the selected folders into a different folder.",
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.move_folders(ctx, schema.folder_paths, schema.destination)
            response.message = resolve_message("folders_moved", current_lang.get())
            logging.info(
                f"[move-folders] user={user_id} task_uid={task_uid} "
                f"folder_paths={schema.folder_paths} destination={schema.destination}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[move-folders] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response
