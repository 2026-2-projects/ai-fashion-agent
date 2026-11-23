"""Public inference errors never carry prompts, credentials, or upstream bodies."""


class InferenceConfigurationError(Exception):
    """Invalid backend-owned inference configuration."""


class InferenceUnavailableError(Exception):
    """The configured model server is unreachable or unavailable."""


class InferenceTimeoutError(Exception):
    """A model-server operation exceeded its timeout."""


class InferenceResponseError(Exception):
    """The model did not return a complete, valid AgentDraft."""


class InferenceInputError(Exception):
    """The context exceeds the configured input budget."""
