CREATE TABLE IF NOT EXISTS chats (
    chat_id uuid PRIMARY KEY,
    token_hash bytea NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_turns (
    turn_id uuid PRIMARY KEY,
    chat_id uuid NOT NULL REFERENCES chats (chat_id),
    sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    client_message_id text NOT NULL,
    message_text text NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'succeeded', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    lease_until timestamptz,
    result jsonb,
    error text,
    UNIQUE (chat_id, client_message_id),
    CHECK ((status = 'processing') = (lease_until IS NOT NULL)),
    CHECK ((status = 'succeeded') = (result IS NOT NULL)),
    CHECK ((status = 'failed') = (error IS NOT NULL))
);

-- Keep claim numbers monotonic across manual retries so stale workers stay fenced.
ALTER TABLE chat_turns ADD COLUMN IF NOT EXISTS retry_attempt_base integer NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS chat_turns_history ON chat_turns (chat_id, sequence);
CREATE INDEX IF NOT EXISTS chat_turns_pending ON chat_turns (sequence)
    WHERE status IN ('queued', 'processing');

CREATE INDEX IF NOT EXISTS chat_turns_handoffs ON chat_turns (sequence DESC)
    WHERE status = 'succeeded' AND result ->> 'outcome' = 'handoff';

ALTER TABLE chat_turns ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS commerce_knowledge (
    article_id text PRIMARY KEY,
    source_id text NOT NULL,
    source_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('draft', 'published'))
);

ALTER TABLE chat_turns ADD COLUMN IF NOT EXISTS submitted_at timestamptz;

CREATE TABLE IF NOT EXISTS manager_replies (
    handoff_id uuid PRIMARY KEY REFERENCES chat_turns (turn_id),
    after_sequence bigint NOT NULL REFERENCES chat_turns (sequence),
    text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS manager_replies_after_sequence ON manager_replies (after_sequence);

CREATE TABLE IF NOT EXISTS manager_knowledge (
    handoff_id uuid PRIMARY KEY REFERENCES manager_replies (handoff_id),
    article jsonb NOT NULL,
    search_keys text[] NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS manager_knowledge_search ON manager_knowledge USING gin (search_keys);

ALTER TABLE manager_replies ADD COLUMN IF NOT EXISTS confirmed_quote_id uuid REFERENCES chat_turns (turn_id);
CREATE UNIQUE INDEX IF NOT EXISTS manager_replies_confirmed_quote
    ON manager_replies (confirmed_quote_id) WHERE confirmed_quote_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS customer_resolutions (
    turn_id uuid PRIMARY KEY REFERENCES chat_turns (turn_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
