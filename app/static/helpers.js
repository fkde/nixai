/**
 * Shared, pure DOM and string helpers used by the SPA.
 *
 * Anything in here MUST be stateless. Functions that touch `state` or
 * specific DOM elements belong in `app.js` (or a future feature module).
 *
 * Kept small on purpose so future modules can lift more helpers out of
 * `app.js` without breaking imports.
 */

const HTML_ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#039;",
  "`": "&#096;",
};

const HTML_ESCAPE_RE = /[&<>"'`]/g;

/**
 * Escape a value for safe inclusion inside HTML text or attribute context.
 * Accepts anything — coerces to string, then maps the unsafe characters.
 */
export function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(HTML_ESCAPE_RE, (char) => HTML_ESCAPES[char] || char);
}

/**
 * Strip control characters that have no place in user-visible text.
 * Preserves newlines, tabs, and other whitespace.
 */
export function stripControlChars(value) {
  return String(value ?? "").replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "");
}

/**
 * Cap string length defensively. Backend will also enforce a limit, but
 * trimming on the client keeps forms responsive and prevents accidental
 * megabyte pastes from reaching the API.
 */
export function clampLength(value, maxLength) {
  const text = stripControlChars(value);
  if (!Number.isFinite(maxLength) || maxLength <= 0) return text;
  return text.length > maxLength ? text.slice(0, maxLength) : text;
}

/**
 * Render markdown-flavoured inline syntax (bold, code spans, http links).
 * Defensive: everything starts escaped, so user input can never inject HTML
 * even if it contains `<script>` tags.
 */
export function formatInlineMarkdown(value) {
  // Pull code spans out of the *raw* string first. escapeHtml turns backticks
  // into `&#096;`, which would prevent the regex below from matching if we
  // escaped first. Tokens use plain ASCII so escapeHtml passes them through
  // unchanged on the next pass.
  const codeSpans = [];
  let html = String(value ?? "").replace(/`([^`]+)`/g, (_match, code) => {
    const token = `@@CODE_SPAN_${codeSpans.length}@@`;
    codeSpans.push(`<code>${escapeHtml(code)}</code>`);
    return token;
  });
  html = escapeHtml(html)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  codeSpans.forEach((code, index) => {
    html = html.replaceAll(`@@CODE_SPAN_${index}@@`, code);
  });
  return html;
}

/**
 * Render multi-line markdown into block HTML (paragraphs, lists, code blocks).
 * Same escape discipline as {@link formatInlineMarkdown}.
 */
export function formatContent(content) {
  const lines = String(content ?? "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let paragraph = [];
  let list = null;
  let codeBlock = null;

  const flushParagraph = () => {
    const text = paragraph.join(" ").trim();
    if (text) {
      blocks.push(`<p>${formatInlineMarkdown(text)}</p>`);
    }
    paragraph = [];
  };

  const closeList = () => {
    if (!list) return;
    blocks.push(
      `<${list.type}>${list.items.map((item) => `<li>${item}</li>`).join("")}</${list.type}>`,
    );
    list = null;
  };

  const addListItem = (type, text) => {
    flushParagraph();
    if (!list || list.type !== type) {
      closeList();
      list = { type, items: [] };
    }
    list.items.push(formatInlineMarkdown(text.trim()));
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (codeBlock) {
      if (trimmed.startsWith("```")) {
        blocks.push(`<pre><code>${escapeHtml(codeBlock.join("\n"))}</code></pre>`);
        codeBlock = null;
      } else {
        codeBlock.push(line);
      }
      continue;
    }

    if (trimmed.startsWith("```")) {
      flushParagraph();
      closeList();
      codeBlock = [];
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      closeList();
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = Math.min(heading[1].length + 2, 5);
      blocks.push(`<h${level}>${formatInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (ordered) {
      addListItem("ol", ordered[1]);
      continue;
    }

    const unordered = trimmed.match(/^[-*+]\s+(.+)$/);
    if (unordered) {
      addListItem("ul", unordered[1]);
      continue;
    }

    if (list && list.items.length > 0) {
      list.items[list.items.length - 1] += ` ${formatInlineMarkdown(trimmed)}`;
      continue;
    }

    paragraph.push(trimmed);
  }

  flushParagraph();
  closeList();
  if (codeBlock) {
    blocks.push(`<pre><code>${escapeHtml(codeBlock.join("\n"))}</code></pre>`);
  }
  return blocks.join("");
}

/**
 * Render plain user text with line breaks preserved but no markdown.
 */
export function plainTextContent(content) {
  return escapeHtml(String(content ?? "")).replace(/\n/g, "<br>");
}

/**
 * Find the offset up to which streamed markdown is "sealed" — i.e. consists
 * of fully completed blocks that won't change as more tokens arrive. A block
 * seals on a blank line (paragraphs, lists, headings) or on a closing ```
 * fence (code blocks). The remainder is the in-progress tail; the live
 * renderer can append the sealed prefix once and only re-render the tail.
 */
export function findStreamSealOffset(content) {
  const text = String(content ?? "");
  if (!text) return 0;
  let pos = 0;
  let sealedEnd = 0;
  let inCode = false;
  while (pos <= text.length) {
    const newline = text.indexOf("\n", pos);
    const lineEnd = newline === -1 ? text.length : newline;
    const trimmed = text.slice(pos, lineEnd).trim();
    const advanceTo = newline === -1 ? text.length : newline + 1;
    if (inCode) {
      if (trimmed.startsWith("```")) {
        inCode = false;
        sealedEnd = advanceTo;
      }
    } else if (trimmed.startsWith("```")) {
      inCode = true;
    } else if (trimmed === "" && newline !== -1) {
      sealedEnd = advanceTo;
    }
    if (newline === -1) break;
    pos = newline + 1;
  }
  return sealedEnd;
}

/**
 * Normalize a workflow id to a filesystem- and URL-safe slug.
 * Lowercases to keep the slug stable across case-insensitive filesystems.
 */
export function slugifyWorkflowId(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^[_-]+|[_-]+$/g, "")
    .slice(0, 80);
}

/**
 * Bound a number into a closed integer range. Non-finite values fall back
 * to the lower bound so callers never end up with NaN propagating into a UI.
 */
export function clampInt(value, min, max) {
  const num = Number(value);
  if (!Number.isFinite(num)) return min;
  const rounded = Math.round(num);
  if (rounded < min) return min;
  if (rounded > max) return max;
  return rounded;
}
