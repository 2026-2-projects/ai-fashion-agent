# PostgreSQL 스키마 설치와 업그레이드

| 대상 | 적용 방법 |
| --- | --- |
| 새 전용 DB | `baseline_003.sql`을 한 번 실행합니다. 001~003의 최종 상태를 포함합니다. |
| 기존 DB | 백업 및 적용 이력과 실제 스키마를 대조한 뒤 아직 적용되지 않은 증분만 순서대로 적용합니다. |
| 부분적으로 초기화됐거나 이력이 불명확한 DB | 작업을 멈추고 스키마 차이를 검토합니다. 이미 있는 데이터를 보존한 복제본에서 먼저 확인합니다. |

## 새 DB

PostgreSQL 15의 빈 DB와 그 DB에 테이블을 만들 수 있는 역할을 준비합니다. 다음 예시는 저장소 루트에서 **새로 만든 로컬 DB**에 적용하는 명령입니다.

```sh
psql -X -v ON_ERROR_STOP=1 -d clomori_new -f backend/migrations/baseline_003.sql
```

초기화는 한 트랜잭션으로 진행합니다. 동시에 시작한 초기화는 DB 안의 같은 잠금을 사용합니다. 사용자 정의 스키마, `public`의 기존 객체 또는 저장된 large object가 있으면 중단합니다. 테이블이 비어 있어도 이미 만든 스키마는 보호합니다. 실패했다면 반환 코드와 대상 DB를 확인하세요. 오류를 없애려고 기존 객체를 삭제하거나 같은 DB에 전체 덤프를 복원하지 마세요.

결과는 `public`의 애플리케이션 테이블 8개, 시퀀스 7개, 인덱스 19개(기본 키·UNIQUE 인덱스 포함)입니다. PostgreSQL 15 기준 CHECK·PK·FK·UNIQUE 제약 합계는 31개입니다. 초기 사용자와 사진, OAuth 토큰, 추천 데이터는 생성되지 않습니다. 성공한 대상 DB·시각과 기준 버전 003을 운영 기록에 남깁니다.

## 기존 DB

기존 데이터와 스키마의 복구 가능한 백업을 확인하고, 해당 DB의 배포 기록과 아래 변경 내용을 대조합니다. 테이블 이름이나 개수만으로 적용 여부를 판정하지 마세요.

| 증분 | 확인할 스키마 변경 |
| --- | --- |
| [001](001_feedback_save.sql) | `recommendation_runs`와 관련 PK·FK·인덱스, `feedback`·`saved_outfits`의 `recommendation_id`·`look_id`, 추천 소유권 복합 FK와 사용자별 부분 UNIQUE 인덱스 |
| [002](002_optional_dislike_reason.sql) | `feedback.chk_feedback_reason_usage`의 **정의**가 싫어요 사유 생략을 허용하며 좋아요·저장 사유는 NULL로 제한 |
| [003](003_feedback_reason_text.sql) | `feedback.reason_text`, 갱신된 `chk_feedback_reason`, `chk_feedback_reason_text_usage` 정의 |

제약을 확인하는 예시입니다. 사용자 행은 조회하지 않습니다.

```sql
SELECT t.relname, c.conname, pg_get_constraintdef(c.oid)
FROM pg_constraint AS c
JOIN pg_class AS t ON t.oid = c.conrelid
WHERE t.relnamespace = 'public'::regnamespace
  AND t.relname IN ('recommendation_runs', 'feedback', 'saved_outfits')
ORDER BY t.relname, c.conname;
```

### 확인한 증분 하나 적용

로컬 관리자 도구 `scripts/db/legacy_sql.py`는 지정한 증분만 감싼 psql 스크립트를 출력합니다. 각 스크립트는 단일 트랜잭션에서 잠금, 현재 상태 확인, DDL, 완료 검사까지 수행합니다. 001의 추천 테이블·컬럼·FK·인덱스나 003의 변경 흔적이 예상과 다르면 중단합니다. 002 이후 상태는 동일 서버가 002 SQL로 임시 테이블에 만든 CHECK 정의와 비교합니다. 이미 적용된 증분을 선택해도 기존 데이터 변경 없이 실패합니다.

002와 003은 해당 증분 **직전** 버전의 승인된 기준 스키마에서 확인한 CHECK 정의 파일도 필요합니다. 002에는 `chk_feedback_reason_usage`, 003에는 `chk_feedback_reason`을 사용합니다. 아래 예시는 승인된 002 참조 DB에서 003의 이전 CHECK를 저장하는 명령입니다. 참조 DB는 운영 대상과 같은 PostgreSQL 메이저 버전을 사용하세요. 기존 운영 DB에서 방금 뽑은 정의를 그대로 승인값으로 쓰면 이전 버전의 독립적인 확인이 되지 않습니다. 신뢰할 수 있는 기준이 없거나 일부 객체만 적용된 상태이면 직접 실행을 멈추고 복제본에서 차이를 검토하세요.

```sh
psql -XAt -v ON_ERROR_STOP=1 -d reviewed_v002 -c "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='public.feedback'::regclass AND conname='chk_feedback_reason'" > prior-v002-reason.txt
python3 scripts/db/legacy_sql.py 003 --prior-check prior-v002-reason.txt > reviewed-003.sql &&
  psql -X -v ON_ERROR_STOP=1 -d target_db -f reviewed-003.sql
```

001만 누락된 경우 생성 명령은 `python3 scripts/db/legacy_sql.py 001`입니다. 002를 선택할 때는 같은 방식으로 `002 --prior-check <기준 v001의 사유 사용 제약 파일>`을 지정합니다. 담당자 한 명이 대상 DB와 결과 스키마를 확인하고 적용 일시·버전을 운영 기록에 남깁니다. 개별 원본 증분 파일들은 보존되어 있으므로 배포에서 직접 호출하거나 `*.sql`을 순회하지 마세요.
