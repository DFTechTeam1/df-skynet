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
        }
