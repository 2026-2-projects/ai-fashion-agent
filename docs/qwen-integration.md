# CLOMORI Qwen 추론 연결

FastAPI는 기본적으로 `MockInferenceEngine`을 사용합니다. `qwen`으로 설정하면 추천의 LOOK 생성 단계를 별도의 OpenAI 호환 모델 서버로 보냅니다. 현재 검증 범위는 가짜 HTTP 응답과 기존 API 계약입니다. 실제 학습 모델의 실행 여부, 지연 시간, 추천 품질은 모델 수령 후 확인합니다.

## 추천 흐름

1. 프론트는 기존 `/api/v1/agent/clarify`에서 되묻기와 장소·날짜·시간 확인을 마친 뒤 `resolved_request`로 `/api/v1/agent/recommend`를 호출합니다.
2. 로그인과 CSRF를 확인한 백엔드가 기존 규칙으로 Tool을 선택합니다. 취향·옷장은 항상 조회하고, 날씨·일정은 기존 키워드 및 입력 검증을 따릅니다. Qwen에는 Tool 정의나 실행 권한 없이 조회 결과만 전달합니다.
3. Qwen은 한 번의 `POST <QWEN_BASE_URL>/chat/completions` 요청에서 LOOK 1~5를 생성합니다. 백엔드는 조회 내역으로 `context_summary`를 만들고, 개수·순서·슬롯·소유 ID·조합을 검증합니다. 소유 확인을 통과한 옷장 사진은 백엔드가 연결합니다.
4. 검증을 통과한 결과를 저장하고 기존 `recommendation_id`, `type`, `action`, `called_tools`, `context_summary`, `looks`를 반환합니다. 상품 이미지 조회, 피드백, 저장 코디는 기존 API를 사용합니다.

## 모델 입력과 출력

- 시스템 메시지는 [`backend/app/agent/prompts.py`](../backend/app/agent/prompts.py)의 한국어 지시와 JSON Schema입니다. 사용자 메시지는 `prompt_version`, `request`(`message`, `place`, `date`, `time`), 기존 옷장 전용 규칙을 적용한 `wardrobe_only`, `context`를 담은 JSON 문자열입니다. 구조화된 장소·날짜·시간을 우선합니다.
- `context`의 `profile`, `preference`, `feedback_summary`에는 패션에 쓰는 프로필·수동 취향·선호 및 비선호 스타일 요약을 담습니다. `wardrobe`에는 해당 사용자의 `item_id`, `category`, `item_type`, `color`, `fit`, `seasons`가 들어갑니다. `weather`와 `calendar_events`는 조회했을 때만 들어가며, 일정은 제목·시작·끝·종일 여부·장소만 사용합니다. 계정 ID·이메일·연결 토큰·사진 파일과 경로는 Tool 결과에서 제외합니다. 사용자 문장과 일부 일정 정보는 모델 서버에 전달되므로 실제 데이터에는 팀이 신뢰하는 서버를 사용합니다.
- 저장소의 [v1.1 데이터셋](../data/releases/qwen3_fashion_664_v1_1/README.md)에서 코디 생성용 415건의 최종 응답은 `{"looks":[...]}`입니다. 모델 출력은 이 형식에 맞췄습니다. 다른 학습 분할이나 대화 템플릿을 썼다면 수령 후 입출력을 대조합니다.
- LOOK은 `look_id`, `role`, `status`, `style`, `items`, `reason`을 포함합니다. 역할은 1 `preference_best`, 2 `preference_alternative`, 3 `exploration`, 4 `wardrobe_best`, 5 `wardrobe_alternative` 순서입니다. `available`에는 `top`, `bottom`, `shoes`가 각 하나씩 필요하며 `outer`, `accessory`는 선택입니다. `unavailable`은 `style: null`, `items: []`와 사유를 담습니다.
- 아이템은 `slot`, `name`, `item_id`를 가집니다. LOOK 1~3의 `item_id`는 `null`, LOOK 4~5는 해당 사용자의 옷장 ID인 양의 정수입니다. LOOK 5를 사용할 수 있으면 LOOK 4도 사용할 수 있어야 하고 둘의 의류 조합은 달라야 합니다. 사진 URL은 백엔드가 검증 후 채웁니다.

어댑터는 `response_format=json_schema`를 기본 사용합니다. 서버가 JSON 객체 모드만 지원하면 `QWEN_RESPONSE_FORMAT=json_object`로 명시적으로 바꿀 수 있습니다. 두 경우 모두 `choices[0].message.content`의 JSON을 기존 `AgentDraft`와 옷장 검사에 통과시켜야 합니다. 잘린 응답, Tool 호출, Markdown으로 감싼 JSON, 계약 위반은 실패로 처리합니다.

| API 상태 | 확인할 항목 |
| --- | --- |
| `422` | 기존 요청·Tool 인자 또는 모델로 보낼 컨텍스트의 크기 |
| `502` | 모델이 반환한 JSON, LOOK 계약, 옷장 검증 또는 서버의 요청 형식 지원 |
| `503` | 모델 서버 주소, 모델 ID, 인증, 서버 연결 상태 |
| `504` | 모델 서버 시간 초과 |

실패한 생성 결과는 추천 이력에 저장하지 않습니다. Mock으로 되돌릴 때는 `AGENT_INFERENCE_PROVIDER=mock`으로 백엔드를 재시작합니다.

## 모델 수령 후 실행

1. 진호에게서 학습 코드와 결과, 정확한 베이스 모델 ID·리비전, 학습에 쓴 tokenizer·chat template, LoRA 어댑터 또는 병합 가중치 링크, 실행 환경과 예시 입출력을 확인합니다. 저장소의 Qwen3.5 실험 문서는 베이스라인 기록이므로 최종 베이스 모델은 인계 자료에서 확인합니다. 가중치와 어댑터는 저장소 밖에 둡니다.
2. 전달받은 모델을 별도 포트의 로컬 또는 팀 모델 서버에 띄웁니다. 아래 예시는 수령한 모델의 형식을 확인한 뒤 사용합니다.

   - **vLLM로 병합 모델 실행**

     ```bash
     vllm serve "$CLOMORI_MERGED_MODEL_PATH" --served-model-name clomori-ft --host 127.0.0.1 --port 8001
     ```

   - **vLLM로 LoRA 어댑터 실행**. 해당 베이스 모델·버전에서 LoRA 및 학습 rank 지원을 확인합니다. 필요하면 학습 rank에 맞게 `--max-lora-rank`를 지정합니다.

     ```bash
     vllm serve "$CLOMORI_BASE_MODEL_PATH" --host 127.0.0.1 --port 8001 \
       --enable-lora --lora-modules "clomori-ft=$CLOMORI_ADAPTER_PATH"
     ```

     구조화 출력과 thinking 설정은 서버 버전·템플릿에 맞춥니다. `enable_thinking` 요청 옵션을 지원하는 vLLM에서는 `QWEN_SEND_CHAT_TEMPLATE_KWARGS=true`로 설정할 수 있습니다. [vLLM LoRA](https://docs.vllm.ai/en/stable/features/lora/) · [vLLM 구조화 출력](https://docs.vllm.ai/en/stable/features/structured_outputs/) · [Qwen 실행 가이드](https://qwen.readthedocs.io/en/stable/deployment/vllm.html#thinking-non-thinking-modes)

   - **Mac의 LM Studio**. 호환되는 병합 GGUF를 받은 경우 `lms import /path/to/clomori-ft.gguf --copy`로 가져와 모델을 로드하고 Developer 화면에서 로컬 서버를 시작합니다. 아래 주소 예시의 포트를 `1234`로 바꾸고 `QWEN_SEND_CHAT_TEMPLATE_KWARGS=false`를 사용합니다. 서버 또는 템플릿에서 thinking을 끄거나 최종 `content`와 분리하도록 설정합니다. [LM Studio 모델 가져오기](https://lmstudio.ai/docs/cli/local-models/import) · [LM Studio 구조화 출력](https://lmstudio.ai/docs/developer/openai-compat/structured-output)

3. 인증 없는 로컬 서버의 경우 `curl --fail http://127.0.0.1:8001/v1/models`로 모델 목록을 확인합니다. LoRA를 사용할 때는 `QWEN_MODEL`에 베이스 모델 ID 대신 목록에 뜨는 **학습된 어댑터 ID**를 지정합니다. 서버 인증을 켰다면 백엔드 쪽 로컬 설정에 `QWEN_API_KEY`를 입력합니다.
4. `backend` 디렉터리의 Python 환경에서 다음과 같이 백엔드를 시작합니다. 기존 DB·세션 설정은 그대로 사용하고, 모델 설정은 해당 프로세스에만 전달할 수 있습니다. 옵션 기본값은 [`backend/.env.example`](../backend/.env.example)에 있습니다.

   ```bash
   AGENT_INFERENCE_PROVIDER=qwen \
     QWEN_BASE_URL=http://127.0.0.1:8001/v1 \
     QWEN_MODEL=clomori-ft \
     python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

5. 별도 터미널에서 FR Worktree의 프론트 개발 서버를 실행하고 [http://localhost:5500](http://localhost:5500)에 접속합니다. 프론트 서버는 위 `8000` 포트의 백엔드에 연결합니다. 로컬 HTTP로 테스트할 때는 백엔드의 `SESSION_COOKIE_SECURE=false` 설정을 확인합니다.

   ```bash
   python3 "$HOME/Documents/ai-fashion-agent-FR/frontend/dev_server.py" --api-port 8000
   ```

6. 테스트 계정으로 가상 옷장을 만들고 먼저 `출근 코디 추천해줘`를 보냅니다. 5 LOOK과 `recommendation_id`, 옷장 사진 연결을 확인합니다. 이어 빈 옷장, 내 옷만 사용, 장소 되묻기, 날씨·일정이 필요한 요청, 피드백과 저장을 확인합니다. Qwen 서버를 중단했을 때 오류가 표시되고 새 추천이 저장되지 않는지도 확인합니다.
7. 화면의 추천 요청 제한은 90초입니다. 기본 모델 읽기 제한은 60초, 연결 제한은 최대 5초이며 외부 Tool 조회 시간은 별도입니다. 실제 장비에서 조회부터 추천 표시까지 걸리는 시간과 JSON 통과율을 측정한 뒤 설정을 조정합니다. `QWEN_MAX_INPUT_CHARS`는 문자 수 보호 한도입니다. 모델의 토큰 한도는 실행 환경에서 별도로 확인합니다.

모델 없이 어댑터를 다시 확인하려면 `backend`에서 다음을 실행합니다. 전체 백엔드 테스트에는 기본 스키마와 마이그레이션이 적용된 별도 PostgreSQL 테스트 DB가 필요합니다.

```bash
python -m pytest -q tests/test_qwen_inference.py
```
