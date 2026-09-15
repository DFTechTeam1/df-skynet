import time
import traceback
from typing import Any, Literal
from uuid import UUID
from fastapi import Path, Query, Request, status
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.get_tree(ctx)
            response.message = resolve_message("files_fetched", current_lang.get())
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.get_folder_detail(ctx, folder_path)
            response.message = resolve_message("folder_detail_fetched", current_lang.get())
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-folder-detail] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/file/{file_uid}",
        summary="Get a single file's detail.",
        description=(
            "Returns one file entry by its `uid`. `type=upload` (default) looks it up in the live "
            "upload/generated tree; `type=generated` looks up a generation result directly, "
            "regardless of whether it's archived or favourited - the uid alone identifies it."
        ),
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
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-file-detail] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/archieved",
        summary="Get archived generation results.",
        description=(
            "Returns archived generation results as a flat (one-level) list of files, in the same "
            "shape as `GET /files/{task_uid}` (no `variants`, since these are always leaf results). "
            "Uploads are never archivable, so only generated files appear here. `type` optionally "
            "restricts the list to `image` or `video`; omitted/null returns both."
        ),
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
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-archived-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/favourited",
        summary="Get favourited generation results.",
        description=(
            "Returns this user's favourited generation results as a flat (one-level) list of files, "
            "in the same shape as `GET /files/{task_uid}` (no `variants`, since these are always leaf "
            "results). `type` optionally restricts the list to `image` or `video`; omitted/null "
            "returns both."
        ),
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
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-favourited-files] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/archieve",
        summary="Archive or unarchive multiple generation results.",
        description=(
            "Sets `archieved_at` on every generation result listed in `file_uids`, all-or-nothing. "
            "`is_archieved=true` (default) archives live, non-favourited results; "
            "`is_archieved=false` unarchives them."
        ),
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
        except BaseError:
            raise
        except Exception:
            logging.error(f"[archive-file] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/favorite",
        summary="Favorite or unfavorite multiple generation results.",
        description=(
            "Sets `is_favourite` on every generation result listed in `file_uids`, all-or-nothing. "
            "`is_favorited=true` (default) favorites live, non-archived results; "
            "`is_favorited=false` unfavorites them."
        ),
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
        except BaseError:
            raise
        except Exception:
            logging.error(f"[favorite-file] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/set-main/{file_uid}",
        summary="Set a generation result as main among its parent's results.",
        description=(
            "Flips `is_main` to true on `file_uid`, atomically flipping its previous sibling "
            "main (if any) to false in the same call. Re-setting the already-current main is a "
            "no-op 200. Errors if `file_uid` is unknown or is a root result with no parent."
        ),
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
        except BaseError:
            raise
        except Exception:
            logging.error(f"[set-main-generation] task_uid={task_uid} failed\n{traceback.format_exc()}")
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.create_folder(ctx, schema.current_path, schema.name)
            response.message = resolve_message("folder_created", current_lang.get())
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.delete_folder(ctx, schema.folder_path)
            response.message = resolve_message("folder_deleted", current_lang.get())
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.delete_files(ctx, schema.file_uids)
            response.message = resolve_message("files_deleted", current_lang.get())
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.rename_file(ctx, schema.file_uid, schema.name)
            response.message = resolve_message("file_renamed", current_lang.get())
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.rename_folder(ctx, schema.folder_path, schema.name)
            response.message = resolve_message("folder_renamed", current_lang.get())
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.move_files(ctx, schema.file_uids, schema.destination)
            response.message = resolve_message("files_moved", current_lang.get())
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
            ctx = FileCtx(db=self.db, redis=self.redis, project_task=project_task, user_id=user_id)

            response.data = await files_service.move_folders(ctx, schema.folder_paths, schema.destination)
            response.message = resolve_message("folders_moved", current_lang.get())
        except BaseError:
            raise
        except Exception:
            logging.error(f"[move-folders] task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response
