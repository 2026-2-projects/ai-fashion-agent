-- Requires 001_initial.sql. Does not drop or overwrite existing tables.
BEGIN;
CREATE TABLE recommendation_looks (
    id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    look_id SMALLINT NOT NULL CHECK (look_id BETWEEN 1 AND 5),
    snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    features JSONB NOT NULL CHECK (jsonb_typeof(features) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, id)
);
CREATE INDEX recommendation_looks_user_idx ON recommendation_looks(user_id);
CREATE TABLE feedback (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    outfit_id UUID NOT NULL,
    reaction TEXT NOT NULL CHECK (reaction IN ('like', 'dislike')),
    reason_codes TEXT[] NOT NULL DEFAULT '{}',
    comment VARCHAR(1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, outfit_id),
    FOREIGN KEY (user_id, outfit_id)
        REFERENCES recommendation_looks(user_id, id) ON DELETE CASCADE,
    CHECK ((reaction = 'like' AND cardinality(reason_codes) = 0)
        OR (reaction = 'dislike' AND cardinality(reason_codes) > 0)),
    CHECK (reason_codes <@ ARRAY['color', 'fit', 'style', 'too_formal', 'too_plain']::TEXT[])
);
CREATE TABLE saved_outfits (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    outfit_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, outfit_id),
    FOREIGN KEY (user_id, outfit_id)
        REFERENCES recommendation_looks(user_id, id) ON DELETE CASCADE
);
CREATE INDEX saved_outfits_page_idx ON saved_outfits(user_id, created_at DESC, outfit_id DESC);
INSERT INTO schema_migrations(version) VALUES (2);
COMMIT;
