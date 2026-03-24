"""
app/api/services/error_translator.py
Maps raw exceptions/error strings to plain English with suggested fixes.
Used to produce user-friendly error messages stored in ForgeRun.error_message.
"""


def translate_error(raw: str) -> dict:
    """
    Translate a raw exception/error string into a human-readable message with a fix suggestion.
    Returns {"message": str, "fix": str}.
    """
    raw_lower = raw.lower()

    # Rate limit
    if "429" in raw or "rate_limit" in raw_lower or "ratelimiterror" in raw_lower:
        return {
            "message": "Claude API rate limited. System will retry automatically.",
            "fix": "Wait — it resolves itself.",
        }

    # JSON decode errors
    if "jsondecodeerror" in raw_lower or "json.decoder" in raw_lower:
        return {
            "message": "Claude returned malformed JSON. 4 recovery methods were attempted.",
            "fix": "Try reducing attached file size or simplifying the blueprint.",
        }

    # Database/connection errors
    if "connectionerror" in raw_lower or "asyncpg" in raw_lower or "operationalerror" in raw_lower:
        return {
            "message": "Database connection lost. Writes queued for replay.",
            "fix": "Check System Health — usually recovers within minutes.",
        }

    # Max retries exceeded
    if "max retries exceeded" in raw_lower or "retry_count" in raw_lower:
        return {
            "message": "Build failed 3 times.",
            "fix": "Try resubmitting with fewer attached files.",
        }

    # Abandoned job (worker restart)
    if "abandonedjobError" in raw or "abandonedjob" in raw_lower:
        return {
            "message": "Worker was restarted during this build.",
            "fix": "Hit Resume to continue from where it stopped.",
        }

    # Timeout errors
    if "timeout" in raw_lower or "timeouterror" in raw_lower:
        return {
            "message": "Build step timed out.",
            "fix": "Try resubmitting — transient timeouts are usually self-resolving.",
        }

    # Context length / input too long
    if "context_length_exceeded" in raw_lower or "too long" in raw_lower:
        return {
            "message": "Blueprint too large for single call. Chunked parsing will handle it.",
            "fix": "Input was automatically reduced.",
        }

    # Stalled / stuck builds
    if "stuck" in raw_lower or "20+ minutes" in raw_lower or "stalled" in raw_lower:
        return {
            "message": "Build stalled with no output.",
            "fix": "Mark as failed and resubmit.",
        }

    # Fallback: return the original message
    return {
        "message": raw,
        "fix": "Check logs for details.",
    }


def translate_error_for_storage(raw: str) -> str:
    """
    Translate a raw error string and return just the message component.
    Convenience wrapper for storing translated errors in DB error_message field.
    """
    return translate_error(raw)["message"]
