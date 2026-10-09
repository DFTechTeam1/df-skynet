from typing import Any
from services.mysql.model.df_engine_generations import GenerationKinds
from services.mysql.model.df_engine_upload_files import UploadFileTypes

# Generation kinds the picker offers, and the section each lands in (an edited image is still an image).
GENERATION_SECTIONS = {
    GenerationKinds.image: "Image Generations",
    GenerationKinds.image_edit: "Image Generations",
    GenerationKinds.element: "Elements",
}


def reference_sections(
    upload_rows: list[dict[str, Any]], generation_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Flat picker payload: image uploads, image generations and elements (videos and favorites are not offered)."""
    sections = {"Image Uploads": [], "Image Generations": [], "Elements": []}
    for row in upload_rows:
        if row["kind"] == UploadFileTypes.image:
            sections["Image Uploads"].append(row["file"])
    labels = GENERATION_SECTIONS
    for row in generation_rows:
        if row["kind"] in labels:
            sections[labels[row["kind"]]].append(row["file"])
    return [{"type": label, "total_data": len(files), "files": files} for label, files in sections.items()]


def global_reference_sections(
    upload_rows: list[dict[str, Any]], generation_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Global picker payload: the same three sections as `reference_sections`, each grouped projects -> tasks -> files.
    Projects and tasks keep the order their first file appears in (rows arrive newest first)."""
    sections: dict[str, list[dict[str, Any]]] = {"Image Uploads": [], "Image Generations": [], "Elements": []}
    labels = GENERATION_SECTIONS
    rows = [("Image Uploads", row) for row in upload_rows if row["kind"] == UploadFileTypes.image]
    rows += [(labels[row["kind"]], row) for row in generation_rows if row["kind"] in labels]

    projects: dict[str, dict[Any, dict[str, Any]]] = {label: {} for label in sections}
    for label, row in rows:
        project = projects[label].setdefault(
            row["project_id"], {"id": row["project_id"], "name": row["project_name"], "tasks": {}}
        )
        task = project["tasks"].setdefault(
            row["task_id"], {"id": row["task_id"], "name": row["task_name"], "files": []}
        )
        task["files"].append(row["file"])

    return [
        {
            "type": label,
            "total_data": sum(
                len(task["files"]) for project in by_project.values() for task in project["tasks"].values()
            ),
            "projects": [{**project, "tasks": list(project["tasks"].values())} for project in by_project.values()],
        }
        for label, by_project in projects.items()
    ]
