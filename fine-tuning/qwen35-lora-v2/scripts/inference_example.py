"""
Runpod / FastAPI 백엔드 연동용 Qwen3.5-4B LoRA v2 추론 예제 스크립트
- Base Model: unsloth/Qwen3.5-4B (FP16)
- Adapter: qwen35-fashion-864-lora-v2 (별도 다운로드 후 로컬 경로 지정)
"""

import json
import torch
from transformers import AutoProcessor, AutoModelForCausalLM, StoppingCriteria, StoppingCriteriaList
from peft import PeftModel

BASE_MODEL_ID = "unsloth/Qwen3.5-4B"
ADAPTER_PATH = "./qwen35-fashion-864-lora-v2"  # 다운로드 받은 어댑터 폴더 경로

FR_SYSTEM = open("prompts/fr_system_prompt.txt", encoding="utf-8").read().strip()
TC_SYSTEM = open("prompts/tc_system_prompt.txt", encoding="utf-8").read().strip()
TOOLS_DEF = json.load(open("prompts/tools_schema.json", encoding="utf-8"))


class StopOnTokens(StoppingCriteria):
    def __init__(self, stop_token_ids):
        self.stop_token_ids = stop_token_ids

    def __call__(self, input_ids, scores, **kwargs):
        for stop_ids in self.stop_token_ids:
            if len(input_ids[0]) >= len(stop_ids):
                if input_ids[0][-len(stop_ids):].tolist() == stop_ids:
                    return True
        return False


def load_fashion_agent(base_model_id=BASE_MODEL_ID, adapter_path=ADAPTER_PATH):
    processor = AutoProcessor.from_pretrained(adapter_path)
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_id,
        torch_dtype=torch.float16,
        device_map="auto",
    )
    model = PeftModel.from_pretrained(base_model, adapter_path)
    model.eval()
    return model, processor


def run_tool_calling_step(model, processor, messages):
    """
    1단계: Tool Calling 라우팅 및 도구 호출 생성
    주의: 모델이 가상의 <tool_response>까지 자가 생성하지 않도록 '</tool_call>'에서 생성을 중단합니다.
    """
    prompt = processor.apply_chat_template(
        messages,
        tools=TOOLS_DEF,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = processor(text=prompt, return_tensors="pt", add_special_tokens=False).to(model.device)
    stop_ids = [processor.tokenizer.encode("</tool_call>", add_special_tokens=False)]
    stopping_criteria = StoppingCriteriaList([StopOnTokens(stop_ids)])

    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=False,
            use_cache=True,
            stopping_criteria=stopping_criteria,
        )
    generated = output[:, inputs["input_ids"].shape[1]:]
    return processor.batch_decode(generated, skip_special_tokens=True)[0]


def generate_five_looks(model, processor, user_request: str, context_obj: dict, base_time: str):
    """
    2단계: 수집된 context를 바탕으로 5 LOOK 코디 JSON 생성
    """
    user_content = (
        f"기준 시각: {base_time}\n"
        f"사용자 요청: {user_request}\n"
        f"context: {json.dumps(context_obj, ensure_ascii=False, separators=(',', ':'))}"
    )
    messages = [
        {"role": "system", "content": FR_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    prompt = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = processor(text=prompt, return_tensors="pt", add_special_tokens=False).to(model.device)

    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=1600,
            do_sample=True,
            temperature=0.35,
            top_p=0.9,
            repetition_penalty=1.08,
            use_cache=True,
        )
    generated = output[:, inputs["input_ids"].shape[1]:]
    raw_text = processor.batch_decode(generated, skip_special_tokens=True)[0]
    start, end = raw_text.find("{"), raw_text.rfind("}")
    return json.loads(raw_text[start:end + 1])


if __name__ == "__main__":
    model, processor = load_fashion_agent()

    # 1) Tool Calling 테스트
    tc_messages = [
        {"role": "system", "content": TC_SYSTEM},
        {"role": "user", "content": "기준 시각: 2026-11-25T14:00:00+09:00\n사용자 요청: 내일 저녁 전주 객리단길 약속 있는데 날씨 보고 내 옷장으로 코디해줘."},
    ]
    print("=== [1단계] Tool Calling 출력 ===")
    print(run_tool_calling_step(model, processor, tc_messages))

    # 2) 5 LOOK 생성 테스트
    sample_ctx = {
        "profile": {"gender": "male", "age_group": "20s", "height_cm": 178, "body_type": "normal"},
        "preference": {"preferred_styles": ["minimal", "classic"], "preferred_colors": ["navy", "white", "black"], "disliked_colors": ["orange"], "preferred_fit": "regular"},
        "weather": {"temperature_c": 11, "precipitation_probability": 10, "precipitation_type": "none", "wind_mps": 2.0, "humidity_percent": 45, "sky": "clear"},
        "schedule": {"date": "2026-11-26", "time": "19:00", "place": "전주 객리단길", "tpo": "dinner"},
        "wardrobe": [
            {"item_id": 101, "category": "top", "item_type": "knit", "color": "ivory", "fit": "regular", "seasons": ["fall", "winter"]},
            {"item_id": 102, "category": "bottom", "item_type": "slacks", "color": "charcoal", "fit": "regular", "seasons": ["fall", "winter"]},
            {"item_id": 103, "category": "outer", "item_type": "coat", "color": "navy", "fit": "regular", "seasons": ["winter"]},
            {"item_id": 104, "category": "shoes", "item_type": "derby_shoes", "color": "black", "fit": "regular", "seasons": ["fall", "winter"]},
        ],
    }
    print("\n=== [2단계] 5 LOOK 코디 생성 출력 ===")
    looks_result = generate_five_looks(model, processor, "내일 저녁 전주 객리단길 약속 코디 추천해줘.", sample_ctx, "2026-11-25T14:00:00+09:00")
    print(json.dumps(looks_result, ensure_ascii=False, indent=2))
