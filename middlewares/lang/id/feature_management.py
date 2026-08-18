class FeatureManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "feature_not_found": "Feature tidak ditemukan.",
            "feature_already_exists": "Feature dengan nama yang sama sudah ada.",
            "feature_template_not_found": "Satu atau lebih prompt template yang dipilih tidak ditemukan.",
        }
