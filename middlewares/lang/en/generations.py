class GenerationsMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "input_references_exceeded": "You've added too many references for this model.",
            "unsupported_generation_parameter": "This parameter isn't supported by the selected model.",
            "generation_parameters_invalid": "Some of the parameters you sent aren't supported by this model.",
            "generation_parameter_must_be_number": "This value must be a number.",
            "generation_parameter_below_minimum": "This value is too low.",
            "generation_parameter_above_maximum": "This value is too high.",
            "generation_parameter_not_in_enum": "This value isn't one of the allowed options.",
            "generation_parameter_must_be_boolean": "This value must be true or false.",
            "generation_parameter_required": "This parameter is required for the selected model.",
            "references_invalid": "One or more references you provided are invalid.",
            "reference_format_udin_url_required": "This DiVA reference is missing its file URL.",
            "reference_file_uid_required": "This reference is missing its file.",
            "prompt_length_exceeded": "Your prompt is {length} characters, which exceeds this project's limit of {max_chars} characters.",
            "feature_not_under_menu": "One or more selected features don't belong to this menu.",
            "generation_area_incomplete": "To set a focus area, x_min, x_max, y_min, and y_max must all be filled in.",
            "generation_area_image_edit_only": "Focus area (x_min, x_max, y_min, y_max) can only be set for image_edit generations.",
            "openrouter_generation_failed": "OpenRouter couldn't generate this. Please try again later.",
            "api_key_token_usage_limit_exceeded": "This API key has reached its usage limit and can no longer be used to generate.",
        }
