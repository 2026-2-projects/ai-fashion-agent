BEGIN;

-- 단일 '싫어요' 버튼만으로도 평가할 수 있도록 사유는 선택 입력으로 둔다.
-- reason 값 자체의 허용 목록은 기존 chk_feedback_reason 제약이 계속 검증한다.
ALTER TABLE feedback
    DROP CONSTRAINT chk_feedback_reason_usage;

ALTER TABLE feedback
    ADD CONSTRAINT chk_feedback_reason_usage
    CHECK (
        feedback_type = 'DISLIKE'
        OR (
            feedback_type IN ('LIKE', 'SAVE')
            AND reason IS NULL
        )
    );

COMMIT;
