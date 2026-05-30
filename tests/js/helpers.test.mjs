import test from "node:test";
import assert from "node:assert/strict";

import {
  clampInt,
  clampLength,
  escapeHtml,
  findStreamSealOffset,
  formatContent,
  formatInlineMarkdown,
  plainTextContent,
  slugifyWorkflowId,
  stripControlChars,
} from "../../app/static/helpers.js";

test("escapeHtml escapes all HTML-sensitive characters and handles nullish values", () => {
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(undefined), "");
  assert.equal(
    escapeHtml("<script data-x=\"1\">Tom & `Jerry`'s</script>"),
    "&lt;script data-x=&quot;1&quot;&gt;Tom &amp; &#096;Jerry&#096;&#039;s&lt;/script&gt;",
  );
});

test("stripControlChars removes unsafe controls but preserves useful whitespace", () => {
  assert.equal(stripControlChars("a\u0000b\tc\nd\re\u007ff"), "ab\tc\nd\ref");
});

test("clampLength strips controls and only truncates for positive finite limits", () => {
  assert.equal(clampLength("abc\u0000def", 4), "abcd");
  assert.equal(clampLength("abcdef", 0), "abcdef");
  assert.equal(clampLength("abcdef", Number.POSITIVE_INFINITY), "abcdef");
});

test("formatInlineMarkdown renders safe bold, code spans, and http links", () => {
  assert.equal(
    formatInlineMarkdown("Use **bold**, `code <tag>`, and [docs](https://example.test/a?b=1)."),
    'Use <strong>bold</strong>, <code>code &lt;tag&gt;</code>, and <a href="https://example.test/a?b=1" target="_blank" rel="noopener noreferrer">docs</a>.',
  );
});

test("formatInlineMarkdown escapes malicious input instead of creating arbitrary HTML", () => {
  assert.equal(
    formatInlineMarkdown("<img src=x onerror=alert(1)> **safe**"),
    "&lt;img src=x onerror=alert(1)&gt; <strong>safe</strong>",
  );
});

test("formatInlineMarkdown leaves non-http links as text", () => {
  assert.equal(
    formatInlineMarkdown("[bad](javascript:alert(1)) [ok](http://example.test)"),
    '[bad](javascript:alert(1)) <a href="http://example.test" target="_blank" rel="noopener noreferrer">ok</a>',
  );
});

test("formatContent renders paragraphs, headings, ordered and unordered lists", () => {
  const html = formatContent(`# Title

First paragraph
continues here.

- one
- two

1. alpha
2. beta`);

  assert.equal(
    html,
    "<h3>Title</h3><p>First paragraph continues here.</p><ul><li>one</li><li>two</li></ul><ol><li>alpha</li><li>beta</li></ol>",
  );
});

test("formatContent keeps list continuations on the previous item", () => {
  assert.equal(
    formatContent("- first\n  wrapped line\n- second"),
    "<ul><li>first wrapped line</li><li>second</li></ul>",
  );
});

test("formatContent renders fenced code blocks literally and closes unclosed fences", () => {
  assert.equal(
    formatContent("```js\nconst x = '<tag>';\n```"),
    "<pre><code>const x = &#039;&lt;tag&gt;&#039;;</code></pre>",
  );
  assert.equal(
    formatContent("before\n\n```\nunterminated"),
    "<p>before</p><pre><code>unterminated</code></pre>",
  );
});

test("plainTextContent escapes HTML and preserves line breaks", () => {
  assert.equal(plainTextContent("a < b\nc"), "a &lt; b<br>c");
});

test("findStreamSealOffset seals complete markdown blocks only", () => {
  assert.equal(findStreamSealOffset(""), 0);
  assert.equal(findStreamSealOffset("hello"), 0);
  assert.equal(findStreamSealOffset("hello\n\nstill streaming"), 7);
  assert.equal(findStreamSealOffset("```js\nx\n```\nmore"), 12);
  assert.equal(findStreamSealOffset("```js\nx\nmore"), 0);
});

test("slugifyWorkflowId creates bounded lowercase workflow ids", () => {
  assert.equal(slugifyWorkflowId("  My Workflow: v2!  "), "my_workflow_v2");
  assert.equal(slugifyWorkflowId("___Already--Clean___"), "already--clean");
  assert.equal(slugifyWorkflowId("x".repeat(100)).length, 80);
});

test("clampInt rounds and clamps finite numbers and falls back on non-finite values", () => {
  assert.equal(clampInt("4.6", 1, 5), 5);
  assert.equal(clampInt(-10, 1, 5), 1);
  assert.equal(clampInt(100, 1, 5), 5);
  assert.equal(clampInt("nope", 1, 5), 1);
});
