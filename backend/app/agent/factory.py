"""Select an inference engine without loading weights or contacting a server."""

from app.agent.inference import InferenceEngine, MockInferenceEngine
from app.agent.qwen import QwenInferenceEngine
from app.agent.settings import load_qwen_settings


def create_inference_engine() -> InferenceEngine:
    settings = load_qwen_settings()
    if settings is None:
        return MockInferenceEngine()
    return QwenInferenceEngine(settings)
