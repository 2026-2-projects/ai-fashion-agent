BEGIN;

-- 001/002가 적용된 기존 DB에 추가한다. 기존 평가/저장 행은 수정하지 않는다.
ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS reason_text TEXT;

ALTER TABLE feedback
    DROP CONSTRAINT IF EXISTS chk_feedback_reason;

ALTER TABLE feedback
    ADD CONSTRAINT chk_feedback_reason
    CHECK (
        reason IS NULL
        OR reason IN (
            'COLOR',
            'FIT',
            'NOT_MY_STYLE',
            'TOO_DRESSED_UP',
            'TOO_PLAIN',
            'TOO_CASUAL',
            'WEATHER',
            'OCCASION',
            'COMBINATION',
            'OTHER'
        )
    );

-- 002의 chk_feedback_reason_usage는 유지한다: 사유 없는 싫어요를 허용한다.
-- CASE로 NULL 사유가 CHECK의 UNKNOWN 결과를 통해 잘못 통과하지 않게 한다.
ALTER TABLE feedback
    DROP CONSTRAINT IF EXISTS chk_feedback_reason_text_usage;

ALTER TABLE feedback
    ADD CONSTRAINT chk_feedback_reason_text_usage
    CHECK (
        CASE
            WHEN feedback_type = 'DISLIKE' AND reason = 'OTHER' THEN
                reason_text IS NOT NULL
                AND char_length(reason_text) BETWEEN 1 AND 300
                -- Python str.strip()과 같은 29개 공백 문자를 검사한다.
                AND reason_text COLLATE "C" = btrim(
                    reason_text,
                    U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                )
                -- TAB/LF/CR 이외의 C0/C1 제어 문자를 거부한다. NUL은 TEXT가 거부한다.
                AND reason_text COLLATE "C"
                    !~ U&'[\0001-\0008\000B\000C\000E-\001F\007F-\009F]'
            ELSE reason_text IS NULL
        END
    );

COMMIT;
