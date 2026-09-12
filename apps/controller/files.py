import traceback
from uuid import UUID
from fastapi import Path, Request, status
from fastapi_controller import controller
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL
from error import BaseError, DataNotFoundError, ServiceError, DataValidationError
from log import logging
from schemas.response import Response
from utils.serializer import serialize
from services.api_caller import APICaller
from services.files import FilesService
from services.redis import CacheKeys, set_json
from services.mysql import query
from services.mysql.model import ProjectTasks
from services.mysql.model.df_engine_upload_files import DfEngineUploadFiles, UploadFileTypes


class FilesController(CoreDependencies):
    @controller.post(
        "/files/upload/{uid}",
        summary="Uploads to Udin Storage.",
        description=(
            "Streams the multipart request body as-is to the storage engine's upload "
            "endpoint for the task `uid`. File validation (extension, size, count) "
            "is enforced by the storage engine itself. Returns every file uploaded so "
            "far for this task, each carrying the actions available to the current user "
            "(only the file's own uploader may rename/delete/move it)."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def upload_files(self, request: Request, uid: UUID = Path(..., description="Task UID.")) -> Response:
        response = Response()
        logging.info(f"[upload-files] uid={uid} forwarding to udin")
        try:
            project_task = await query(
                db=self.db,
                table=ProjectTasks,
                filters=(ProjectTasks.uid == str(uid),),
                options=(selectinload(ProjectTasks.project),),  # type: ignore
                fetch_one=True,
            )

            project_task = serialize(project_task)

            # Note: Validation will be enabled later
            # if not project_task:
            #     raise DataNotFoundError(message="project_task_not_found")

            # if project_task['status'] == 4:
            #     raise DataValidationError(message="task_already_finished")

            # if project_task['project']['status'] != 6:
            #     raise DataValidationError(message="project_not_ongoing")

            project_uid = project_task["project"]["uid"]

            async with APICaller(
                base_url=UDIN_BASE_URL,
                headers={"X-API-Key": UDIN_API_KEY, "Content-Type": request.headers.get("content-type", "")},
            ) as caller:
                upstream = await caller.call(
                    "POST",
                    f"/engine/storage/upload-files/{project_uid}",
                    content=request.stream(),
                    raise_for_status=False,
                )

            try:
                body = upstream.json() if upstream.content else {}
            except ValueError:
                body = {}
            if upstream.status_code >= status.HTTP_400_BAD_REQUEST:
                raise BaseError(
                    status_code=upstream.status_code,
                    message="upload_failed",
                    error=body.get("error"),
                )
            uploaded = body.get("data") or []
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
            task_files = serialize(
                await query(
                    db=self.db, table=DfEngineUploadFiles, filters=(DfEngineUploadFiles.task_id == project_task["id"],)
                )
            )
            mapped_files = FilesService().map_file_actions(task_files, user_id)
            await set_json(self.redis, CacheKeys().user_files(user_id, project_task["id"]), mapped_files)

            response.data = mapped_files
            response.message = "Files successfully uploaded."
            logging.info(f"[upload-files] uid={uid} succeeded, status={upstream.status_code}")
        except BaseError as e:
            logging.warning(f"[upload-files] uid={uid} rejected ({e.status_code}): {e.message}")
            raise
        except Exception:
            logging.error(f"[upload-files] uid={uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response
