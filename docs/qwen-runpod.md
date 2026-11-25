# CLOMORI Runpod 모델 서버 실행 절차

## STEP 26-D · 모델과 서빙 환경

2026-11-25에 확인한 배포 후보는 공식 `vllm/vllm-openai:v0.34.0`이다. 다중 아키텍처 이미지 digest는 `sha256:20fdb089454afbb324efa4110a2c025ff7b27cc1a086e07aa580b18df8ad1ce1`이다. 릴리스 소스 기준 CUDA 13.0.3, PyTorch 2.14.0, Transformers 5.16.1 이상 5.23 미만, XGrammar 0.2.8이다. Runpod에서는 CUDA 13 호환 NVIDIA 드라이버(R580 이상)가 있는 호스트를 선택하고 이미지 안의 실제 패키지 버전을 기록한다. 아래 명령은 구문과 공개 소스를 확인한 배포 후보이며, 실제 Pod 기동 검증은 결제 후 진행한다. [릴리스](https://github.com/vllm-project/vllm/releases/tag/v0.34.0) · [이미지 digest](https://hub.docker.com/v2/repositories/vllm/vllm-openai/tags/v0.34.0) · [CUDA 요구 사항](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/index.html) · [버전 제약](https://github.com/vllm-project/vllm/blob/v0.34.0/requirements/common.txt)

| 저장소 | 이번에 고정한 Hugging Face revision | 확인 결과 |
|---|---|---|
| `unsloth/Qwen3.5-4B` | `3764fa359b9082ea5a1e4a5e3ac3aaf6e9671636` | 전체 체크포인트의 두 safetensors 합계 9.32 GB. 모델 클래스는 `Qwen3_5ForConditionalGeneration`. |
| `hhoyaa/qwen35-fashion-864-lora-v2` | `708b6598bcf7bf66f809c9c7efd503581fcce4d9` | 어댑터 84,972,248바이트. 설정의 base revision이 null이어서 학습 당시의 base SHA는 별도 확인 대상. |

**직접 확인.** 원본 safetensors 헤더에는 언어부 128개 모듈의 A/B 가중치 256개가 있다. q/k/v/o는 전체 어텐션 8개 층, gate/up/down은 32개 MLP 층에 대응한다. 저장 dtype은 모두 F32이고 랭크는 16이다. 모델 카드의 FP16은 학습 시 연산 정밀도를 가리킨다. M4에서 PyTorch 2.14.0, Transformers 5.22.2, PEFT 0.21.2, Accelerate 1.16.0으로 원본 설정의 전체 모델 구조를 `meta` 장치에 생성하고 원본 정규표현식을 적용했다. PEFT가 만든 256개 키와 차원이 헤더와 모두 일치했다(21,233,664개 파라미터). 이 시험 범위는 구조와 차원이다. [베이스 파일](https://huggingface.co/unsloth/Qwen3.5-4B/tree/3764fa359b9082ea5a1e4a5e3ac3aaf6e9671636) · [어댑터 파일](https://huggingface.co/hhoyaa/qwen35-fashion-864-lora-v2/tree/708b6598bcf7bf66f809c9c7efd503581fcce4d9) · [PEFT LoRA](https://huggingface.co/docs/peft/en/package_reference/lora)

**로딩 판단.** Transformers 5.22.2의 `AutoModelForCausalLM`은 이 config에서 텍스트 전용 `Qwen3_5ForCausalLM`을 선택한다. 인계된 전체 모델 및 어댑터의 모듈 경로를 재현할 때는 `Qwen3_5ForConditionalGeneration.from_pretrained(...)` 또는 이에 대응하는 `AutoModelForImageTextToText`를 사용한다. vLLM은 Qwen3.5 언어부 LoRA를 지원한다. 0.34.0의 PEFT 설정은 문자열 target_modules를 허용하고 로더는 실제 safetensors 키를 검사한다. NVIDIA 구현의 packed qkv/gate-up 매핑과 실제 텐서 종류가 부합한다. 원본 어댑터를 정적으로 로딩하는 방식을 우선 시험한다. 이 조합의 GPU 부팅, 첫 추론 및 지연은 별도 검증 대상이다. [Transformers 매핑](https://github.com/huggingface/transformers/blob/v5.22.2/src/transformers/models/auto/modeling_auto.py) · [모델 지원표](https://docs.vllm.ai/en/stable/models/supported_models/) · [NVIDIA Qwen3.5](https://github.com/vllm-project/vllm/blob/v0.34.0/vllm/models/qwen3_5/nvidia/model.py) · [LoRA 설정](https://github.com/vllm-project/vllm/blob/v0.34.0/vllm/lora/peft_helper.py) · [가중치 검사](https://github.com/vllm-project/vllm/blob/v0.34.0/vllm/lora/lora_model.py)

**Structured Output 로컬 시험.** 고정 어댑터 토크나이저와 모델 vocab 크기 248,320으로 vLLM 이미지와 같은 XGrammar 0.2.8에서 배포 코드의 전체 5 LOOK JSON Schema를 컴파일했다. 토큰 단위로 정상 5 LOOK(150토큰)의 종료를 허용했고 role 범위 밖인 값과 잘린 JSON의 종료를 거부했다. 필수 의류가 없는 사용자용 Schema도 같은 방식으로 컴파일했다. 정상 2건은 통과했고 LOOK 4/5의 상태·아이템·스타일이 잘못된 6건은 거부됐다. 한 요청 안의 중복 슬롯, 실제 소유 ID, 추천 품질은 백엔드와 실모델로 별도 검증한다.

### GPU와 비용

Runpod Pods 공개 가격표를 이용한 USD 예산이다. 콘솔의 지역·재고·Cloud 유형별 최종 견적을 선택 시점에 확인한다. 8시간은 다운로드·초기화·대기를 포함한 Pod 실행 시간이다. [Runpod GPU 가격](https://www.runpod.io/pricing)

| GPU | VRAM | 시간당 | 8시간 GPU 비용 | 선택 기준 |
|---|---:|---:|---:|---|
| RTX A5000 | 24 GB | $0.27 | $2.16 | 1요청씩 저비용으로 리허설 |
| A40 | 48 GB | $0.59 | $4.72 | 첫 배포 권장. GPU 메모리와 호스트 RAM에 여유 |
| L4 | 24 GB | $0.69 | $5.52 | A5000/A40 재고 부족 시 후보 |
| RTX 4090 | 24 GB | $0.89 | $7.12 | 지연이 병목일 때 같은 입력으로 실측 |

전체 베이스 가중치는 약 8.68 GiB이고 KV 캐시, Gated DeltaNet 상태, CUDA 작업공간, 런타임이 추가된다. **24 GB, 동시 요청 1개, 서버 문맥 8,192**는 시작 견적이다. 학습 길이는 4,096이므로 이 범위를 넘는 입력 품질도 별도로 측정한다. 출력 1,600을 예약하면 8,192 서버에는 템플릿 포함 입력이 6,592토큰 이하로 들어가야 한다. 한국어 문자 수 제한과 토큰 수는 다르다. 메모리·처리량 최솟값은 GPU 실측 대상이다. 컨테이너 디스크 40 GB와 `/workspace` 볼륨 50 GB를 시작점으로 잡으면 베이스·어댑터와 추가 병합본 약 9 GB를 보관할 수 있다.

컨테이너 및 실행 중 볼륨 디스크는 각각 $0.10/GB·월, 정지한 Pod의 볼륨은 $0.20/GB·월이다. 30일을 가정하면 위 90 GB 실행 저장소는 8시간 약 $0.10로, A40 8시간 합계는 약 $4.82다. 정지 후 50 GB 볼륨은 하루 약 $0.33이다. 120시간 연속 사용 시 A40의 GPU 비용만 $70.80이다. $70 예산에서는 리허설·발표 시간에 맞춰 시작하고 끝나면 정지한다. Auto-Pay를 비활성화하고 중지 뒤에도 남는 볼륨 요금을 잔액에 포함한다. Railway Hobby는 월 최소 $5에 사용량 $5를 포함하고 이를 초과하는 리소스는 추가 과금한다. [Railway 가격](https://railway.com/pricing) [Runpod 청구 기준](https://github.com/runpod/docs/blob/main/accounts-billing/billing.mdx)

## STEP 26-F · 결제 승인 후 Runpod에서 실행

1. 단일 GPU Pod에 이미지 참조 `vllm/vllm-openai:v0.34.0@sha256:20fdb089454afbb324efa4110a2c025ff7b27cc1a086e07aa580b18df8ad1ce1`, CUDA 13 호환 호스트, `/workspace` 볼륨을 지정한다. 외부 HTTP 포트는 `8000/http` 하나다. Runpod Secret으로 **서비스 전용** `VLLM_API_KEY`를 주입하고 Railway의 `QWEN_API_KEY`에 같은 값을 넣는다. Runpod 계정 키와 구분한다. 콘솔의 Container start command에는 아래 JSON을 입력해 공식 이미지의 `vllm serve` 기본 ENTRYPOINT를 재정의한다. 첫 실행에 Pod Web Terminal로 아래 두 파일을 준비하면 이후 같은 볼륨으로 시작할 때 자동 실행된다. [Runpod 시작 명령 구조](https://docs.runpod.io/api-reference-v2/pods/create-a-pod) · [공식 이미지](https://github.com/vllm-project/vllm/blob/v0.34.0/docker/Dockerfile)

```json
{"entrypoint":["/bin/bash","-c"],"cmd":["until [ -f /workspace/clomori/start.sh ]; do sleep 2; done; exec /bin/bash /workspace/clomori/start.sh"]}
```

2. Pod 터미널에서 외부에 허용할 경로를 설정한다. vLLM Bearer 인증이 적용되는 `GET /v1/models`, `POST /v1/chat/completions`만 연다. 같은 포트에 있는 별도의 인증 없는 관리·추론 경로는 공개할 필요가 없다. [vLLM 인증 범위](https://github.com/vllm-project/vllm/blob/v0.34.0/docs/usage/security.md) · [미들웨어 등록 방식](https://github.com/vllm-project/vllm/blob/v0.34.0/vllm/entrypoints/serve/middleware/register.py)

```bash
mkdir -p /workspace/clomori
cd /workspace/clomori
cat > clomori_routes.py <<'PY'
from starlette.responses import Response

class DemoRoutes:
    paths = {("GET", "/v1/models"), ("POST", "/v1/chat/completions")}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] == "http" and (scope["method"], scope["path"]) not in self.paths:
            await Response(status_code=404)(scope, receive, send)
            return
        await self.app(scope, receive, send)
PY
```

3. 같은 터미널에서 시작 스크립트를 작성한다. 임시 파일에 쓴 뒤 이동하면 Pod가 완성된 스크립트로 시작한다. 내려받는 두 저장소는 공개다. [vLLM 정적 LoRA](https://docs.vllm.ai/en/stable/features/lora/) · [OpenAI 호환 Structured Outputs](https://docs.vllm.ai/en/stable/features/structured_outputs/)

```bash
cd /workspace/clomori
cat > start.sh.new <<'SH'
set -eu
: "${VLLM_API_KEY:?Runpod Secret VLLM_API_KEY must be set}"
cd /workspace/clomori
export HF_HOME=/workspace/hf-cache
export PYTHONPATH="/workspace/clomori${PYTHONPATH:+:$PYTHONPATH}"
export VLLM_ALLOW_RUNTIME_LORA_UPDATING=0
base=/workspace/clomori/base-3764fa3
adapter=/workspace/clomori/adapter-708b659
hf download unsloth/Qwen3.5-4B --revision 3764fa359b9082ea5a1e4a5e3ac3aaf6e9671636 --local-dir "$base"
hf download hhoyaa/qwen35-fashion-864-lora-v2 --revision 708b6598bcf7bf66f809c9c7efd503581fcce4d9 --local-dir "$adapter"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
python -c 'from importlib.metadata import version; print({k: version(k) for k in ("vllm","torch","transformers","xgrammar")})'
exec vllm serve "$base" --served-model-name clomori-base \
  --tokenizer "$adapter" --chat-template "$adapter/chat_template.jinja" \
  --chat-template-content-format string --default-chat-template-kwargs '{"enable_thinking":false}' \
  --language-model-only --dtype half --max-model-len 8192 --max-num-seqs 1 \
  --enable-lora --max-lora-rank 16 --lora-dtype float16 \
  --lora-modules "clomori-fashion-v2=$adapter" \
  --host 0.0.0.0 --port 8000 --middleware clomori_routes.DemoRoutes
SH
mv start.sh.new start.sh
```

4. 외부 HTTPS 프록시에서 인증 없는 `GET /v1/models`는 401, 올바른 키는 200, 노출하지 않은 경로는 404인지 확인한다. 공용 HTTPS 주소는 `https://<POD_ID>-8000.proxy.runpod.net`이다. 모델 목록에 **clomori-fashion-v2**가 있어야 한다. Railway에는 `QWEN_BASE_URL=https://<POD_ID>-8000.proxy.runpod.net/v1`, `QWEN_MODEL=clomori-fashion-v2`를 넣는다. 로컬 CLI 점검 시에는 전용 키를 환경변수로 주입하고 셸 추적을 끈다. [Runpod HTTPS 포트](https://docs.runpod.io/pods/configuration/expose-ports)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$QWEN_BASE_URL/models"
curl -fsS -H "Authorization: Bearer $QWEN_API_KEY" "$QWEN_BASE_URL/models"
curl -sS -o /dev/null -w '%{http_code}\n' "${QWEN_BASE_URL%/v1}/metrics"
```

5. 모델 서버를 사용할 수 있는 컴퓨터에서 저장소 루트로 이동해 아래 검사를 실행한다. `QWEN_API_KEY`는 위에서 준비한 전용 비밀 값, `QWEN_BASE_URL`은 해당 Pod의 HTTPS 주소다. Python 인터프리터에는 프로젝트 `backend/requirements.txt`를 설치한다. 셸에서 `QWEN_BASE_URL`과 `QWEN_API_KEY`를 export한 후 실행한다. 이 명령은 합성 Tool 데이터만 전송하며 응답의 옷 이름·이유를 출력한다. 일반·옷장 5건과 비선호 색 대조 2건이 기대 상태·상의 ID를 모두 만족하면 종료 코드 0, 일부 실패는 1, 설정 누락은 2다.

```bash
AGENT_INFERENCE_PROVIDER=qwen QWEN_MODEL=clomori-fashion-v2 PYTHONPATH=backend \
  python scripts/quality/smoke_qwen.py
```

6. 외부에서 서비스가 실제로 보내는 FR 메시지·JSON Schema를 사용해 합성 요청을 보낸다. 응답의 `model`, `finish_reason`, 입력·출력 토큰, 종단 지연, 정상 5 LOOK 비율과 unavailable/옷장 ID 오류 건수를 기록한다. 1,400과 1,600을 먼저 비교하고, 잘리면 메시지 길이와 실제 출력 토큰을 함께 확인한다. `temperature=0.35`, `top_p=0.9`, `repetition_penalty=1.08`, thinking off, `stream=false`, `response_format.type=json_schema`가 출발값이다. FR에는 TC 전용 stop을 쓰지 않는다. 비·일정·비선호 조건 반영은 반환된 이유·아이템을 검토한다. 비스트리밍 Runpod HTTPS 프록시의 한도는 100초다. 초기 타임아웃 60초와 실측 여유 시간을 비교하고, 90초 내에도 반복 지연되면 입력/출력 길이와 GPU를 조정한다. 합격 후에 Railway에서 Qwen provider를 켠다.

### 정적 LoRA 로딩이 실패할 때

부팅 또는 실제 adapter 요청에서 unsupported module, key/shape mismatch, dtype 오류가 나면 SHA·rank·이미지 digest와 모델 ID를 대조한다. 고정 체크포인트를 사용해 CPU RAM 32 GB 이상을 확보한 별도 병합 환경에서 아래 코드를 실행할 수 있다. 작업용 Python 버전 제안은 `torch==2.14.0 transformers==5.22.2 peft==0.21.2 accelerate==1.16.0`이다. 정상 원본과 별개인 새 경로에 쓴다. `safe_merge`의 수치 검사와 서비스 입력에 대한 품질 검증은 각각 필요하다. [PEFT merge_and_unload](https://huggingface.co/docs/peft/en/package_reference/peft_model)

```python
from pathlib import Path
from shutil import copy2
import torch
from transformers import Qwen3_5ForConditionalGeneration
from peft import PeftModel

root = Path("/workspace/clomori")
base_dir, adapter_dir = root / "base-3764fa3", root / "adapter-708b659"
output = root / "merged-3764fa3-708b659"
output.mkdir(exist_ok=False)
base = Qwen3_5ForConditionalGeneration.from_pretrained(base_dir, dtype=torch.float16)
adapted = PeftModel.from_pretrained(base, adapter_dir).eval()
adapted.merge_and_unload(safe_merge=True).save_pretrained(output)
for name in ("preprocessor_config.json", "video_preprocessor_config.json"):
    if (base_dir / name).exists():
        copy2(base_dir / name, output / name)
for name in ("chat_template.jinja", "tokenizer.json", "tokenizer_config.json", "processor_config.json"):
    copy2(adapter_dir / name, output / name)
```

병합 모델은 위 서빙 명령의 `"$base"`를 새 출력 경로로, `--served-model-name`을 `clomori-fashion-v2`로 바꾸고 `--enable-lora`, `--max-lora-rank`, `--lora-dtype`, `--lora-modules` 네 옵션을 제거한다. 고정 토크나이저·템플릿·인증·경로 설정은 동일하게 사용한다. 사본이 약 9 GB 추가되고 어댑터별 교체는 새 병합을 거친다. 배포 전 동일 입력의 greedy 생성과 5 LOOK 검증, 응답 지연을 기준으로 PEFT 원본과 비교한다.
