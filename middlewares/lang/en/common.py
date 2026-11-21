class CommonMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "too_many_requests": "Too many requests. Please wait a moment before trying again.",
            "success": "Success",
            "data_not_found_error": "We couldn't find what you're looking for.",
            "data_validation_error": "Some of the information you entered isn't valid. Please check and try again.",
            "data_conflict_error": "This conflicts with something that already exists. Please review and try again.",
            "project_action_requires_ongoing": "{action} can only be performed while the project is ongoing.",
            "default_model_not_configured": "The default {model} model hasn't been set up yet. Please ask your administrator to choose one in the settings.",
            "global_project_setting_not_configured": "The global project settings haven't been set up yet. Please ask your administrator to configure them in the settings.",
            "internal_server_error": "Something went wrong on our system. Please try again in a moment.",
            "chat_queue_unavailable": "We couldn't queue your message right now. Please try again in a moment.",
            "guardrail_prompt_injection": "Your message was blocked because it appears to try to override the system's instructions.",
            "guardrail_nsfw": "Your message was blocked because it contains content that isn't allowed.",
            "guardrail_chat_assistant": "Your message doesn't look like a question or a chat for the assistant. Please ask a question or tell us what you need help with.",
            "guardrail_use_case": "Detected use case: {use_case}.",
            "guardrail_no_use_case": "We couldn't tell what you want to do with this message. Please rephrase it.",
            "prompt_guardrail_timeout": "Checking your message took too long. Please try again in a moment.",
            "prompt_guardrail_provider_error": "The message check service returned an error. Please try again in a moment.",
            "prompt_guardrail_unreachable": "We couldn't reach the message check service. Please try again in a moment.",
        }
