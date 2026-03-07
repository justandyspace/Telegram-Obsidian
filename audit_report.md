# Pre-Pentest Security Audit: telegram-obsidian-local

**Auditor:** external / independent  
**Date:** 2026-03-05  
**Assessment mode:** red-team ready  
**Target codebase:** `C:\Users\Desktop\Desktop\telegram-obsidian-local`

---

## A. Executive Summary

The bot accepts text, media, links, and voice messages from authorized Telegram users, processes them through an AI pipeline, and writes notes into Obsidian-backed storage using SQLite and CouchDB.

**Reported findings:**

- Critical (P0): **4**
- High risk (P1): **5**
- Medium risk (P2): **4**
- Low risk (P3): **2**

**Primary blocker:** real operator secrets were stored in plaintext inside `.env`, including `TELEGRAM_TOKEN`, `GEMINI_API_KEY`, `CF_TUNNEL_TOKEN`, `TG_API_HASH`, `TG_API_ID`, and `COUCHDB_PASSWORD`. Any token found in that file must be treated as compromised and rotated immediately.

Additional high-severity concerns include SQL injection risk in migration helpers, missing rate limiting for expensive Telegram flows, SSRF exposure through DNS rebinding / TOCTOU behavior, and leakage of internal exception text to end users.

**Verdict:** `NO-GO` for external pentesting until all P0 and P1 issues are resolved.

---

## B. Findings Table

| ID | Severity | CWE | Component | Summary | Impact | Recommended Fix |
| --- | --- | --- | --- | --- | --- | --- |
| F-01 | P0 | CWE-312 | `.env` / git history | Secrets stored in plaintext and potentially committed | Full bot compromise, data leakage, third-party API abuse | Rotate all secrets, remove from history, move to a secrets manager |
| F-02 | P0 | CWE-89 | `storage.py` migration helper | Dynamic SQL built with interpolated identifiers | Schema destruction, arbitrary DB modification | Enforce a hardcoded whitelist for table and column names |
| F-03 | P0 | CWE-400 | Telegram handlers | No per-user or per-command rate limiting | Cost abuse, queue starvation, denial of service | Add token-bucket limits for intake and heavy commands |
| F-04 | P0 | CWE-918 | `url_safety.py` | URL validation and request execution can resolve DNS at different moments | SSRF against internal services | Lock requests to the validated IP and harden resolver behavior |
| F-05 | P1 | CWE-200 | `ai_service.py` and router | Raw exception strings may be returned to users | Internal path and system state leakage | Return generic user-safe errors and log internals only |
| F-06 | P1 | CWE-326 | CouchDB deployment | Basic auth over non-TLS transport | Credential interception in transit | Require TLS for DB traffic |
| F-07 | P1 | CWE-284 | `commands.py` delete-all flow | Token consume and deletion are not atomic | Partial or unintended deletion under race | Use one transaction / lock scope |
| F-08 | P1 | CWE-22 | `commands.py` path validation | Symbolic-link traversal risk during delete | Arbitrary file deletion outside the vault | Check symlinks and validate resolved paths strictly |
| F-09 | P2 | CWE-693 | CouchDB config | Broad CORS write permissions | CSRF exposure | Restrict methods and disable credentialed write CORS |
| F-10 | P2 | CWE-116 | `telegram_router.py` | Telegram file path interpolation lacks strict sanitization | Limited traversal-style risk | Validate allowed path characters explicitly |
| F-11 | P2 | CWE-400 | `enrichment.py` | No strict cap on large prompt payloads | Cost abuse and degraded performance | Truncate large prompt bodies deterministically |
| F-12 | P2 | CWE-693 | Docker / dependencies | Floating images and unhashed installs | Supply-chain risk | Pin digests and require dependency hashes |
| F-13 | P2 | CWE-778 | logging | Missing audit trail for destructive actions | Weak incident forensics | Add structured audit logs |
| F-14 | P3 | CWE-311 | SQLite durability mode | `synchronous=NORMAL` may lose recent writes on crash | Limited data loss window | Consider `synchronous=FULL` where appropriate |
| F-15 | P3 | CWE-400 | Telegram polling behavior | Long polling loops around media retrieval can be noisy | Telegram API throttling risk | Add exponential backoff |

---

## C. Top 10 Must-Fix Before Pentest

- Rotate all compromised secrets and remove `.env` from version control history.
- Add per-user rate limits for intake, `/summary`, and `/find`.
- Fix DNS rebinding / TOCTOU exposure in URL fetch validation.
- Stop returning raw exception text to Telegram users.
- Harden delete flows against symlink traversal.
- Add strict identifier whitelists for migration-time SQL helpers.
- Tighten CouchDB CORS policy.
- Limit LLM prompt size deterministically.
- Pin infrastructure images and dependency integrity.
- Add structured audit logging for delete and retry operations.

---

## D. Telegram Command Risk Matrix

| Command | Main Abuse Vector | Current Risk | Required Protection |
| --- | --- | --- | --- |
| `/start` | Recon / feature discovery | Low | Allowlist enforcement |
| `/status` | Operational detail leakage | Medium | Redact internals and limit user-facing diagnostics |
| `/find <query>` | DoS against search and index | High | Rate limiting and query length caps |
| `/summary <query>` | LLM abuse, prompt injection, cost spikes | High | Strict limits, sanitization, quotas |
| `/job <id>` | Enumeration of job identifiers | Medium | Reduce exposure of note paths and internals |
| `/retry <id>` | Retry storm on unstable jobs | Medium | Retry caps and throttling |
| `/delete <id|file>` | Unsafe file deletion | High | Strict path validation and audit logs |
| `/delete all` | Total data wipe | Medium | Strong confirmation flow and shorter TTL |
| `/delete confirm` | Token replay / timing edge cases | Low | Constant-time compare and one-time token semantics |
| Intake flows | Large-file floods | High | Queue throttling and payload limits |

---

## E. GO / NO-GO for External Pentest

### Verdict: `NO-GO`

Minimum conditions to move to `GO`:

1. All leaked secrets rotated and invalidated.
2. Git history scrubbed if secrets were committed.
3. Rate limiting implemented for intake and expensive commands.
4. SSRF protections fixed, including DNS TOCTOU handling.
5. Raw internal errors no longer exposed to users.
6. A safe staging environment exists with test credentials only.

### Open Auditor Questions

- Was `.env` ever committed to git history?
- Are CouchDB and webhook endpoints exposed publicly without a hardened reverse proxy?
- Why are `TG_API_ID` and `TG_API_HASH` present if the codebase does not use them directly?
- Will the multi-tenant configuration be part of the security test scope?
