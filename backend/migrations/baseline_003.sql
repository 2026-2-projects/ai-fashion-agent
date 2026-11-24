-- CLOMORI PostgreSQL baseline through migration 003. New, empty databases only.
-- Includes definitions only. Each application sequence starts at its initial value.
BEGIN ISOLATION LEVEL READ COMMITTED;
SET LOCAL search_path = pg_catalog;
SET LOCAL standard_conforming_strings = on;
SET LOCAL lock_timeout = '10s';

-- Serialize concurrent attempts in this database. The following statement sees
-- objects committed by a previous initializer before it acquired the lock.
SELECT pg_catalog.pg_advisory_xact_lock(21023003, 1);

DO $guard$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_namespace WHERE nspname = 'public')
       OR EXISTS (SELECT FROM pg_catalog.pg_database WHERE datname = current_database() AND datistemplate)
       OR EXISTS (
           SELECT FROM pg_catalog.pg_namespace
           WHERE nspname !~ '^pg_' AND nspname NOT IN ('information_schema', 'public')
       )
       OR EXISTS (
           SELECT FROM pg_catalog.pg_depend
           WHERE refclassid = 'pg_catalog.pg_namespace'::regclass
             AND refobjid = 'public'::regnamespace
       )
       OR EXISTS (SELECT FROM pg_catalog.pg_largeobject_metadata)
    THEN
        RAISE EXCEPTION 'CLOMORI baseline requires a new, empty database with an empty public schema'
            USING HINT = 'Review migration history for an existing or partially initialized database.';
    END IF;
END;
$guard$;

CREATE TABLE public.feedback (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    feedback_type character varying(20) NOT NULL,
    reason character varying(50),
    style_tags text[] DEFAULT '{}'::text[] NOT NULL,
    color_tags text[] DEFAULT '{}'::text[] NOT NULL,
    fit_tags text[] DEFAULT '{}'::text[] NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    recommendation_id uuid,
    look_id smallint,
    reason_text text,
    CONSTRAINT chk_feedback_reason CHECK (((reason IS NULL) OR ((reason)::text = ANY (ARRAY[('COLOR'::character varying)::text, ('FIT'::character varying)::text, ('NOT_MY_STYLE'::character varying)::text, ('TOO_DRESSED_UP'::character varying)::text, ('TOO_PLAIN'::character varying)::text, ('TOO_CASUAL'::character varying)::text, ('WEATHER'::character varying)::text, ('OCCASION'::character varying)::text, ('COMBINATION'::character varying)::text, ('OTHER'::character varying)::text])))),
    CONSTRAINT chk_feedback_reason_text_usage CHECK (
CASE
    WHEN (((feedback_type)::text = 'DISLIKE'::text) AND ((reason)::text = 'OTHER'::text)) THEN ((reason_text IS NOT NULL) AND ((char_length(reason_text) >= 1) AND (char_length(reason_text) <= 300)) AND ((reason_text COLLATE "C") = btrim(reason_text, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'::text)) AND ((reason_text COLLATE "C") !~ U&'[\0001-\0008\000B\000C\000E-\001F\007F-\009F]'::text))
    ELSE (reason_text IS NULL)
END),
    CONSTRAINT chk_feedback_reason_usage CHECK ((((feedback_type)::text = 'DISLIKE'::text) OR (((feedback_type)::text = ANY (ARRAY[('LIKE'::character varying)::text, ('SAVE'::character varying)::text])) AND (reason IS NULL)))),
    CONSTRAINT chk_feedback_type CHECK (((feedback_type)::text = ANY (ARRAY[('LIKE'::character varying)::text, ('DISLIKE'::character varying)::text, ('SAVE'::character varying)::text]))),
    CONSTRAINT feedback_look_id_check CHECK (((look_id >= 1) AND (look_id <= 5)))
);

CREATE SEQUENCE public.feedback_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.feedback_id_seq OWNED BY public.feedback.id;

CREATE TABLE public.google_calendar_connections (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    google_account_email character varying(255),
    access_token_encrypted text,
    refresh_token_encrypted text,
    token_expires_at timestamp with time zone,
    scope text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.google_calendar_connections_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.google_calendar_connections_id_seq OWNED BY public.google_calendar_connections.id;

CREATE TABLE public.recommendation_runs (
    id uuid NOT NULL,
    user_id bigint NOT NULL,
    looks jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT recommendation_five_looks CHECK (((jsonb_typeof(looks) = 'array'::text) AND (jsonb_array_length(looks) = 5)))
);

CREATE TABLE public.saved_outfits (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    title character varying(100),
    outfit_data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    recommendation_id uuid,
    look_id smallint,
    CONSTRAINT chk_saved_outfits_outfit_data CHECK ((jsonb_typeof(outfit_data) = 'object'::text)),
    CONSTRAINT saved_outfits_look_id_check CHECK (((look_id >= 1) AND (look_id <= 5)))
);

CREATE SEQUENCE public.saved_outfits_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.saved_outfits_id_seq OWNED BY public.saved_outfits.id;

CREATE TABLE public.user_preferences (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    preferred_styles text[] DEFAULT '{}'::text[] NOT NULL,
    preferred_colors text[] DEFAULT '{}'::text[] NOT NULL,
    disliked_colors text[] DEFAULT '{}'::text[] NOT NULL,
    preferred_fit character varying(50),
    feedback_summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.user_preferences_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_preferences_id_seq OWNED BY public.user_preferences.id;

CREATE TABLE public.user_profiles (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    gender character varying(30),
    age_group character varying(30),
    height_cm smallint,
    body_type character varying(50),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_user_profiles_height CHECK (((height_cm IS NULL) OR (height_cm > 0)))
);

CREATE SEQUENCE public.user_profiles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_profiles_id_seq OWNED BY public.user_profiles.id;

CREATE TABLE public.users (
    id bigint NOT NULL,
    email character varying(255) NOT NULL,
    password_hash text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;

CREATE TABLE public.wardrobe_items (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    category character varying(50) NOT NULL,
    item_type character varying(100) NOT NULL,
    color character varying(50) NOT NULL,
    fit character varying(50) NOT NULL,
    seasons text[] DEFAULT '{}'::text[] NOT NULL,
    image_url text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.wardrobe_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.wardrobe_items_id_seq OWNED BY public.wardrobe_items.id;

ALTER TABLE ONLY public.feedback ALTER COLUMN id SET DEFAULT nextval('public.feedback_id_seq'::regclass);

ALTER TABLE ONLY public.google_calendar_connections ALTER COLUMN id SET DEFAULT nextval('public.google_calendar_connections_id_seq'::regclass);

ALTER TABLE ONLY public.saved_outfits ALTER COLUMN id SET DEFAULT nextval('public.saved_outfits_id_seq'::regclass);

ALTER TABLE ONLY public.user_preferences ALTER COLUMN id SET DEFAULT nextval('public.user_preferences_id_seq'::regclass);

ALTER TABLE ONLY public.user_profiles ALTER COLUMN id SET DEFAULT nextval('public.user_profiles_id_seq'::regclass);

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

ALTER TABLE ONLY public.wardrobe_items ALTER COLUMN id SET DEFAULT nextval('public.wardrobe_items_id_seq'::regclass);

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.google_calendar_connections
    ADD CONSTRAINT google_calendar_connections_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.google_calendar_connections
    ADD CONSTRAINT google_calendar_connections_user_id_key UNIQUE (user_id);

ALTER TABLE ONLY public.recommendation_runs
    ADD CONSTRAINT recommendation_runs_owner_key UNIQUE (id, user_id);

ALTER TABLE ONLY public.recommendation_runs
    ADD CONSTRAINT recommendation_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.saved_outfits
    ADD CONSTRAINT saved_outfits_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_user_id_key UNIQUE (user_id);

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_user_id_key UNIQUE (user_id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.wardrobe_items
    ADD CONSTRAINT wardrobe_items_pkey PRIMARY KEY (id);

CREATE INDEX idx_feedback_user_id ON public.feedback USING btree (user_id);

CREATE INDEX idx_recommendation_runs_user ON public.recommendation_runs USING btree (user_id);

CREATE INDEX idx_saved_outfits_user_id ON public.saved_outfits USING btree (user_id);

CREATE INDEX idx_wardrobe_items_user_id ON public.wardrobe_items USING btree (user_id);

CREATE UNIQUE INDEX uq_feedback_user_look ON public.feedback USING btree (user_id, recommendation_id, look_id) WHERE (recommendation_id IS NOT NULL);

CREATE UNIQUE INDEX uq_saved_outfit_user_look ON public.saved_outfits USING btree (user_id, recommendation_id, look_id) WHERE (recommendation_id IS NOT NULL);

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT fk_feedback_recommendation_owner FOREIGN KEY (recommendation_id, user_id) REFERENCES public.recommendation_runs(id, user_id);

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT fk_feedback_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.google_calendar_connections
    ADD CONSTRAINT fk_google_calendar_connections_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.saved_outfits
    ADD CONSTRAINT fk_saved_outfit_recommendation_owner FOREIGN KEY (recommendation_id, user_id) REFERENCES public.recommendation_runs(id, user_id);

ALTER TABLE ONLY public.saved_outfits
    ADD CONSTRAINT fk_saved_outfits_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT fk_user_preferences_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT fk_user_profiles_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.wardrobe_items
    ADD CONSTRAINT fk_wardrobe_items_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.recommendation_runs
    ADD CONSTRAINT recommendation_runs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

COMMIT;
