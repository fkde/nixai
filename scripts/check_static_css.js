#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const cssDir = path.join("app", "static");
const files = fs.readdirSync(cssDir)
  .filter((name) => name.endsWith(".css"))
  .sort()
  .map((name) => path.join(cssDir, name));

let failed = false;

for (const file of files) {
  const source = fs.readFileSync(file, "utf8");
  const stack = [];
  let inComment = false;
  let quote = null;
  let line = 1;
  let column = 0;

  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    const next = source[index + 1];
    column += 1;

    if (char === "\n") {
      line += 1;
      column = 0;
    }

    if (inComment) {
      if (char === "*" && next === "/") {
        inComment = false;
        index += 1;
        column += 1;
      }
      continue;
    }

    if (quote) {
      if (char === "\\") {
        index += 1;
        column += 1;
      } else if (char === quote) {
        quote = null;
      }
      continue;
    }

    if (char === "/" && next === "*") {
      inComment = true;
      index += 1;
      column += 1;
    } else if (char === "\"" || char === "'") {
      quote = char;
    } else if (char === "{") {
      stack.push({ line, column });
    } else if (char === "}") {
      const opened = stack.pop();
      if (!opened) {
        console.error(`${file}:${line}:${column}: unmatched closing brace`);
        failed = true;
      }
    }
  }

  for (const opened of stack) {
    console.error(`${file}:${opened.line}:${opened.column}: unmatched opening brace`);
    failed = true;
  }
}

if (failed) {
  process.exit(1);
}
