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

CREATE INDEX IF NOT EXISTS chat_turns_history ON chat_turns (chat_id, sequence);
CREATE INDEX IF NOT EXISTS chat_turns_pending ON chat_turns (sequence)
    WHERE status IN ('queued', 'processing');

CREATE INDEX IF NOT EXISTS chat_turns_handoffs ON chat_turns (sequence DESC)
    WHERE status = 'succeeded' AND result ->> 'outcome' = 'handoff';
