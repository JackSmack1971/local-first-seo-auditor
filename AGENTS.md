Agent Development Best Practices for the Local‑First SEO Auditor
This document collects actionable guidelines for building the local‑first SEO auditor described in the Product Requirements Document (PRD) and Functional Requirements Document (FRD). It is intended for autonomous coding agents and should eliminate open questions. The recommendations reflect current best practices in Python/Rust (2025) and reference authoritative sources.
1. Architectural Overview
1.1 High‑Level Architecture
The application follows a local‑first architecture:
Frontend: A Tauri 2.x desktop shell with a React user interface. All user actions occur locally and are authenticated via a PIN gate (argon2id with 64 MB memory, 3 passes, 16‑byte salt). UI strings are externalized into i18n/*.json for localisation.
IPC layer: HTTP requests over 127.0.0.1:8787 secured by request signing. Each session generates a 32‑byte nonce and HMAC key stored in the OS keyring. The client sends X‑Nonce and X‑Signature = HMAC_SHA256(nonce || path || body) for each request. The server recomputes and uses hmac.compare_digest() to prevent timing attacks[1].
Backend: A FastAPI server orchestrates jobs and exposes endpoints for crawling, auditing, topic exploration, link analysis and AI artifacts (§14 of the PRD). Worker processes perform CPU‑bound and I/O‑bound tasks concurrently using asyncio. Use a single httpx.AsyncClient per worker and never instantiate clients inside hot loops to maximize connection reuse[2].
Storage: DuckDB stores facts (crawled URL data, audit metrics, link edges). SQLite stores jobs, staging queues, metrics and AI caches. Parquet is used for exports. A single writer drains the staging queue into DuckDB to avoid lock contention (§6.1 Option A). If T‑STRESS‑WRITE‑001 shows p95 staging wait > 500 ms, switch to Option B (direct writes).
Workers: Dedicated asynchronous workers handle modules (crawl, audit, topics, links, AI). Each run is tracked in the jobs table with state transitions (PENDING → STARTING → RUNNING → SUCCEEDED/FAILED/…).
1.2 Concurrency and Rate‑Limiting
HTTP crawling uses asynchronous requests via httpx.AsyncClient. Limit concurrency with a semaphore to avoid overloading hosts: create semaphore = asyncio.Semaphore(MAX_CONCURRENCY) outside your fetch function, and wrap each request in async with semaphore:[3]. This pattern ensures only MAX_CONCURRENCY simultaneous requests.
To honour the per‑host token bucket (0.5 requests per second with burst 1) and adapt to CPU usage (§3.1), wrap outgoing requests in aiolimiter.AsyncLimiter or aiometer.amap, specifying max_at_once and max_per_second[4]. Log throttling events and decrease concurrency when psutil.cpu_percent(interval=1) > 85 % for 60 s.
Always pass limits = httpx.Limits(max_connections=N, max_keepalive_connections=M) to the AsyncClient. The PRD sets HTTP_CONCURRENCY = 16 and Playwright_TABS = 2 as defaults (§7). A global AsyncClient with http2=True and timeout values tuned for slow pages provides backpressure and connection reuse.[5].
Use asyncio.TaskGroup (Python 3.11+) for structured concurrency. This ensures that if one task fails, sibling tasks are cancelled and exceptions are propagated deterministically. Combined with semaphores, it creates predictable cancellation semantics.
1.3 Browser Automation (Playwright)
Playwright handles JavaScript‑dependent pages and performance metrics (LCP, INP, CLS). Long‑running sessions can cause memory leaks; adhere to these guidelines:
Proper context and page management: Always close pages and contexts when done. Use an async with async_playwright() block, create a context for each logical session, and call await page.close() and await context.close() in a finally clause before closing the browser[6].
Context recycling pattern: Do not reuse a single context forever. Instead, create a wrapper (PlaywrightSessionManager) that recycles contexts after a fixed number of pages (e.g., 10). When the threshold is reached, close the current context and create a new one[7].
Resource blocking: Disable unnecessary resources (images, stylesheets, fonts) to conserve memory. In Python, register a route handler via await context.route('**/*', block_resources) where block_resources aborts requests for specific resource types[8].
Memory monitoring: Periodically inspect memory usage and restart the browser when thresholds are crossed. For Node examples, the article shows checking process.memoryUsage() and restarting when heap usage exceeds 512 MB[9]. In Python, you can use tracemalloc or psutil to monitor RSS and trigger context recycling.
Page navigation patterns: Reuse a single page instance when iterating through multiple URLs. Clear event listeners and timers after each navigation to avoid memory leaks[10].
Launch options: Headless mode with flags such as --disable-gpu, --disable-background-timer-throttling and --disable-dev-shm-usage reduces resource usage[11]. Set max_old_space_size to bound Node’s memory; in Python, rely on OS limits and restart contexts.
1.4 Data Flow and Determinism
Follow deterministic ordering throughout the pipeline:
Sort URLs and seeds before processing.
When writing facts to DuckDB, maintain stable column ordering and null timestamps for determinism (§1.3). Use duckdb.register() to ingest Pandas DataFrames and COPY TO parquet for exports.
Use idempotent upserts keyed by (run_id, url) to avoid duplicates (§6.2).
2. Security and Privacy Practices
2.1 Request Signing and Authentication
HMAC signature: The client should compute signature = hmac.new(secret_key, message, hashlib.sha256).hexdigest() and send it in an X‑Signature header. The server must recompute the signature using the same secret and compare using hmac.compare_digest()[12]. Never use == for string comparison to avoid timing attacks[13].
Nonce rotation: Each session uses a unique 32‑byte nonce. The backend rotates the nonce every 30 minutes or when the user reauthenticates. Reject requests with missing or invalid X‑Nonce or X‑Signature (§6). Log trace IDs for correlation.
Secret management: Store HMAC keys and API credentials in the OS keyring. Only store variable names (not values) in .env.local (§12). Use Argon2id for PIN hashing with memory hardening (m=64 MB, t=3, p=1).
PII redaction: Before sending data to AI models or writing logs, redact emails, phone numbers and tokens per §12. Use regex patterns to find RFC 5322 email addresses and E.164 phone numbers, and replace them with [REDACTED]. Canonicalize unicode to avoid homoglyph attacks.
2.2 Transport Layer and CSP
Bind the FastAPI server to 127.0.0.1 only. Do not expose it on public interfaces. Use an unprivileged port (8787).
Add a strict Content Security Policy (CSP) in the Tauri front‑end: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' http://127.0.0.1:8787; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; (§12). This prevents injection of external scripts.
All critical actions (deleting projects, exporting data, changing API keys, enabling Common Crawl, increasing AI budget > $10) must be gated behind the PIN prompt (§12). Rate‑limit PIN attempts (5 attempts per 10 min; 10 min lockout on failure).
2.3 Error Handling and Circuit Breakers
Wrap external API calls (Wikimedia, pytrends, OpenRouter) in circuit breakers. A simple pattern is a sliding window counter: open the circuit after 5 failures in 60 s; half‑open after 60 s; reset on success (§11). For Python, the pybreaker library provides this mechanism.
Use exponential backoff for retries: 1 s, 3 s, 7 s (max 3 attempts). Only retry transient errors (HTTP 429, 503, connection timeout). Do not retry 4xx responses except 429. Sleep between retries and respect Retry-After headers where provided.
On AI failures, perform up to three repair attempts (sending the previous invalid output back to the model). If still invalid, set the artifact status to DEGRADED:AI and include partial results (§8.4).
3. Crawling and Auditing
3.1 Hybrid Crawl Engine
Input handling: Accept either a sitemap.xml URL or a manual list of seed URLs. Validate host names and remove duplicates. Parse robots.txt per host; respect Disallow and Crawl‑delay. Use a token bucket per host (0.5 req/s, burst 1) and global concurrency of 16.
HTTP‑first phase: Use asyncio.TaskGroup to schedule HTTP requests via httpx.AsyncClient. Parse HTML with trafilatura or selectolax to extract titles, meta tags, headings, canonicals, hreflang, and internal links. Compute word count and text density to detect likely SPAs. Cache whether each domain requires JS rendering to avoid repeated Playwright runs.
SPA detection: Flag pages for Playwright if any of the following are true: presence of framework markers (attributes like data-reactroot, ng-version, vue), low text density (text length / HTML length < 0.15), or prior cached JS requirement.
Playwright escalation: For flagged pages, launch a Playwright browser (Chromium) with at most two concurrent tabs. Wait for network idle (≤ 2 ongoing connections for ≥ 500 ms), then extract SEO elements and optional lab metrics. Recycle tabs every 100 pages to avoid memory leaks (§7). Use the context recycling pattern and resource blocking described above to manage memory[6][7].
Caching and retries: Store the JS requirement per domain in SQLite. Retry transient failures using exponential backoff. For SPA pages that repeatedly time out, record render_timeout=true and skip further attempts.
3.2 Audit Rule Framework
Rule structure: Each audit rule is a class or dataclass with fields: id, name, category, impact_model, severity_calc, evidence_extractor, auto_fixable, acceptance_criteria (§3.1). The severity_calc returns an enum {Critical, High, Medium, Low}. The evidence_extractor returns an object containing url, field, value, rationale (for example, the missing <title> element and why it matters).
Implementation guidelines:
Use a factory to register all rule classes and allow dynamic selection by category or priority.
Each rule operates on a PageDocument object containing the parsed HTML, metrics and meta information.
Use pure functions or static methods for predicates to simplify unit tests.
When auto‑fixable, include suggested fix in the AI action plan schema (e.g., recommending a canonical tag or descriptive title).
Compute severity consistently; for example, missing <title> is always Critical, whereas thin content may be Medium depending on word count threshold.
Write golden fixtures for 10 pages and assert pass/fail outcomes for each rule.
Delta comparison: After each audit run, join current and previous results on (url, rule_id) and classify issues as Added, Removed, Changed or Stable (§3.1). Exclude timestamps from comparisons. Display deltas in the UI with colour coding and allow export to CSV/JSON.
3.3 Performance Guardrails
Page budget: Default to 5 000 pages per crawl. Warn when JS pages exceed 20 %; prompt user to reduce budget or run per‑host batches. If CPU > 85 % or memory > 90 % for 60 s, reduce concurrency and alert via UI banners (§7). Use psutil to check memory and CPU usage.
Disk usage: Check free disk before starting; warn at 15 GB remaining; hard stop at 20 GB. Clean up WAT files immediately after processing Common Crawl data.
Watchdogs: Implement a watchdog thread that terminates orphaned Playwright processes after 5 minutes (§7). Recycle browser instances every 100 pages.
4. Topic Exploration
4.1 Seed Terms and Data Sources
Accept comma‑separated or multi‑line seed terms (minimum 1, maximum 50). Normalize case and trim whitespace. Save seeds along with run metadata (§3.2).
Wikipedia Pageviews: Use Wikimedia REST API with aiolimiter to enforce ≤ 10 requests/s. Fetch the last 90 days of pageview data. Normalize signals using log‑scale transformation. Implement a circuit breaker for repeated failures (§3.2).
Google Trends (pytrends): Off by default; require the user to enable via settings and PIN (opt‑in). Use pytrends 4.9.1; limit to 1 request every 5 s. Provide fallback to cached data if the API fails.
4.2 Clustering and Brief Generation
Mini‑batch K‑Means: Use scikit‑learn’s MiniBatchKMeans (version 1.6+). The algorithm processes small random batches of data rather than the entire dataset, updating cluster centroids based on each batch[14]. This reduces computation and memory usage at the expense of a slight loss in cluster quality[15]. The process repeats until convergence or a maximum number of iterations[16]. Determine the optimal number of clusters via the elbow method or user input.
Represent terms using numeric features such as normalized pageviews and trend scores. Fit MiniBatchKMeans on these features and assign cluster IDs.
For each cluster, compute representative terms (highest average score), determine search intent (informational/commercial/transactional/navigational), and attach seasonality notes. Use question extraction to gather interrogatives from Wikipedia sections; extract up to 10 unique questions per cluster using regex patterns (who|what|when|where|why|how).
Content briefs: Generate a Markdown brief per cluster containing the cluster name, intent, representative terms, seasonality, related questions and a suggested outline (H2/H3). The AI model can generate this under strict JSON schema defined in §8.2. Validate with Pydantic (extra='forbid').
5. Link Graph and PageRank
5.1 Internal Link Extraction
During the crawl, extract every <a href> attribute, normalize URLs (scheme, case, trailing slash, remove fragments), and filter to same‑domain links. Exclude self‑links. Store edges with src, dst, first_seen and last_seen timestamps in link_edge table.
After ingesting edges, compute inbound/outbound counts per URL. Identify orphan pages (no inbound links) and assign them the AUD‑LINK‑001 violation; exclude the homepage from orphan detection (§3.3).
5.2 PageRank Calculation
Use NetworkX 3.5’s pagerank implementation. Set damping factor 0.85, tolerance 1e‑6 and maximum 100 iterations (§3.3). If the number of edges exceeds 50 k, aggregate to host‑level: group edges by (src_host, dst_host), compute PageRank on the host graph, then distribute scores back to pages proportionally to their internal degree. Record convergence status and iterations.
Persist PageRank scores in host_rank and url_doc tables with update timestamps. Warn in the UI when switching to host‑level PageRank.
5.3 Common Crawl (Opt‑In)
When enabled (PIN‑gated), download a ≤ 200 MB WAT file. Check that free disk ≥ 5 GB; abort if not. Stream parse the Links section; filter to hosts present in the current project. Stop after 1 M rows or 5 minutes. Delete the WAT file after parsing.
6. AI Reasoning and Caching
Use OpenRouter (or compatible) with strict JSON schemas for Action Plans, Cluster Labels and Internal Link Recommendations (§8). Include prompt version and facts hash in the cache key. Limit the model temperature to ≤ 0.3 and tokens to the minimal necessary. Always echo the JSON schema in the prompt and instruct the model to produce no extra fields.
Validate the AI response with Pydantic (extra='forbid'). On validation errors, attempt up to three repairs by informing the model of the exact schema mismatch and resubmitting. If all attempts fail, mark the artifact as DEGRADED:AI and include partial results.
Cache AI responses in SQLite keyed by (model, version, prompt_version_hash, facts_hash) with a TTL of 7 days (§15). Do not exceed the configured AI budget; estimate cost by (tokens_in * $/1k_in + max_tokens_out * $/1k_out) and display the estimate before execution (§20). Limit AI parallelism to 2 concurrent calls.
7. Observability and Testing
Structured logging: Emit JSON lines with ts, level, trace_id, run_id, job_id, stage, event, url, latency_ms, err_code, err_msg, and additional meta fields. Include X‑Trace‑Id from the client in all backend logs.
Metrics: Record crawl pages total, errors total, RPS, AI tokens, AI cost, queue depth, disk used, PageRank iterations, memory and CPU usage (§9). Expose a lightweight dashboard at /metrics/ui and /logs/ui for local viewing. Compute SLO attainment hourly and trigger banners at 50 % and 100 % error budget consumption (§16).
Testing strategy: Implement unit tests for each rule (20+ scenarios), integration tests for crawl→staging→DuckDB ingestion, and end‑to‑end tests for each run type (crawl/audit/topics/links/AI). Use golden fixtures to verify determinism (byte‑compare after nulling timestamps). Stress test with 5 000 pages (80 % static, 20 % JS) to ensure completion within 1 800 s (§7). Chaos tests should simulate API failures, network cuts, worker crashes and database locks (§17, §18).
8. Coding Standards and Practices
Language versions: Use Python 3.11+ for workers (enables TaskGroup, tomllib and pattern matching). Use Rust 1.70+ for the Tauri shell. Ensure code is formatted with black and typed with mypy (strict optional). Use Ruff or Flake8 for linting.
Dependency management: Pin dependencies using pip‑tools with --generate‑hashes. Maintain a CycloneDX SBOM. Audit dependencies with pip‑audit and update quarterly (§12).
Database access: Use parameterized SQL (via duckdb.Cursor.execute) to prevent injection. Avoid mixing sync and async DB operations. Use aiosqlite for SQLite and duckdb for DuckDB. Wrap writes in transactions and commit only after the entire batch is processed.
Thread and process safety: Avoid global state in workers. Use asyncio.Lock or asyncio.Semaphore to protect shared resources (e.g., AI budget). When using multiprocessing (for CPU‑heavy tasks like HTML parsing), ensure tasks are idempotent and results are sent back via queues.
Determinism: Always sort keys when iterating dictionaries. When serialising JSON, pass sort_keys=True and ensure_ascii=False to get consistent ordering.
Documentation: Document each module, class and function with docstrings and type hints. Provide usage examples and link to sections of this guide. Maintain README.md per sub‑package and keep the root CHANGELOG.md updated with semantic versioning.
9. Example Code Snippets
9.1 HMAC Request Signing (Client and Server)
import hmac
import hashlib
from fastapi import FastAPI, Request, HTTPException

SECRET = b"supersecretkey"

def sign_request(nonce: bytes, path: str, body: bytes) -> str:
    """Compute HMAC‑SHA256 over nonce||path||body."""
    message = nonce + path.encode("utf‑8") + body
    return hmac.new(SECRET, message, hashlib.sha256).hexdigest()

# Client side
nonce = os.urandom(32)
body = json.dumps(payload, separators=(",", ":")).encode("utf‑8")
signature = sign_request(nonce, "/crawl/run", body)
headers = {
    "X‑Nonce": base64.b64encode(nonce).decode(),
    "X‑Signature": signature,
    "X‑Trace‑Id": str(uuid.uuid4()),
}
async with httpx.AsyncClient() as client:
    resp = await client.post("http://127.0.0.1:8787/crawl/run", headers=headers, json=payload)

# Server side (FastAPI)
app = FastAPI()

@app.post("/crawl/run")
async def crawl_run(request: Request):
    nonce_b64 = request.headers.get("X‑Nonce")
    signature = request.headers.get("X‑Signature")
    if not nonce_b64 or not signature:
        raise HTTPException(401, detail="Missing signature")
    nonce = base64.b64decode(nonce_b64)
    body = await request.body()
    path = request.url.path
    expected = sign_request(nonce, path, body)
    # Use compare_digest to prevent timing attacks[12]
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, detail="Invalid signature")
    # Continue processing request
    ...
9.2 Concurrency‑Limited Fetcher
import asyncio
import httpx
from typing import Any, Dict

BASE_URL = "https://example.com/api"
MAX_CONCURRENCY = 16  # configured per PRD

semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

async def fetch(client: httpx.AsyncClient, endpoint: str) -> Dict[str, Any]:
    async with semaphore:  # limit concurrent requests[3]
        response = await client.get(f"{BASE_URL}{endpoint}", timeout=30)
        response.raise_for_status()
        return response.json()

async def main():
    async with httpx.AsyncClient(http2=True, limits=httpx.Limits(max_connections=MAX_CONCURRENCY)) as client:
        tasks = [fetch(client, f"/resource/{i}") for i in range(100)]
        results = await asyncio.gather(*tasks)
        print(results)

asyncio.run(main())
9.3 Playwright Context Recycling
from playwright.async_api import async_playwright
import asyncio

class SessionManager:
    def __init__(self, max_pages_per_context: int = 10):
        self.browser = None
        self.context = None
        self.page_count = 0
        self.max_pages = max_pages_per_context

    async def start(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=True)
        await self._new_context()

    async def _new_context(self):
        if self.context:
            await self.context.close()
        self.context = await self.browser.new_context()
        self.page_count = 0

    async def get_page(self):
        if self.page_count >= self.max_pages:
            await self._new_context()
        self.page_count += 1
        return await self.context.new_page()

    async def close(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        await self.pw.stop()

async def scrape_urls(urls):
    manager = SessionManager(max_pages_per_context=10)
    await manager.start()
    try:
        for url in urls:
            page = await manager.get_page()
            await page.goto(url)
            # Extract data
            title = await page.title()
            print(url, title)
            await page.close()  # clean up resources[6]
    finally:
        await manager.close()

asyncio.run(scrape_urls(["https://example.com", "https://example.org"]))
9.4 Mini‑Batch K‑Means for Topic Clustering
import numpy as np
from sklearn.cluster import MiniBatchKMeans

def cluster_topics(features: np.ndarray, n_clusters: int = 8) -> np.ndarray:
    """Cluster topics using Mini‑Batch K‑Means.

    Parameters
    ----------
    features : (n_samples, n_features) array of normalized signals
    n_clusters : int, number of clusters to form

    Returns
    -------
    labels : array of cluster assignments
    """
    kmeans = MiniBatchKMeans(n_clusters=n_clusters, batch_size=1024, random_state=42)
    kmeans.fit(features)
    return kmeans.labels_

# Example usage: cluster 100 topics based on log‑scaled pageviews and trends
features = np.random.rand(100, 2)
labels = cluster_topics(features, n_clusters=5)
The MiniBatchKMeans algorithm processes small random batches of data instead of the entire dataset, updating cluster centroids on each mini‑batch[14]. This technique reduces memory and computation time at the cost of a slight loss in cluster quality[15].
10. Future Considerations
Windows/WSL performance: Benchmark the crawler on Windows 11 and WSL 2. If WSL is ≥ 20 % faster, recommend WSL as the default environment (§19). Document known differences (file system latency, networking, Playwright installation) and provide guidance for enabling WSL.
Code signing: Plan for Windows code signing by Milestone 5. Until then, display the installer’s SHA‑256 hash in the UI (§12).
OpenAI replacement: The PRD mentions OpenRouter but future AI models may differ. Abstract the AI client behind an interface that accepts prompt, facts and schema and returns a validated response. This allows swapping providers without changing the rest of the system.
By following the practices outlined above, coding agents can implement the SEO auditor with confidence, ensuring privacy, security, performance and maintainability.
11. Dev Environment Setup and Commands
The AGENTS.md format is designed to give coding agents all of the context they need to build and test the project. This section provides concrete commands to set up the development environment, run tests, and follow the correct workflow. Do not run production build commands inside interactive agent sessions; they disable hot reloading and can leave the dev server in an inconsistent state[17].
11.1 Setup Commands
Install system prerequisites:
Install the latest Rust toolchain (rustup install stable) and the Tauri CLI (cargo install tauri-cli).
Install Node.js (v18+ recommended) and a package manager such as pnpm (npm install -g pnpm) or npm.
Install Python 3.11+ and create a virtual environment: python -m venv .venv && source .venv/bin/activate.
Install dependencies:
Frontend (React + Tauri shell): pnpm install or npm install from the project root. This installs all Node dependencies and prepares the Tauri frontend.
Backend (FastAPI workers and Python modules): pip install -r requirements.txt inside the virtual environment.
Rust packages: cargo build will fetch and build Rust crates as needed.
Start the development server:
Frontend & backend hot reload: run pnpm tauri dev (or npm run tauri dev) to launch the Tauri application in development mode with hot reload for both the React frontend and the Rust shell. Alternatively, use separate terminals: pnpm dev to run the React UI and cargo tauri dev to run the Rust/Tauri host. Do not run the production build (pnpm build or cargo build --release) during interactive agent sessions[18].
Backend API only: if you wish to develop the API without the UI, run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8787 after activating the virtual environment.
11.2 Useful Commands Recap
Command
Purpose
pnpm tauri dev
Launch the Tauri application with hot reload for frontend and backend.
pnpm dev
Start the React dev server (if working on frontend only).
cargo tauri dev
Compile and run the Rust/Tauri shell with live reload.
python -m uvicorn ...
Run the FastAPI backend with auto‑reload for API development.
pytest
Execute the Python test suite.
pnpm test
Run frontend tests (if present, e.g., Vitest or Jest).
pnpm lint
Run ESLint checks on the frontend TypeScript/JavaScript code.
ruff check . / black
Lint and format Python code.
mypy .
Run static type checking on Python modules.
cargo clippy
Lint Rust code and enforce style guidelines.

12. Code Style and Conventions
Maintaining consistent code style across languages helps agents understand and modify the codebase. Adopt the following conventions:
TypeScript/JavaScript: Use strict mode and single quotes with no semicolons, matching the conventions of the AGENTS.md example[19]. Configure Prettier and ESLint to enforce these rules. Prefer TypeScript (.tsx/.ts) over plain JavaScript for new components and utilities[20]. Co‑locate component‑specific styles in the same folder as the component when practical[20].
Python: Format code with black and enforce typing with mypy --strict. Use ruff or flake8 to catch unused imports and style issues. Prefer pure functions and composition over mutable state.
Rust: Follow Rustfmt’s default style. Use Clippy to catch common mistakes and adopt idiomatic patterns (e.g., use iterators, avoid unnecessary cloning). Document all public functions and modules.
Commit messages & branches: Use descriptive commit messages (imperative mood, present tense). For pull requests, prefix the title with the subsystem (e.g., [crawl] Add token‑bucket limiter) and include a summary of changes and test coverage. Always run pnpm lint, pnpm test and pytest before pushing[21].
Dependency updates: When adding or updating dependencies in the Node/TypeScript code, ensure the appropriate lockfile (pnpm-lock.yaml, package-lock.json or yarn.lock) is updated and committed. After modifying dependencies, restart the development server so that changes take effect[22]. Use pinned versions and regenerate the Python requirements.txt via pip‑tools to keep environments reproducible.
13. Testing and Continuous Integration
Testing is critical for agent‑driven development. Follow these instructions to ensure new code maintains quality:
Unit tests: Write tests for individual functions, classes and audit rules. Use pytest for Python and appropriate frameworks for Rust (cargo test) and React (Vitest or Jest). Strive for ≥ 80 % coverage (§17).
Integration tests: Simulate full runs (crawl→staging→DuckDB; topics; links; AI). Use golden fixtures to verify deterministic outputs. For UI tests, consider using Playwright to simulate button clicks and verify results tables.
End‑to‑end tests: Execute workflows (J1–J3 from the PRD) in an isolated environment. Ensure the metrics and logs align with SLOs.
Continuous integration (CI): Configure a GitHub Actions workflow that installs dependencies, runs pnpm tauri dev in headless mode (or uses a tauri-action), executes the test suites and lints code. Fail the build on any error. Keep lockfiles (package-lock.json, pnpm-lock.yaml) in sync when adding or updating dependencies[22].
Before merging: Always run local tests and lint checks. Fix any failing tests or type errors until the entire suite is green[23]. Update or add tests for any new functionality[24].
14. PR Title & Description
• Title format:
feat(scope): short summary (Conventional Commits) → enables automatic releases & changelogs. (conventionalcommits.org)
• Description sections (all required unless N/A):
• Context: link PRD/FRD issues & related tickets.
• Change Summary: what & why (design trade-offs).
• Risk & Impact: user-visible, infra, data, privacy.
• Security Notes: secrets, PII handling, crypto/HMAC, authz. Map to checklist below. (OWASP)
• Performance: expected deltas vs. budgets; micro/benchmark evidence if perf-sensitive. (Google GitHub)
• Testing: unit/integration/e2e added/updated; failure cases; repro steps. (Google GitHub)
• Migration/DB: schema changes, backfills, feature-flag strategy, rollback plan. (abseil.io)
• Screens/Snaps: UI diffs, API examples, logs if applicable.
• Docs: files updated (README, AGENTS.md, ADRs).
• Release note (user-facing): one concise line.
Why CC + SemVer? Conventional Commits → machine-readable intent; dovetails with SemVer for automated versioning and breaking-change detection. (conventionalcommits.org)
3) Author Pre-Flight (before “Ready for Review”)
• CI passes: tests, lint, format, type-check.
• JS/TS: ESLint, Prettier, tsc; Python: Ruff, Black, Pyright; Rust: Clippy, rustfmt.
• Coverage floor upheld (e.g., ≥90% lines/branches on touched paths) with meaningful tests (negative paths). (Google GitHub)
• Security gates:
• Static analysis (e.g., CodeQL), dependency audit, secret-scan, SBOM build (CycloneDX/SPDX), license check.
• OWASP quick checks: input validation, authn/z, crypto, logging, data protection. (OWASP)
• Privacy: PII redaction in logs; keys via env/secret manager; HMAC signature code paths tested. (OWASP)
• Performance budget: run micro/bench tests if touching hot paths; attach result snippet. (Google GitHub)
• Docs updated: AGENTS.md/README/CHANGELOG as needed.
• Branch hygiene: branch up-to-date with main; no unrelated file churn.
• Draft first: open as Draft PR until all gates green, then mark Ready. (Supported by GitHub templates & statuses.) (GitHub Docs)
4) Reviewer Rubric
Reviewers verify what changed and why it’s correct, using this order:
• Design & correctness: architecture fit, failure modes, invariants, concurrency & idempotency. (Google GitHub)
• Security & privacy: OWASP categories, secrets handling, permissions, data flows, PII minimization. (OWASP)
• Performance & resource use: complexity, memory, I/O; budgets/regressions. (Google GitHub)
• Tests: coverage quality (happy + sad paths), determinism, meaningful assertions. (Google GitHub)
• Readability & maintainability: names, comments, docs, smaller functions, fewer side effects. (Google GitHub)
Comment style: specific, actionable (“Consider extracting X to Y because Z”), label nitpicks; avoid bikeshedding; keep tone respectful. (Google GitHub)
SLA: first response ≤ 24h; subsequent turns ≤ 24h until merge.
5) Security Checklist (attach in PR)
• Input validation & output encoding where appropriate.
• Authn/authz enforced at all entry points; least privilege.
• Cryptography: vetted libs, correct modes, key mgmt; HMAC signatures verified & tested.
• Error handling avoids sensitive leakage; logs scrub PII/secrets.
• Data at rest & in transit protected; secure cookies; CSRF where needed.
• Dependencies scanned; licenses compatible; no known vulns.
• Add/confirm threat-model notes if touching auth/data plane. (OWASP)
6) Performance Guardrails
• Declare the budget (latency/CPU/mem/allocs) for affected endpoints/functions.
• Provide before/after benchmark or representative load test for hot paths; include sample dataset sizes.
• Flag potential N+1 queries, cache strategy, back-pressure behavior.
(Rationale and approach align with code-health guidance: keep future change cost low by catching perf issues in review.) (Google GitHub)
7) Labels, Ownership & Approvals
• CODEOWNERS: at least one owner must approve for owned paths. (GitHub Docs)
• Required labels: type:feat|fix|chore|docs, risk:low|med|high, area:<component>, breaking-change (if any).
• Approvals: 1–2 reviewers; 2 required for high-risk (security, migrations).
• Auto-assign reviewers via path rules; use Draft until ready. (GitHub Docs)
8) Merge, Versioning & Releases
• Merge strategy: Squash & merge with Conventional-Commit title → clean history, auto-generated release notes. (conventionalcommits.org)
• Versioning: follow SemVer 2.0.0; increment MAJOR for breaking changes, MINOR for features, PATCH for fixes. (Semantic Versioning)
• Post-merge: delete branch; CI tags release; changelog updated from commit metadata.
9) Templates (drop into repo)
9.1 .github/PULL_REQUEST_TEMPLATE.md
## Title feat(scope): short summary ## Context Link PRD/FRD issues and related tickets. ## Change Summary - What changed - Why (trade-offs & alternatives considered) ## Risk & Impact - User-facing impact: - Infra/data impact: - Rollout plan / flags: - **Rollback plan:** ## Security & Privacy - [ ] Input validation / encoding considered - [ ] Authn/Authz paths verified - [ ] Secrets/keys managed (no plaintext) - [ ] PII handling/log redaction reviewed - Notes: ## Performance - Budget(s): - Benchmarks/load test summary: ## Testing - [ ] Unit - [ ] Integration - [ ] E2E - Failure cases covered: - Repro/verification steps: ## Docs - [ ] README - [ ] AGENTS.md - [ ] ADR/Changelog ## Release note One line, user-facing.
9.2 CONTRIBUTING.md (excerpt)
### Commit Messages Follow Conventional Commits. Use `BREAKING CHANGE:` footer when applicable. ### PR Size Target ≤ 300 LOC net; otherwise split or justify ("Why single PR?"). ### Review SLA First response within 24h; mark PR as Draft until all CI checks pass.
9.3 Branch Protection (policy)
• Require status checks: tests, lint/format, type-check, SAST, dep-scan, SBOM, license check.
• Require 1–2 approvals; require CODEOWNERS; linear history; dismiss stale reviews on new commits. (GitHub Docs)

[1] [12] [13] Generate & Verify HMAC Signatures in Python, Node.js, Go - Authgear
https://www.authgear.com/post/generate-verify-hmac-signatures
[2] [5] Async Support - HTTPX
https://www.python-httpx.org/async/
[3] [4] David Gasquez
https://davidgasquez.com/async-batch-requests-python/
[6] [7] [8] [9] [10] [11] What are the memory management best practices when running long Playwright sessions? | WebScraping.AI
https://webscraping.ai/faq/playwright/what-are-the-memory-management-best-practices-when-running-long-playwright-sessions
[14] [15] [16] ML | Mini Batch K-means clustering algorithm - GeeksforGeeks
https://www.geeksforgeeks.org/machine-learning/ml-mini-batch-k-means-clustering-algorithm/
[17] [18] [20] [22] raw.githubusercontent.com
https://raw.githubusercontent.com/openai/agents.md/main/AGENTS.md
[19] [21] [23] [24] AGENTS.md
https://agents.md/
