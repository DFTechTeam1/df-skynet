from typing import Any
from starlette.concurrency import run_in_threadpool
from schemas.format.action import GeneratedFileAction, UploadedFileAction
from services.search import get_search_engine
from services.search.base import And, Equal, Filter, Or, SearchRequest
from services.search.docs import GENERATION_KINDS, MAIN_GENERATIONS, UPLOADED_FILES

MAX_HITS = 1000  # Algolia's hitsPerPage ceiling; the endpoints this feeds return the full list, so one page is the cap
_INTERNAL_KEYS = ("objectID", "project_uid")
_NAME_PATH = ["name", "path"]
_NAME_PATH_TASK = ["name", "path", "task"]


def _kinds(kinds: tuple[str, ...]) -> Filter:
    return Or([Equal("kind", str(kind)) for kind in kinds])


def _is_owner(doc: dict[str, Any], viewer_id: int) -> bool:
    return (doc.get("creator") or {}).get("user_id") == viewer_id


def _clean(doc: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in doc.items() if key not in _INTERNAL_KEYS}


def generation_with_action(doc: dict[str, Any], viewer_id: int, can_override: bool) -> dict[str, Any]:
    """An indexed generation doc in the shape `get_generation_main_refactored` returns: the viewer's `action` is
    worked out here (creator, else override role, else nothing) because the index stores `action` as null."""
    action = GeneratedFileAction.action(_is_owner(doc, viewer_id), can_override, doc)
    return {**_clean(doc), "variants": [], "references": [], "action": action.model_dump(mode="json")}


def upload_with_action(doc: dict[str, Any], viewer_id: int, can_override: bool) -> dict[str, Any]:
    """An indexed upload doc in the shape `get_user_uploaded_files_refactored` returns, with the viewer's `action`."""
    action = UploadedFileAction.action(_is_owner(doc, viewer_id), can_override)
    return {**_clean(doc), "action": action.model_dump(mode="json")}


async def _search(requests: list[SearchRequest]) -> list[list[dict[str, Any]]]:
    results = await run_in_threadpool(get_search_engine().search, requests)  # the Algolia SDK is sync
    return [[hit.data for hit in result.hits] for result in results]


async def search_project_files(
    project_uid: str,
    query: str,
    generation_kinds: tuple[str, ...],
    viewer_id: int,
    can_override: bool,
    personal_file: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`(uploaded_files, generations)` of one project matching `query` on name, path and task name. Same shapes as the
    getters behind `/files/{project_uid}` and `/references-picker/{project_uid}`. `personal_file` keeps only the
    viewer's own files, like `my_task` does there."""
    project = Equal("project_uid", project_uid)
    generations_filter = And([project, _kinds(generation_kinds)])
    uploads, generations = await _search(
        [
            SearchRequest(UPLOADED_FILES, query, project, limit=MAX_HITS, restrict_attributes=_NAME_PATH_TASK),
            SearchRequest(
                MAIN_GENERATIONS, query, generations_filter, limit=MAX_HITS, restrict_attributes=_NAME_PATH_TASK
            ),
        ]
    )
    if personal_file:
        uploads = [doc for doc in uploads if _is_owner(doc, viewer_id)]
        generations = [doc for doc in generations if _is_owner(doc, viewer_id)]
    return (
        [upload_with_action(doc, viewer_id, can_override) for doc in uploads],
        [generation_with_action(doc, viewer_id, can_override) for doc in generations],
    )


async def search_task_generations(
    task_uid: str,
    query: str,
    viewer_id: int,
    can_override: bool,
    personal_file: bool = False,
    kinds: tuple[str, ...] = (GENERATION_KINDS[0], GENERATION_KINDS[1]),
) -> list[dict[str, Any]]:
    """Generations of one task or song (matched by its uid in `task_uid` / `song_uid`) matching `query` on name and
    path. Same shape as `get_generation_main_refactored`."""
    scope = Or([Equal("task_uid", task_uid), Equal("song_uid", task_uid)])
    [docs] = await _search(
        [
            SearchRequest(
                MAIN_GENERATIONS, query, And([scope, _kinds(kinds)]), limit=MAX_HITS, restrict_attributes=_NAME_PATH
            )
        ]
    )
    if personal_file:
        docs = [doc for doc in docs if _is_owner(doc, viewer_id)]
    return [generation_with_action(doc, viewer_id, can_override) for doc in docs]


_PICKER_GROUPS = ("Image Generations", "Image Uploads", "Elements", "Shared")
_PICKER_HIDDEN_GENERATION = {
    "references",
    "variants",
    "is_main",
    "full_prompt",
    "prompt",
    "version",
    "parent_id",
    "parameter",
    "action",
    "cost_usd",
    "cost_idr",
    "status",
}


def group_reference_picker(generations: list[dict[str, Any]], uploads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The `/references-picker` payload. Used by both the DB and the search path so they can't drift: videos are left
    out (and folders, which can't be a reference) and each entry drops the fields the picker doesn't show."""
    files_by_group = {
        "Image Generations": [
            {key: value for key, value in generation.items() if key not in _PICKER_HIDDEN_GENERATION}
            for generation in generations
            if generation["kind"] != "video"
        ],
        "Image Uploads": [
            {key: value for key, value in file.items() if key != "action"}
            for file in uploads
            if file["kind"] not in ("video", "folder")
        ],
    }
    return [
        {"type": group, "total": len(files_by_group.get(group, [])), "files": files_by_group.get(group, [])}
        for group in _PICKER_GROUPS
    ]
