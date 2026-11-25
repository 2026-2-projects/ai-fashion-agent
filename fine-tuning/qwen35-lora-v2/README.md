---

base_model: unsloth/Qwen3.5-4B 
library_name: peft 
pipeline_tag: text-generation 
language:
- ko 
license: apache-2.0 
tags:
- qwen
- lora
- sft
- transformers
- trl
- unsloth
- fashion-agent
- tool-calling

---

# Model Card for `hhoyaa/qwen35-fashion-864-lora-v2`

**AI Fashion Agent** 서비스를 위해 `unsloth/Qwen3.5-4B` 모델을 LoRA(Low-Rank Adaptation) 방식으로 파인튜닝한 한국어 패션 특화 어댑터 모델입니다. 사용자의 프로필·취향·날씨·일정·보유 옷장 데이터를 바탕으로 **4가지 도구 호출(Tool Calling) 라우팅**과 **5개 슬롯(5 LOOK) 맞춤형 코디 JSON 생성**을 수행합니다.

---

## Model Details

### Model Description

이 모델은 단순한 패션 질의응답을 넘어, 백엔드 에이전트 루프 내에서 필요한 외부 컨텍스트(사용자 정보, 옷장, 날씨, 캘린더 일정)만 선택적으로 조회하고, 최종적으로 서비스 스키마에 맞는 5가지 코디 추천 결과를 반환하도록 학습되었습니다.

* **Developed by:** @hhoyaa (2026-2-projects / AI Fashion Agent Team)
* **Model type:** Causal Language Model (SLM + LoRA Adapter)
* **Language(s) (NLP):** 한국어 (Korean)
* **License:** Apache-2.0
* **Finetuned from model:** `unsloth/Qwen3.5-4B`

### Model Sources

* **Hugging Face Model Hub:** <https://huggingface.co/hhoyaa/qwen35-fashion-864-lora-v2>
* **GitHub Repository:** <https://github.com/2026-2-projects/ai-fashion-agent> (Branch: `feature/qwen35-lora-v2`)

---

## Uses

### Direct Use

이 모델은 크게 두 가지 시스템 프롬프트 모드에서 직접 사용할 수 있습니다.

1. **Tool Calling 라우팅 모드 (`TC_SYSTEM`):**
   * 사용자 요청을 분석하여 허용된 4가지 도구(`get_user_context`, `get_wardrobe`, `get_weather`, `get_calendar_events`) 중 필요한 도구만 호출하거나, 단순 패션 상식 질문의 경우 도구 없이 `direct_answer` JSON을 반환합니다.
   * 정보 수집이 완료되면 최종 행동으로 `{"type": "fashion_recommendation", "action": "generate_five_looks", ...}`를 출력합니다.
2. **5 LOOK 코디 생성 모드 (`FR_SYSTEM`):**
   * 수집된 `context`만을 근거로 고정된 5개 슬롯(`preference_best`, `preference_alternative`, `exploration`, `wardrobe_best`, `wardrobe_alternative`) 구조의 JSON 객체 `{"looks": [...]}`를 반환합니다.
   * `LOOK 1~3`은 일반 추천(`item_id: null`), `LOOK 4~5`는 실제 보유 옷장(`context.wardrobe`)의 `item_id`만 사용하며, 조건상 구성할 수 없는 슬롯은 `status: "unavailable"`과 사유를 명시합니다.

### Downstream Use

* **Runpod / vLLM / FastAPI 추론 서버 연동:** GPU 서버에 베이스 모델(`unsloth/Qwen3.5-4B`)과 본 LoRA 어댑터를 로드하여 OpenAI 호환 API 또는 전용 추론 엔드포인트로 서빙합니다.
* **백엔드 Agent Core 및 Validator 연결:** FastAPI 백엔드에서 실제 Kakao Local, 기상청 API, Google Calendar API, PostgreSQL 옷장 DB와 연결하여 전체 추천 파이프라인을 구동합니다.

### Out-of-Scope Use

* 패션·코디 추천 및 일정/날씨 기반 옷차림 상담 외의 범용 지식 질의응답
* 확인되지 않은 외부 쇼핑몰 URL, 이미지 URL, 또는 사용자 옷장에 없는 의류 속성/ID 임의 생성

---

## Bias, Risks, and Limitations

* **학습 데이터 규모 및 도메인 한계:** 총 864건의 한국어 SFT 데이터로 1 Epoch 학습되었으므로, 학습 데이터 분포를 크게 벗어나는 특수 의복이나 극단적 상황에서는 표현이 다소 단조로워질 수 있습니다.
* **합성 평가 데이터 기반 검증:** 확장 평가셋(`new_100`)은 구조적·기능적 자동 채점을 위해 설계된 합성 데이터이며, 실제 서비스 오픈 후 사용자 피드백(좋아요/싫어요/저장) 기반의 HITL(Human-in-the-Loop) 데이터 수집 및 v0.2 재학습이 권장됩니다.
* **다중 도구 호출 시 자가 시뮬레이션 주의:** 복합 조회 질의에서 모델이 첫 번째 `<tool_call>`을 생성한 뒤 멈추지 않고 가상의 `<tool_response>`까지 이어서 생성할 수 있습니다. 백엔드 추론 루프에서는 반드시 `stop=["</tool_call>"]` 파라미터를 설정해야 합니다.

### Recommendations

* 백엔드 연동 시 모델이 출력한 JSON에 대해 반드시 \*\*Validator(스키마 검사, 1개 LOOK 내 중복 `slot` 검사, `LOOK 4~5`의 실제 DB `item_id` 존재 여부 검사)\*\*를 거친 뒤 프론트엔드로 전달하세요.

---

## How to Get Started with the Model

### 1. 추론 실행 코드 (`Unsloth` / `PEFT` 기반)

Runpod 또는 Colab GPU 환경에서 베이스 모델과 Hugging Face에 업로드된 어댑터를 함께 로드하여 추론하는 예제입니다.

```python
import torch
from unsloth import FastLanguageModel

BASE_MODEL_ID = "unsloth/Qwen3.5-4B"
ADAPTER_MODEL_ID = "hhoyaa/qwen35-fashion-864-lora-v2"

# 1. 베이스 모델 및 어댑터 로드 (FP16)
model, processor = FastLanguageModel.from_pretrained(
    model_name=ADAPTER_MODEL_ID,
    max_seq_length=4096,
    load_in_4bit=False,
    dtype=torch.float16,
)
FastLanguageModel.for_inference(model)
tokenizer = getattr(processor, "tokenizer", processor)

# 2. 5 LOOK 코디 생성 프롬프트 예시
FR_SYSTEM_PROMPT = (
    '너는 개인 맞춤형 패션 코디 생성기다. 아래 사용자 요청 및 제공된 context만을 근거로 '
    'JSON 객체 {"looks": [...]}를 반환한다. 5개 슬롯의 role 순서는 '
    'preference_best, preference_alternative, exploration, wardrobe_best, wardrobe_alternative이다. '
    'LOOK 1~3의 item_id는 null, LOOK 4~5는 context.wardrobe에 등록된 item_id만 쓴다. '
    '사용자의 제약을 우선하고 구성할 수 없는 LOOK은 unavailable로 반환한다. '
    '이미지 URL이나 확인되지 않은 사실을 생성하지 않는다.'
)

messages = [
    {"role": "system", "content": FR_SYSTEM_PROMPT},
    {
        "role": "user",
        "content": (
            '기준 시각: 2026-10-07T20:00:00+09:00\n'
            '사용자 요청: 내일 저녁 객리단길 와인바에서 소개팅이 있어. 로고가 크게 보이지 않는 차분한 올드머니 스타일로 입고 싶어.\n'
            'context: {"profile":{"gender":"male","age_group":"30s"},"preference":{"preferred_styles":["old_money","classic"],"preferred_colors":["navy","cream","brown"],"disliked_colors":["neon_yellow"],"preferred_fit":"regular"},"weather":{"temperature_c":13,"precipitation_probability":10,"sky":"clear"},"wardrobe":[{"item_id":10061,"category":"top","item_type":"knit","color":"cream","fit":"regular"},{"item_id":10062,"category":"bottom","item_type":"slacks","color":"brown","fit":"regular"},{"item_id":10063,"category":"shoes","item_type":"loafers","color":"dark_brown","fit":"regular"},{"item_id":10068,"category":"outer","item_type":"cardigan","color":"camel","fit":"regular"}]}'
        ),
    },
]

prompt = tokenizer.apply_chat_template(
    messages,
    tokenize=False,
    add_generation_prompt=True,
    enable_thinking=False,
)
inputs = tokenizer(prompt, return_tensors="pt").to("cuda")

with torch.no_grad():
    outputs = model.generate(
        **inputs,
        max_new_tokens=1400,
        do_sample=True,
        temperature=0.35,
        top_p=0.9,
        repetition_penalty=1.08,
    )

response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
print(response)
```

### 2. 태스크별 권장 추론 파라미터

| 호출 단계 | `do_sample` | `temperature` | `repetition_penalty` | `max_new_tokens` | 필수 제어 옵션 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Tool Calling 라우팅** | `False` | `0.0` (Greedy) | `1.0` | `512` | `stop=["</tool_call>"]` |
| **5 LOOK 코디 생성** | `True` | `0.35` | `1.08` | `1400` | JSON 스키마 후처리 검증 |

---

## Training Details

### Training Data

총 **1,080건**의 데이터셋을 학습·검증·테스트로 엄격히 분리하여 사용했으며, 사전 무결성 검사를 통해 분할 간 데이터 중복 0건 및 최대 시퀀스 길이(1,901 토큰 이하)를 검증했습니다.

| 분할 (Split) | 패션 추천 (FR) | Tool Calling (TC) | 합계 | 비고 |
| :--- | :---: | :---: | :---: | :--- |
| **Train (학습)** | 540건 | 324건 | **864건** | 기존 664건 + 추가 200건 통합본 |
| **Validation (신규 검증)** | 60건 | 40건 | **100건** | 엣지 케이스 포함 확장 검증셋 |
| **Test (신규 테스트)** | 60건 | 40건 | **100건** | 최종 정량 평가용 확장 테스트셋 |
| **Legacy Val / Test** | 5건씩 | 3건씩 | **16건** | 기존 v0.1 회귀 비교용 보존셋 |

### Training Procedure

#### Preprocessing & Overfitting Prevention

1. **Completion-Only Loss (`train_on_responses_only`):** 긴 시스템 프롬프트 및 JSON 컨텍스트 입력 부분은 Loss 계산에서 마스킹하고, 오직 `<|im_start|>assistant` 응답 구간에 대해서만 오차를 학습하도록 설정했습니다.
2. **NEFTune (`neftune_noise_alpha=5`):** 학습 시 입력 임베딩에 미세 노이즈를 주입하여 소규모 데이터셋의 기계적 암기를 억제하고 추천 사유(`reason`)의 표현 다양성을 높였습니다.
3. **균등 셔플링 (`seed=42`):** 패션 추천(540건)과 Tool Calling(324건) 데이터가 전체 216 step에 고르게 분포하도록 셔플링했습니다.

#### Training Hyperparameters

* **Training regime:** FP16 Mixed Precision (`load_in_4bit=False`, `load_in_16bit=True`)
* **LoRA Config:** `r=16`, `lora_alpha=16`, `lora_dropout=0`, Target Modules (`q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`)
* **Epochs / Steps:** 1 Epoch (216 Steps)
* **Batch Size:** Per-device `1` × Gradient Accumulation `4` = Effective Batch Size `4`
* **Optimizer & Scheduler:** `adamw_8bit`, Learning Rate `2e-4`, `cosine` scheduler, `warmup_ratio=0.05`, `weight_decay=0.01`
* **Max Sequence Length:** `4,096`

#### Speeds, Sizes, Times

* **총 학습 소요 시간:** 약 58분 21초 (Google Colab Tesla T4 GPU 기준)
* **어댑터 가중치 크기:** 약 85 MB (`adapter_model.safetensors`)
* **학습 Loss 변화:** 초기 `0.928` → 종료 시점 `0.276` (전체 평균 Train Loss `0.310`, Validation Loss `0.582`)

---

## Evaluation

### Testing Data, Factors & Metrics

#### Testing Data

* **`new_100` (신규 확장 테스트셋 100건):** 일반·옷장 추천, 옷장 전용 제약(`LOOK 1~3 unavailable`), 빈 옷장·의류 부족(`LOOK 4~5 unavailable`), 기피 색상·날씨 제약, 4대 도구 개별/복합 호출, `direct_answer`, 특정 도구 조회 제외 조건 포함
* **`legacy_8` (기존 회귀 테스트셋 8건):** 기존 v0.1 실험과의 일관성 비교용

#### Metrics

1. `json_valid`: 유효한 JSON 객체 파싱 성공 여부
2. `five_looks`: `looks` 배열 내 정확히 5개 슬롯 반환 여부
3. `roles_correct`: 고정된 5개 `role` 순서 준수 여부
4. `look_ids_correct`: `look_id` 1\~5 순차 부여 여부
5. `no_duplicate_slots`: 단일 LOOK 내 의류 카테고리(`slot`) 중복 없음 여부
6. `wardrobe_ids_valid`: `LOOK 4~5`에서 `context.wardrobe`에 실제 존재하는 `item_id`만 사용했는지 여부
7. `first_action_correct`: Tool Calling 시나리오에서 올바른 첫 도구 선택, `direct_answer`, 또는 `generate_five_looks` 행동 수행 여부

### Results

#### 1. 신규 확장 테스트셋 (`new_100` — 100건 기준)

| 평가 지표 | Base Model (`Qwen3.5-4B`) | Fine-tuned v2 (`LoRA-864-v2`) | 개선 폭 |
| :--- | :---: | :---: | :---: |
| **JSON 유효성 (`json_valid`)** | 86.8% (59/68) | **100.0% (68/68)** | +13.2%p |
| **5 LOOK 슬롯 수 (`five_looks`)** | 98.3% (59/60) | **100.0% (60/60)** | +1.7%p |
| **Role 순서 정확도 (`roles_correct`)** | 98.3% (59/60) | **100.0% (60/60)** | +1.7%p |
| **LOOK ID 정확도 (`look_ids_correct`)** | 23.3% (14/60) | **100.0% (60/60)** | +76.7%p |
| **슬롯 중복 없음 (`no_duplicate_slots`)** | 11.7% (7/60) | **100.0% (60/60)** | +88.3%p |
| **옷장 ID 정합성 (`wardrobe_ids_valid`)** | 68.3% (41/60) | **100.0% (60/60)** | +31.7%p |
| **첫 행동/도구 선택 (`first_action_correct`)** | 80.0% (32/40) | **100.0% (40/40)** | +20.0%p |

#### 2. 기존 회귀 테스트셋 (`legacy_8` — 8건 기준)

* Base Model에서 `0.0% (0/5)`였던 `no_duplicate_slots`를 포함해 **7개 전 평가 지표 모두 100.0% 통과**를 달성했습니다.

---

## Environmental Impact

* **Hardware Type:** NVIDIA Tesla T4 GPU (16GB VRAM)
* **Hours used:** 약 0.97시간 (58분 21초)
* **Cloud Provider:** Google Colaboratory

---

## Technical Specifications

### Model Architecture and Objective

* **Base Architecture:** Qwen3.5-4B (Causal Language Model)
* **Fine-tuning Method:** Supervised Fine-Tuning (SFT) with LoRA (`r=16`, `alpha=16`, Trainable parameters: `21,233,664` / `0.47%`)
* **Objective:** Completion-only Cross-Entropy Loss on assistant responses

### Compute Infrastructure & Software

* **Hardware:** NVIDIA Tesla T4 (16GB VRAM)
* **Framework Versions:**
  * `Unsloth`: `2026.11.6`
  * `PEFT`: `0.21.2`
  * `Transformers` / `TRL` / `PyTorch` (CUDA FP16 환경)

---

## Model Card Contact

* **Developer / Maintainer:** `@hhoyaa` (AI Fashion Agent Team)
* **Project Repository:** <https://github.com/2026-2-projects/ai-fashion-agent>