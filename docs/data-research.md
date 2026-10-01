# 3.1 공개 패션·Tool Calling 데이터 조사

## 1. 조사 목적

AI 기반 개인 맞춤형 패션 에이전트의 Fashion SLM 학습을 위해 활용 가능한 공개 패션 데이터셋과 Tool Calling 데이터셋을 조사한다.

조사 기준은 다음과 같다.

- 패션 추천 학습에 활용 가능한지
- 의류 카테고리, 색상, 스타일, 코디 관계 등의 정보가 포함되어 있는지
- Tool Calling 학습에 활용 가능한 구조인지
- 라이선스와 재배포 조건이 명확한지
- 본 프로젝트의 Qwen3-4B 기반 QLoRA 파인튜닝에 적용 가능한지

본 프로젝트에서는 공개 데이터를 그대로 대량 학습하기보다는, 공개 데이터의 구조와 패턴을 참고하고 프로젝트 전용 Gold Data와 Synthetic Data를 별도로 구축하는 방향을 우선한다.

---

# 2. 공개 패션 데이터셋 조사

## 2.1 조사 결과

| 데이터셋 | 출처 | 규모 / 특징 | 이용 조건 | 우리 프로젝트 활용 | 판단 |
|---|---|---|---|---|---|
| Polyvore Outfits | Hugging Face | 68,306개 Outfit, 261,058개 패션 아이템. Fashion Compatibility 및 Outfit Recommendation 용도로 구성 | CC BY 4.0. 현재 Hugging Face 페이지에서는 접근 요청이 필요하며 연구·교육 목적 및 이미지 권리 조건을 추가 확인해야 함 | 상의·하의·신발 등 아이템 간 조합 관계와 코디 구성 방식 참고 | 조건부 활용 |
| 패션상품 및 착용 영상 | AI Hub | 패션상품 대표 이미지 40,036장, 패션상품-착용영상 Pair 117,270건 등 | AI Hub 이용정책 준수 필요 | 국내 패션 상품 카테고리, 상품-착용 관계 참고 | 활용 후보 |
| 의류 통합 데이터 | AI Hub | 총 550,634장. 의류 이미지, 착용 이미지, 치수, 신체정보, 원단정보 등 포함 | AI Hub 이용정책 및 신청 필요 | 국내 의류 종류와 속성 체계 참고 | 참고용 |
| Fashion Stylist Multimodal v2 | Hugging Face | 1,000 Rows, 26 Columns. Style Preference, Recommended Colors, Top, Bottom, Shoes, Accessory 등 포함 | MIT | Gold/Synthetic Data의 구조 및 패션 추천 필드 설계 참고 | 적극 참고 |
| Fashionpedia | Fashionpedia | 48,825장. 27개 주요 의류 카테고리, 19개 의류 파트, 294개 세부 속성 포함 | Annotation 및 Ontology는 CC BY 4.0. 원본 이미지는 각 이미지 제공처의 라이선스 적용 | 의류 카테고리와 세부 Attribute 체계 참고 | 보류 |
| DeepFashion2 | 공식 GitHub | 약 491K 이미지, 13개 의류 카테고리, 약 801K Clothing Items. Detection, Segmentation, Re-ID 중심 | 데이터 다운로드 신청 필요 | 이미지 인식 및 의류 분류에는 적합하나 현재 텍스트 중심 Fashion SLM에는 활용도가 낮음 | 제외 / 보류 |

---

## 2.2 Polyvore Outfits

Polyvore Outfits는 패션 아이템 간 Compatibility와 Outfit Recommendation 연구를 위해 구성된 대표적인 패션 데이터셋이다.

주요 특징은 다음과 같다.

- 68,306개의 Outfit
- 261,058개의 Fashion Item
- Category Label
- Item Description
- Outfit Grouping
- Fashion Compatibility Prediction
- Outfit Recommendation
- Fill-In-The-Blank Evaluation

본 프로젝트에서는 이미지 자체를 학습시키는 것보다 다음과 같은 관계를 참고하는 데 활용할 수 있다.

```text
상의
+
하의
+
신발
+
아우터
↓
하나의 코디 구성
```

즉, 어떤 종류의 아이템들이 하나의 Outfit으로 함께 구성되는지 참고할 수 있다.

단, 데이터셋은 CC BY 4.0으로 제공되지만 현재 Hugging Face 페이지에서는 접근 요청 절차와 연구·교육 목적 관련 안내가 존재하므로 실제 데이터를 사용할 경우 조건을 다시 확인한다.

참고:
https://huggingface.co/datasets/mvasil/polyvore-outfits

---

## 2.3 AI Hub - 패션상품 및 착용 영상

AI Hub의 패션상품 및 착용 영상 데이터셋은 패션상품 이미지와 실제 착용 이미지 또는 영상 간의 관계를 포함한다.

주요 데이터는 다음과 같다.

- 패션 상품 대표 사진: 40,036장
- 패션상품 및 패션영상 Pair: 117,270건
- 상품 Keypoint
- Model Pose
- Semantic 영역
- Wearing Information

상품 단독 데이터와 실제 착용 상태가 연결되어 있기 때문에 국내 패션 상품의 카테고리와 착용 관계를 참고하기에 유용하다.

본 프로젝트에서는 다음 용도로 참고할 수 있다.

```text
상품 카테고리
상품 종류
착용 상태
상품 간 관계
```

다만 본 프로젝트는 이미지 생성이나 Virtual Try-On이 목적이 아니므로 전체 데이터를 직접 활용하기보다는 의류 분류 및 관계 구조를 참고하는 방향이 적합하다.

참고:
https://www.aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&currMenu=116&dataSetSn=78

---

## 2.4 AI Hub - 의류 통합 데이터

의류 통합 데이터는 의류 이미지와 다음 정보를 연결한 데이터셋이다.

- 의류 이미지
- 착용 이미지
- 치수 데이터
- 착용자의 신체 정보
- 원단 정보

총 구축량은 550,634장이다.

주요 의류 분류에는 다음과 같은 항목이 포함된다.

```text
blouse
cardigan
coat
jacket
jumper
shirt
sweater
t-shirt
vest
bottom
dress
jumpsuit
```

본 프로젝트에서는 다음 용도로 참고할 수 있다.

- Wardrobe Item Category 설계
- 의류 Type 정의
- 의류 속성 체계 참고
- 국내 패션 데이터 구조 참고

하지만 이 데이터는 가상 피팅 및 의류 이미지 분석 목적에 더 가깝기 때문에 Fashion Recommendation 학습의 직접적인 핵심 데이터로 사용하기보다는 참고용으로 활용한다.

참고:
https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71501

---

## 2.5 Fashion Stylist Multimodal v2

Fashion Stylist Multimodal v2는 Fashion Recommendation을 위한 Synthetic Dataset이다.

주요 특징은 다음과 같다.

- 1,000 Rows
- 26 Columns
- MIT License
- Synthetic Data

주요 필드는 다음과 같다.

```text
gender
age_group
style_preference
recommended_colors
primary_color
secondary_color
outfit_description
outfit_top
outfit_bottom
outfit_shoes
outfit_accessory
```

우리 프로젝트에서 사용할 데이터 구조와 상당히 유사하다.

예를 들어 다음과 같은 구조를 참고할 수 있다.

```text
User Profile
+
Style Preference
+
Color Preference
↓
Outfit Recommendation
```

하지만 해당 데이터는 Synthetic Data이므로 사람이 직접 작성·검증한 Gold Data로 취급하지 않는다.

본 프로젝트에서는 다음 용도로 적극 활용한다.

- Gold Data JSON 구조 설계 참고
- Synthetic Data 필드 설계 참고
- Fashion Recommendation Output 구조 참고

참고:
https://huggingface.co/datasets/lihicarmeli/fashion-stylist-multimodal-v2

---

## 2.6 Fashionpedia

Fashionpedia는 Fashion Computer Vision 연구를 위한 데이터셋이다.

주요 구성은 다음과 같다.

- 48,825개의 의류 이미지
- 27개 Main Apparel Category
- 19개 Apparel Part
- 294개 Fine-grained Attribute
- Segmentation Mask
- Attribute Annotation
- Fashion Ontology

Annotation과 Ontology는 CC BY 4.0으로 제공되지만, 원본 이미지의 저작권은 Fashionpedia가 소유하지 않는다.

따라서 이미지를 직접 학습 데이터로 활용할 경우 각 이미지 제공처의 이용 조건을 따로 확인해야 한다.

본 프로젝트에서는 이미지 자체보다 다음과 같은 의류 Attribute 체계를 참고할 수 있다.

```text
Category
Attribute
Garment Part
Style Property
```

현재 프로젝트는 텍스트 기반 Fashion SLM이 핵심이므로 우선순위는 낮게 설정한다.

참고:
https://fashionpedia.github.io/

---

## 2.7 DeepFashion2

DeepFashion2는 대규모 Fashion Computer Vision Dataset이다.

주요 특징은 다음과 같다.

- 약 491K Images
- 약 801K Clothing Items
- 13개 Clothing Category
- Bounding Box
- Landmark
- Mask
- Category
- Style
- Commercial / Consumer Image Pair

주요 목적은 다음과 같다.

```text
Clothing Detection
Segmentation
Pose / Landmark
Retrieval
Re-Identification
```

본 프로젝트는 이미지 분석보다 자연어 기반 패션 추천과 Tool Calling이 핵심이므로 직접적인 활용도는 낮다.

추후 사용자의 옷 사진을 자동 분류하는 기능 등을 확장할 경우 활용 가능성이 있지만 현재 범위에서는 제외 또는 보류한다.

참고:
https://github.com/switchablenorms/DeepFashion2

---

# 3. Tool Calling 공개 데이터셋 조사

Fashion SLM은 패션 추천뿐 아니라 사용자 요청에 따라 필요한 Tool을 선택하여 호출해야 한다.

따라서 공개 Function Calling / Tool Calling Dataset도 함께 조사하였다.

## 3.1 조사 결과

| 데이터셋 | 규모 | 라이선스 | 특징 | 우리 프로젝트 활용 |
|---|---:|---|---|---|
| glaive-function-calling-v2-ko | 약 15.2K | Apache-2.0 | Glaive Function Calling 데이터를 한국어로 변환 | 한국어 Tool Calling 형식 참고 |
| xLAM Function Calling 60K | 60K | CC BY 4.0 | 실제 Function Execution 및 검증 과정이 포함된 고품질 Synthetic Dataset | Tool Call 구조와 검증 방식 참고 |
| Hermes Function Calling v1 | 10K 이상 규모 | Apache-2.0 | Single/Multi Function Call, JSON Mode, Agentic Structured Output 포함 | JSON 및 Multi-Tool 구조 참고 |
| Glaive Function Calling v2 | 113K | Apache-2.0 | 다양한 Function Calling 대화 예제 포함 | 일반 Tool Calling 패턴 참고 |

---

## 3.2 glaive-function-calling-v2-ko

glaive-function-calling-v2-ko는 Glaive Function Calling Dataset을 한국어로 변환한 데이터셋이다.

약 15.2K개의 데이터를 포함하며 Apache-2.0 License로 제공된다.

주요 구조는 다음과 같다.

```text
System Message
Function Description
User Request
Assistant Tool Call
Tool Result
Assistant Final Response
```

한국어 사용자의 자연어 요청을 어떤 식으로 Tool Calling 형태로 변환하는지 참고하기에 적합하다.

예:

```text
사용자 요청
↓
필요한 함수 판단
↓
함수 이름 및 Argument 생성
```

본 프로젝트에서는 한국어 Tool Calling Gold Data를 만들 때 참고 자료로 활용한다.

참고:
https://huggingface.co/datasets/heegyu/glaive-function-calling-v2-ko

---

## 3.3 xLAM Function Calling 60K

xLAM Function Calling 60K는 Salesforce AI Research의 Function Calling Dataset이다.

주요 특징은 다음과 같다.

- 60,000개의 Function Calling Data
- CC BY 4.0
- Synthetic Data
- Function Format Validation
- 실제 Function Execution
- Semantic Verification

데이터 생성 후 단순히 형식만 검사하는 것이 아니라 실제 함수 실행과 의미 검증까지 수행한다는 점이 특징이다.

본 프로젝트에서는 다음을 참고할 수 있다.

```text
Tool 이름 검증
Argument 형식 검증
Tool 실행 결과 검증
잘못된 호출 제거
```

특히 HITL 검증 단계에서 Tool Calling Data를 어떤 기준으로 검수해야 하는지 참고할 수 있다.

참고:
https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k

---

## 3.4 Hermes Function Calling v1

Hermes Function Calling v1은 Structured Output 및 Function Calling 학습을 위한 데이터셋이다.

Apache-2.0 License로 제공된다.

다음 유형의 데이터가 포함된다.

```text
Single Function Calling
Multiple Function Calling
JSON Mode
Agentic JSON Mode
Structured Extraction
```

본 프로젝트에서는 하나의 Tool만 호출하는 경우뿐 아니라 여러 Tool을 연속해서 호출하는 경우의 구조를 참고할 수 있다.

예:

```text
get_calendar_events()
↓
일정에서 장소 확인
↓
get_weather()
↓
최종 코디 추천
```

이와 같이 Multi-Tool Calling 흐름을 구성하는 데 참고하기 적합하다.

참고:
https://huggingface.co/datasets/NousResearch/hermes-function-calling-v1

---

## 3.5 Glaive Function Calling v2

Glaive Function Calling v2는 대규모 Function Calling Dataset이다.

주요 특징은 다음과 같다.

- 약 113K Rows
- Apache-2.0 License
- 다양한 API 및 Function Calling Scenario 포함

예를 들어 다음과 같은 일반적인 Function들이 존재한다.

```text
get_exchange_rate()
search_flight()
weather API
database query
```

하지만 이러한 Function들은 본 프로젝트에서 사용하는 Tool과 직접적으로 일치하지 않는다.

따라서 전체 데이터를 그대로 학습시키기보다는 Tool Calling의 구조와 패턴을 참고하는 용도로 활용한다.

참고:
https://huggingface.co/datasets/glaiveai/glaive-function-calling-v2

---

# 4. 우리 프로젝트에서의 활용 방향

## 4.1 패션 데이터

공개 패션 데이터는 다음과 같이 활용한다.

```text
Polyvore Outfits
→ 아이템 조합 관계와 Outfit 구성 방식 참고

AI Hub 패션상품 및 착용 영상
→ 국내 패션 상품 카테고리와 착용 관계 참고

AI Hub 의류 통합 데이터
→ 의류 종류 및 Attribute 구조 참고

Fashion Stylist Multimodal v2
→ Gold/Synthetic Data JSON 구조 참고

Fashionpedia
→ 세부 의류 Attribute 체계 참고

DeepFashion2
→ 현재는 제외, 추후 이미지 인식 기능 확장 시 검토
```

---

## 4.2 Tool Calling 데이터

Tool Calling 공개 데이터는 다음과 같이 활용한다.

```text
glaive-function-calling-v2-ko
→ 한국어 Tool Calling 형식 참고

xLAM Function Calling 60K
→ 고품질 Tool Call 및 검증 방식 참고

Hermes Function Calling v1
→ Multi-Tool Calling 및 JSON 구조 참고

Glaive Function Calling v2
→ 일반적인 Function Calling Pattern 참고
```

---

# 5. 프로젝트 전용 Tool

본 프로젝트에서 Fashion Agent가 사용할 Tool은 다음 4개로 제한한다.

```text
get_user_context()
get_wardrobe()
get_weather()
get_calendar_events()
```

각 Tool의 역할은 다음과 같다.

### get_user_context()

사용자의 프로필과 패션 취향 정보를 조회한다.

예:

```text
preferred_styles
preferred_colors
disliked_colors
preferred_fit
profile
feedback_summary
```

---

### get_wardrobe()

사용자가 등록한 옷장 정보를 조회한다.

예:

```text
category
item_type
color
fit
season
image
item_id
```

---

### get_weather()

특정 날짜와 장소의 날씨 정보를 조회한다.

예:

```text
temperature
sky
precipitation
wind
humidity
```

---

### get_calendar_events()

Google Calendar에서 사용자의 일정을 조회한다.

예:

```text
date
time
place
event summary
```

---

# 6. 공개 Tool Calling 데이터를 그대로 학습하지 않는 이유

공개 Function Calling Dataset에는 본 프로젝트와 관련 없는 Function들이 다수 포함되어 있다.

예:

```text
book_flight()
send_email()
get_exchange_rate()
search_hotel()
```

이러한 Function을 대량으로 학습시키면 프로젝트에서 실제로 사용하지 않는 Tool을 호출하려는 패턴이 학습될 가능성이 있다.

따라서 공개 데이터는 다음 목적으로만 사용한다.

```text
Tool Calling 구조 참고
JSON 형식 참고
Argument 설계 참고
Multi-Tool Calling 흐름 참고
검증 방식 참고
```

실제 Fine-Tuning의 핵심 Tool Calling Data는 프로젝트의 4개 Tool에 맞춰 직접 제작한다.

---

# 7. 최종 학습 데이터 구성 방향

본 프로젝트의 최종 학습 데이터는 크게 두 종류로 구성한다.

```text
1. Fashion Recommendation Data
2. Tool Calling Data
```

---

## 7.1 Fashion Recommendation Data

Fashion Recommendation Data는 사용자의 조건에 따라 적절한 코디를 추천하는 방법을 학습시키기 위한 데이터이다.

예:

```text
사용자 요청
+
프로필
+
패션 취향
+
날씨
+
일정
+
보유 의류
↓
LOOK 1
LOOK 2
LOOK 3
```

학습해야 할 주요 요소는 다음과 같다.

```text
계절
날씨
TPO
스타일
색상
핏
프로필
패션 취향
보유 의류
```

---

## 7.2 Tool Calling Data

Tool Calling Data는 사용자 요청을 분석하여 어떤 Tool이 필요한지 판단하는 방법을 학습시키기 위한 데이터이다.

예:

```text
사용자:
"내일 일정 보고 코디 추천해줘"

↓ Agent 판단

get_calendar_events()

↓ 일정 장소 확인

get_weather()

↓ Context 구성

Fashion Recommendation
```

---

# 8. Gold Data 및 Synthetic Data 구축 계획

공개 데이터만으로 본 프로젝트의 정확한 요구사항을 충족하기 어렵기 때문에 프로젝트 전용 데이터를 별도로 구축한다.

예상 구성은 다음과 같다.

```text
공개 데이터 조사 및 참고
        +
Gold Data 약 80개
        +
Synthetic Data 약 800개
        ↓
HITL 검증
        ↓
최종 학습 데이터
```

Gold Data는 팀원이 직접 작성하고 검증한 고품질 데이터로 구성한다.

Synthetic Data는 Gold Data를 기준으로 다음 요소를 변경하여 생성한다.

```text
계절
날씨
TPO
지역
스타일
색상
핏
보유 의류 사용 여부
Calendar 사용 여부
Tool Calling 조합
```

---

# 9. HITL 검증

Synthetic Data는 생성 후 그대로 학습에 사용하지 않는다.

팀원이 직접 일부 데이터를 교차 검증하여 잘못된 데이터를 수정 또는 제거한다.

검증 항목 예시는 다음과 같다.

### 패션 추천 검증

```text
날씨와 맞지 않는 옷 추천 여부
사용자 취향 반영 여부
TPO 적합성
색상 조합
핏 적합성
```

### Tool Calling 검증

```text
불필요한 Tool 호출 여부
필요한 Tool 누락 여부
잘못된 Argument 여부
존재하지 않는 Tool 호출 여부
잘못된 Tool 순서 여부
```

예:

```text
사용자:
"내일 전주 날씨 보고 코디 추천해줘"

올바른 호출:
get_weather()

잘못된 호출:
get_calendar_events()
```

---

# 10. 데이터 분리 계획

최종 정제 데이터는 다음 비율로 분리한다.

```text
Train       80%
Validation  10%
Test        10%
```

Synthetic Data의 경우 거의 동일한 변형 데이터가 Train과 Test에 동시에 포함되지 않도록 주의한다.

이를 통해 실제 일반화 성능을 확인할 수 있도록 구성한다.

---

# 11. 최종 결론

본 프로젝트에서는 패션 추천 학습을 위해 Polyvore Outfits, AI Hub 패션 데이터, Fashion Stylist Multimodal v2, Fashionpedia, DeepFashion2 등을 조사하였다.

Polyvore Outfits은 의류 간 조합 및 Outfit Recommendation 구조를 참고하기에 적합하며, AI Hub 데이터는 국내 의류 카테고리 및 착용 관계를 참고하는 데 활용할 수 있다.

Fashion Stylist Multimodal v2는 Synthetic Dataset이므로 Gold Data로 직접 활용하기보다는 패션 추천 JSON 구조와 Synthetic Data 설계에 참고한다.

Tool Calling 학습을 위해 glaive-function-calling-v2-ko, xLAM Function Calling 60K, Hermes Function Calling v1, Glaive Function Calling v2 등을 조사하였다.

공개 Tool Calling Dataset의 Function 종류는 본 프로젝트와 직접 일치하지 않으므로 전체 데이터를 그대로 학습하기보다는 Tool Calling 구조, JSON 형식, Multi-Tool Calling 방식 및 검증 방법을 참고한다.

본 프로젝트의 실제 Tool Calling Data는 다음 4개 Tool을 기준으로 직접 구축한다.

```text
get_user_context()
get_wardrobe()
get_weather()
get_calendar_events()
```

최종적으로 공개 데이터는 구조와 패턴을 참고하는 용도로 활용하고, 프로젝트 전용 Gold Data와 Synthetic Data를 구축하여 Qwen3-4B QLoRA Fine-Tuning에 활용한다.

---

# 12. 참고 자료

## Fashion Dataset

- Polyvore Outfits  
  https://huggingface.co/datasets/mvasil/polyvore-outfits

- AI Hub 패션상품 및 착용 영상  
  https://www.aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&currMenu=116&dataSetSn=78

- AI Hub 의류 통합 데이터  
  https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71501

- Fashion Stylist Multimodal v2  
  https://huggingface.co/datasets/lihicarmeli/fashion-stylist-multimodal-v2

- Fashionpedia  
  https://fashionpedia.github.io/

- DeepFashion2  
  https://github.com/switchablenorms/DeepFashion2

## Tool Calling Dataset

- glaive-function-calling-v2-ko  
  https://huggingface.co/datasets/heegyu/glaive-function-calling-v2-ko

- xLAM Function Calling 60K  
  https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k

- Hermes Function Calling v1  
  https://huggingface.co/datasets/NousResearch/hermes-function-calling-v1

- Glaive Function Calling v2  
  https://huggingface.co/datasets/glaiveai/glaive-function-calling-v2