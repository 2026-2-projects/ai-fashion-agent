BEGIN;

-- 1. 사용자가 실제로 받은 추천 결과 보관
CREATE TABLE recommendation_runs (
    id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL
        REFERENCES users(id) ON DELETE CASCADE,
    looks JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT recommendation_runs_owner_key
        UNIQUE (id, user_id),
    CONSTRAINT recommendation_five_looks
        CHECK (
            jsonb_typeof(looks) = 'array'
            AND jsonb_array_length(looks) = 5
        )
);

CREATE INDEX idx_recommendation_runs_user
    ON recommendation_runs(user_id);

-- 2. 피드백에 추천 및 LOOK 식별 정보 추가
ALTER TABLE feedback
    ADD COLUMN recommendation_id UUID,
    ADD COLUMN look_id SMALLINT
        CHECK (look_id BETWEEN 1 AND 5);

ALTER TABLE feedback
    ADD CONSTRAINT fk_feedback_recommendation_owner
    FOREIGN KEY (recommendation_id, user_id)
    REFERENCES recommendation_runs(id, user_id);

CREATE UNIQUE INDEX uq_feedback_user_look
    ON feedback(user_id, recommendation_id, look_id)
    WHERE recommendation_id IS NOT NULL;

-- 3. 저장한 코디에도 추천 및 LOOK 식별 정보 추가
ALTER TABLE saved_outfits
    ADD COLUMN recommendation_id UUID,
    ADD COLUMN look_id SMALLINT
        CHECK (look_id BETWEEN 1 AND 5);

ALTER TABLE saved_outfits
    ADD CONSTRAINT fk_saved_outfit_recommendation_owner
    FOREIGN KEY (recommendation_id, user_id)
    REFERENCES recommendation_runs(id, user_id);

CREATE UNIQUE INDEX uq_saved_outfit_user_look
    ON saved_outfits(user_id, recommendation_id, look_id)
    WHERE recommendation_id IS NOT NULL;

COMMIT;