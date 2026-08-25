class SettingMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "setting_engine_model_must_be_text": "Model enhancer dan assistant harus berupa model teks.",
            "setting_engine_model_must_be_enabled": "Model enhancer dan assistant harus berupa model yang aktif (enabled).",
            "setting_engine_model_must_be_available": "Model enhancer dan assistant harus masih tersedia dari OpenRouter.",
        }
