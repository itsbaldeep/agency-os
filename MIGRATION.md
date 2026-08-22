# OpenCode Zen → Codex + DeepSeek migration

Codex CLI is the worker's default coding-agent harness. It authenticates with
the ChatGPT subscription in `~/.codex/auth.json`. Raw chat completions are
separate and use DeepSeek's OpenAI-compatible API.

## Environment

Set these in the worker environment / `.env`:

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=...
ZAI_API_KEY=...                    # optional fallback
OPENROUTER_API_KEY=...              # optional fallback
OPENROUTER_FREE_MODEL=...:free      # optional; defaults to deepseek/deepseek-r1:free
```

`DEEPSEEK_API_KEY` is used only by raw pipeline completion calls. The worker
removes `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `DEEPSEEK_API_KEY` before it
starts `codex exec`, so Codex continues to use `~/.codex/auth.json`.

Raw completions use `deepseek-chat`. If DeepSeek rejects a request for balance
or rate-limit reasons, the worker tries z.ai `glm-4.5-flash`, then the configured
OpenRouter `:free` model; unset fallback keys are skipped.

## Rollback

Set `OPENCODE_FALLBACK=1` in the worker environment and restart the worker to
send coding-agent tasks back through the retained `run_opencode` path. Remove
the flag (or set it to `0`) and restart to return to Codex. This does not change
the DeepSeek raw-completion path.
