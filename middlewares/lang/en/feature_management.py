class FeatureManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "feature_not_found": "Feature not found.",
            "feature_already_exists": "A feature with this name already exists.",
            "feature_template_not_found": "One or more selected prompt templates could not be found.",
        }
