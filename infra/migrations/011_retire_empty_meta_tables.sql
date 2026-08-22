BEGIN;

-- Empty speculative/meta-loop tables with no active operator workflow.
-- The Discord bot remains an alert/command surface; conversational sessions
-- belong in Codex CLI or the retained OpenCode web service.
DROP TABLE IF EXISTS assistant_messages;
DROP TABLE IF EXISTS brand_embeddings;
DROP TABLE IF EXISTS mentions;

COMMIT;
