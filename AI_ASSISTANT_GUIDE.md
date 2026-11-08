# AI Assistant Guide

AI is **optional**. Every feature works without it; AI adds free-form answers, extra test proposals and narrative failure analysis.

## Configuration

```env
AI_PROVIDER=anthropic          # or none (default)
AI_API_KEY=<your Anthropic API key>
AI_MODEL=claude-opus-5-5       # any Messages-API model id
AI_TIMEOUT_SECONDS=90
AI_MAX_REQUESTS_PER_HOUR=60
```

The key is read only by the backend (API/worker). It is never sent to the browser, included in reports, or logged (log redaction masks `sk-ant-…` patterns). `/api/system/capabilities` exposes only whether AI is configured and the model name.

## Provider layer

`app/ai/provider.py` defines `AIProvider.structured(system, prompt, schema)`. `AnthropicProvider` uses the official Anthropic Python SDK (`client.messages.parse` with a Pydantic `output_format`, effort `medium`) and enables Anthropic's server-side refusal fallback (`fallbacks: "default"`). The response is re-validated with Pydantic; refusals, truncation (`max_tokens`), schema mismatches, authentication, rate-limit, connection and server errors are converted to `AIUnavailable` with a user-readable reason. A per-process hourly limiter caps usage. Adding another provider means implementing `structured()`.

## Uses

| Feature | Context sent | Output schema | Fallback without AI |
|---|---|---|---|
| Test generation | file path, language/framework instructions, existing test file names, focus, source (≤14 000 chars) | `AITestSuggestions` | rule-based generators |
| Failure analysis | test name, file, status, raw message, traceback tail (≤6 000 chars), up to 25 source lines around the failing frame | `AIFailureAnalysis` (summary, location, meaning, causes, fixes, extra tests, confidence) | rule-based explanation (always computed) |
| Assistant | compact JSON of stored project data: analysis summary, open findings, latest run + failures, coverage, generated-test counts; last 6 messages | `AIAssistantAnswer` (answer, used_sources, information_missing) | deterministic grounded responder |

## Grounding rules

The system prompts instruct the model to use only the supplied context and to say what is missing rather than invent files, results, coverage, error messages, locations or history. The model **never** decides test outcomes — statuses come only from the execution engine — and AI analyses are stored separately (`ai_analysis`) from the raw output and the rule-based analysis, labelled "suggestion" with provider and confidence.

## Grounded responder (no AI)

Without a provider, the assistant answers common questions directly from the database: architecture/structure, which functions to test (complexity, gaps, findings), latest run summary, failures and stack traces, coverage and uncovered files, open findings, and a release checklist derived from recorded data. Other questions get an explanation of what it can answer. Messages show `answered from stored data` and the data sections used.

## Error handling

If the AI call fails during chat, the assistant answers from stored data and prefixes the reply with the reason. AI failure analysis returns HTTP 503 with the reason. AI test generation failures are listed in the job result while rule-based tests are still created.
