class ElementsMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "element_created": "Element successfully created.",
            "elements_fetched": "Elements successfully retrieved.",
            "element_fetched": "Element successfully retrieved.",
            "element_not_found": "We couldn't find that element.",
            "element_updated": "Element successfully updated.",
            "element_deleted": "Element successfully deleted.",
            "element_file_renamed": "File successfully renamed.",
            "element_file_not_found": "We couldn't find that file.",
            "element_file_not_creator": "Only the person who uploaded this file can rename it.",
            "element_uploaded": "Images successfully uploaded.",
            "element_upload_no_files": "Please attach at least one image.",
            "element_upload_image_only": "Only JPG, JPEG or PNG images can be uploaded.",
            "element_upload_timeout": "The upload took too long. Please try again.",
            "element_has_generations": "This element can't be deleted because it already has generations.",
            "element_action_not_permitted": "You don't have permission to modify this element.",
        }
