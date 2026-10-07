from typing import Any
from services.mysql.model.df_engine_generations import GenerationKinds
from services.mysql.model.df_engine_upload_files import UploadFileTypes


def reference_sections(
    upload_rows: list[dict[str, Any]], generation_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Flat picker payload: image uploads, image generations and elements (videos and favorites are not offered)."""
    sections = {"Image Uploads": [], "Image Generations": [], "Elements": []}
    for row in upload_rows:
        if row["kind"] == UploadFileTypes.image:
            sections["Image Uploads"].append(row["file"])
    labels = {GenerationKinds.image: "Image Generations", GenerationKinds.element: "Elements"}
    for row in generation_rows:
        if row["kind"] in labels:
            sections[labels[row["kind"]]].append(row["file"])
    return [{"type": label, "total_data": len(files), "files": files} for label, files in sections.items()]
