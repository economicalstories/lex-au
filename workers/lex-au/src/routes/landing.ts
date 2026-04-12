/**
 * Mobile-optimised landing page for the lex-au Cloudflare Worker.
 *
 * Serves a static HTML page at `/` that:
 *   - Explains that lex-au is an unofficial MCP server over content sourced
 *     from the Federal Register of Legislation (legislation.gov.au).
 *   - Surfaces the deployed MCP endpoint URL (derived from the request host,
 *     so no hard-coded localhost/local callback URLs).
 *   - Shows the attribution wording required by the legislation.gov.au
 *     Terms of Use and links back to the original source.
 *   - Is responsive down to small (~320px) mobile viewports, uses system
 *     fonts, and ships zero client-side JavaScript fetches — the only JS is
 *     a single copy-to-clipboard helper that operates on inline strings.
 */
import { Hono } from "hono";
import type { Env } from "../env";

const LEGISLATION_SOURCE_URL = "https://www.legislation.gov.au";
const LEGISLATION_TERMS_URL = "https://www.legislation.gov.au/terms-of-use";

const landing = new Hono<{ Bindings: Env }>();

landing.get("/", (c) => {
  const url = new URL(c.req.url);
  // Derive the absolute, public MCP URL from the incoming request so we never
  // point users at a local callback like http://localhost:8787/mcp.
  const mcpUrl = `${url.origin}/mcp`;
  const today = new Date().toISOString().slice(0, 10);

  const html = renderLandingPage({ mcpUrl, today });
  return c.html(html);
});

interface LandingContext {
  mcpUrl: string;
  today: string;
}

function renderLandingPage({ mcpUrl, today }: LandingContext): string {
  const mcpConfig = JSON.stringify(
    {
      mcpServers: {
        "lex-au": {
          type: "http",
          url: mcpUrl,
        },
      },
    },
    null,
    2,
  );

  // Exact attribution wording from
  // https://www.legislation.gov.au/terms-of-use — "Based on content..."
  // is the required form when content has been transformed (we embed and
  // re-index it), which covers the search/MCP surface of this worker.
  const attributionLine = `Based on content from the Federal Register of Legislation at ${today}. For the latest information on Australian Government law please go to https://www.legislation.gov.au.`;

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="light dark" />
<meta name="referrer" content="no-referrer" />
<meta name="description" content="lex-au is an unofficial Model Context Protocol (MCP) server over Australian federal legislation. Content is sourced from the Federal Register of Legislation at legislation.gov.au." />
<title>lex-au — Australian Legislation MCP</title>
<style>
  :root {
    --bg: #ffffff;
    --fg: #0b1220;
    --muted: #4b5563;
    --border: #e5e7eb;
    --accent: #0b4f8b;
    --accent-fg: #ffffff;
    --code-bg: #f4f6fa;
    --callout-bg: #fff8e1;
    --callout-border: #f4c430;
    --max: 720px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0b1220;
      --fg: #e5e7eb;
      --muted: #9ca3af;
      --border: #1f2937;
      --accent: #4f8fd0;
      --accent-fg: #0b1220;
      --code-bg: #111827;
      --callout-bg: #24210e;
      --callout-border: #b68800;
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg); }
  body {
    font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
          "Helvetica Neue", Arial, sans-serif;
    padding: max(env(safe-area-inset-top), 16px) 16px max(env(safe-area-inset-bottom), 24px);
    -webkit-text-size-adjust: 100%;
  }
  main { max-width: var(--max); margin: 0 auto; }
  header { padding: 8px 0 16px; }
  .eyebrow {
    display: inline-block;
    font-size: 12px;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 6px;
  }
  h1 {
    font-size: clamp(1.5rem, 4.2vw + 0.6rem, 2.15rem);
    line-height: 1.15;
    margin: 0 0 10px;
    letter-spacing: -0.01em;
  }
  h2 {
    font-size: 1.15rem;
    margin: 28px 0 8px;
    letter-spacing: -0.005em;
  }
  p { margin: 0 0 12px; color: var(--fg); }
  p.lede { color: var(--muted); font-size: 1.02rem; }
  a { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
  a:focus-visible, button:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: 4px;
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
    margin: 12px 0;
    background: var(--bg);
  }
  .mcp-url {
    display: flex;
    gap: 8px;
    align-items: stretch;
    flex-wrap: wrap;
  }
  .mcp-url code {
    flex: 1 1 220px;
    min-width: 0;
    word-break: break-all;
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 0.95rem;
  }
  button.copy {
    flex: 0 0 auto;
    min-height: 44px;
    padding: 0 14px;
    border-radius: 8px;
    border: 1px solid var(--accent);
    background: var(--accent);
    color: var(--accent-fg);
    font-weight: 600;
    font-size: 0.95rem;
    cursor: pointer;
  }
  button.copy:active { transform: translateY(1px); }
  pre {
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    overflow-x: auto;
    font-size: 0.88rem;
    -webkit-overflow-scrolling: touch;
  }
  pre code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  ul { padding-left: 1.2em; margin: 6px 0 12px; }
  li { margin: 4px 0; }
  .callout {
    background: var(--callout-bg);
    border-left: 4px solid var(--callout-border);
    border-radius: 6px;
    padding: 12px 14px;
    margin: 16px 0;
    font-size: 0.95rem;
  }
  .callout strong { display: block; margin-bottom: 4px; }
  .attribution {
    font-size: 0.9rem;
    color: var(--muted);
    border-top: 1px solid var(--border);
    margin-top: 28px;
    padding-top: 16px;
  }
  .attribution p { color: var(--muted); }
  .disclaimer {
    font-size: 0.85rem;
    color: var(--muted);
  }
  @media (max-width: 480px) {
    body { padding-left: 14px; padding-right: 14px; }
    .card { padding: 12px; }
    pre { font-size: 0.82rem; }
  }
</style>
</head>
<body>
<main>
  <header>
    <span class="eyebrow">lex-au</span>
    <h1>Australian federal legislation over MCP</h1>
    <p class="lede">
      An unofficial <a href="https://modelcontextprotocol.io/" rel="noopener noreferrer">Model Context Protocol</a>
      server for searching and retrieving Australian federal Acts and
      legislative instruments. Content is sourced from the
      <a href="${LEGISLATION_SOURCE_URL}" rel="noopener noreferrer">Federal Register of Legislation</a>
      (legislation.gov.au).
    </p>
  </header>

  <section aria-labelledby="connect">
    <h2 id="connect">Connect an MCP client</h2>
    <p>Point your MCP client at this hosted endpoint — there is no local callback to configure:</p>
    <div class="card mcp-url">
      <code id="mcp-endpoint">${escapeHtml(mcpUrl)}</code>
      <button class="copy" type="button" data-copy-target="mcp-endpoint" aria-label="Copy MCP endpoint URL">Copy</button>
    </div>
    <p>Drop this block into your client's MCP config (Claude Desktop, Claude Code, Cursor, VS Code, etc.):</p>
    <pre><code id="mcp-config">${escapeHtml(mcpConfig)}</code></pre>
    <p style="margin-top:8px">
      <button class="copy" type="button" data-copy-target="mcp-config" aria-label="Copy MCP client configuration">Copy config</button>
    </p>
  </section>

  <section aria-labelledby="ops">
    <h2 id="ops">Operations</h2>
    <p>Need to validate corpus indexing status quickly? Open the <a href="/coverage">coverage dashboard</a>.</p>
  </section>

  <section aria-labelledby="tools">
    <h2 id="tools">What the MCP server exposes</h2>
    <ul>
      <li><code>search_for_au_legislation_acts</code> — search Acts and legislative instruments by topic.</li>
      <li><code>search_for_au_legislation_sections</code> — semantic section-level search, optionally scoped to one Act.</li>
      <li><code>lookup_au_legislation</code> — exact lookup by type, year and number.</li>
      <li><code>get_au_legislation_sections</code> — list provisions for a specific Act or instrument.</li>
      <li><code>get_au_legislation_full_text</code> — full text concatenated from all sections.</li>
    </ul>
  </section>

  <div class="callout" role="note">
    <strong>Source of truth is legislation.gov.au</strong>
    The authoritative, up-to-date text of every Commonwealth Act and instrument
    lives at <a href="${LEGISLATION_SOURCE_URL}" rel="noopener noreferrer">${LEGISLATION_SOURCE_URL}</a>.
    Always follow the link back to the original compilation before relying on
    the text for legal purposes.
  </div>

  <section class="attribution" aria-labelledby="attribution-heading">
    <h2 id="attribution-heading">Attribution &amp; terms of use</h2>
    <p>
      Content served through this MCP server is derived from the
      <a href="${LEGISLATION_SOURCE_URL}" rel="noopener noreferrer">Federal Register of Legislation</a>
      and is reused under the
      <a href="${LEGISLATION_TERMS_URL}" rel="noopener noreferrer">legislation.gov.au Terms of Use</a>.
      By using this service you also agree to those terms.
    </p>
    <p>
      Required attribution statement:
    </p>
    <pre><code id="attribution-line">${escapeHtml(attributionLine)}</code></pre>
    <p class="disclaimer">
      lex-au is not operated by, endorsed by, or affiliated with the Office of
      Parliamentary Counsel, the Attorney-General's Department, or the
      Australian Government. It is an independent, experimental project and
      must not be relied upon as a substitute for the official text on
      <a href="${LEGISLATION_SOURCE_URL}" rel="noopener noreferrer">legislation.gov.au</a>.
    </p>
  </section>
</main>

<script>
  // Minimal copy-to-clipboard: operates purely on inline DOM strings. It does
  // not make any network requests, so there are no local REST callbacks from
  // this page — all interactive use flows through the MCP endpoint above.
  document.addEventListener("click", function (ev) {
    var target = ev.target;
    if (!(target instanceof HTMLElement)) return;
    var btn = target.closest("button.copy");
    if (!btn) return;
    var id = btn.getAttribute("data-copy-target");
    if (!id) return;
    var el = document.getElementById(id);
    if (!el) return;
    var text = el.textContent || "";
    var done = function () {
      var original = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(function () { btn.textContent = original; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { done(); });
    } else {
      var range = document.createRange();
      range.selectNodeContents(el);
      var sel = window.getSelection();
      if (sel) { sel.removeAllRanges(); sel.addRange(range); }
      try { document.execCommand("copy"); } catch (e) { /* noop */ }
      if (sel) sel.removeAllRanges();
      done();
    }
  });
</script>
</body>
</html>`;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export { landing, LEGISLATION_SOURCE_URL, LEGISLATION_TERMS_URL };
