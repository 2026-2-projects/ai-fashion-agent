# Qwen3.5-4B Baseline Demo
<br>

## 1. 실험 목적

Fashion AI Agent 개발을 위한 첫 단계로  
파인튜닝 전 `Qwen3.5-4B` 모델을 Google Colab에서 불러오고  
한국어 패션 추천이 정상적으로 생성되는지 확인하기 위함이다.

이 실험은 파인튜닝이 아닌 원본 모델의 Baseline 추론 테스트다.

---

## 2. 실행 환경

| 항목 | 내용 |
|---|---|
| 실행 환경 | Google Colab |
| GPU | NVIDIA Tesla T4 |
| GPU 메모리 | 14.56 GB |
| 모델 | `unsloth/Qwen3.5-4B` |
| 모델 클래스 | `Qwen3_5ForConditionalGeneration` |
| Processor | `Qwen3VLProcessor` |
| 모델 dtype | `torch.float16` |
| Framework | Unsloth |
| Unsloth | 2026.9.7 |
| Transformers | 5.2.0 |
| PyTorch | 2.8.0+cu128 |

#### 모델 로딩 후 GPU 사용량:
```text
GPU 실제 사용량: 8.46 GB
GPU 예약 메모리: 8.53 GB
GPU 전체 메모리: 14.56 GB
```

---

## 3. 모델 로딩 설정
```py
from unsloth import FastVisionModel

model, tokenizer = FastVisionModel.from_pretrained(
    model_name = "unsloth/Qwen3.5-4B",
    load_in_4bit = False,
    use_gradient_checkpointing = "unsloth",
)
```

#### 설정 이유 :
* Qwen3.5는 Unsloth에서 4-bit QLoRA를 권장하지 않는다.
* 첫 테스트에서는 16-bit 모델을 사용한다.
* T4 GPU에서 모델이 정상적으로 로딩되는지 먼저 확인한다.

---

## 4. 테스트 프롬프트  
```text
가을 저녁이고 기온은 15도야.  
비가 조금 올 예정이고, 소개팅에 갈 거야.  
미니멀한 남성 코디 한 가지를 추천해줘.
```

#### 생성 설정
```py
max_new_tokens=256
do_sample=False
enable_thinking=False
```

---

## 5. 모델 출력
```text
가을 저녁, 15도의 기온에 비가 조금 올 예정인 상황이라면,
방수성과 통기성을 모두 잡으면서도 미니멀한 스타일이 가장 적합합니다.

소개팅이라는 맥락을 고려하여, 깔끔하고 세련된 느낌을 주는
'단색 레이어링 코디'를 추천해 드립니다.

...
```

출력은 ```max_new_tokens=256``` 제한에 도달하여 문장 중간에서 종료됐다.

---

## 6. 확인 결과
*  -[X] Colab T4 GPU 연결
*  -[X] Unsloth 설치
*  -[X] Qwen3.5-4B 모델 로딩
*  -[X] GPU 추론 실행
*  -[X] 한국어 패션 추천 생성
*  -[ ] 완전한 추천 응답 생성
*  -[ ] 고정 JSON 출력 테스트
*  -[ ] Tool Calling 테스트
*  -[ ] 파인튜닝

---

## 7. 관찰 내용

### 정상 동작
* 한국어 요청을 이해했다.
* 계절, 기온, 비, 소개팅 상황을 답변에 반영했다.
* 미니멀 스타일에 맞는 코디 방향을 제안했다.

### 개선이 필요한 부분
* ```max_new_tokens=256```이 부족해 출력이 중간에 잘렸다.
* "안 겉옷" 과 같이 일부 표현이 어색했다.
* 요청한 것보다 답변이 길고 설명이 장황했다.
* 아직 프로젝트에서 요구하는 고정 JSON 형식을 적용하지 않았다.

### 경고 메시지
```torchaudio``` 및 deprecated API 관련 경고가 발생했지만
패션 텍스트 추론에는 영향을 주지 않았다.

---

## 8. 다음 단계
1. ```max_new_tokens```를 512 이상으로 변경한다.
2. 출력 길이를 제한한 프롬프트를 테스트한다.
3. 프로젝트에서 사용할 3 LOOK JSON 구조를 정의한다.
3. 원본 모델의 JSON 생성 성공 여부를 확인한다.
4. 패션 추천 평가용 Baseline 질문을 작성한다.
5. Tool Calling Baseline을 테스트한다.
6. 학습 데이터 형식을 설계한다.
7. LoRA 어댑터를 추가하고 파인튜닝을 진행한다.

---

## 9. 현재 결론

Qwen3.5-4B는 Tesla T4 환경에서 약 8.5GB의 GPU 메모리를 사용하여  
정상적으로 로딩됐으며, 기본적인 한국어 패션 추천도 생성할 수 있었다.  
  
다만 출력 길이 제어, 표현 품질, JSON 형식 준수 능력은 추가 평가가 필요하다.  
이 결과를 파인튜닝 전 Baseline으로 사용한다.
