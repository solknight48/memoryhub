// Test harness for the UI's pure functions.
//
// Slices them out of the shipped index.html and runs them against a minimal DOM
// shim, so the page's real logic is testable without a browser. Reads a JSON
// object of {function: [args...]} on stdin and writes {function: [results...]}
// on stdout; DOM nodes come back as serialised HTML.
//
//   node tests/uijs.mjs src/memoryhub/ui/index.html <<< '{"modelLabel":["claude-opus-5"]}'
//
// The shim implements only what the sliced functions touch: appendChild,
// setAttribute, className, textContent, style. If the page ever reaches for
// innerHTML the harness fails loudly rather than escaping nothing.

import { readFileSync } from "node:fs";

const page = readFileSync(process.argv[2], "utf8");

// Two regions: the markdown renderer, then the avatar/model helpers. Both are
// pure given a document, so they run outside a browser unchanged.
function slice(from, to) {
  const a = page.indexOf(from), b = page.indexOf(to);
  if (a < 0 || b < 0 || b < a) {
    throw new Error(`cannot slice "${from}" .. "${to}" — was one of them renamed?`);
  }
  return page.slice(a, b);
}
const src = slice("function el(tag", "function tip(evt") +
            slice("const AVATARS", "function niceStamp");

class Node {
  constructor(tag) {
    this.tag = tag;
    this.attrs = {};
    this.kids = [];
    this.text = null;
    this.style = {};
  }
  appendChild(n) { this.kids.push(n); return n; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  set className(v) { this.attrs.class = v; }
  set textContent(v) { this.text = v; this.kids = []; }
  set innerHTML(_) { throw new Error("the page must never use innerHTML"); }
  addEventListener() {}
}
class Text {
  constructor(t) { this.data = t; }
}
class Frag extends Node {
  constructor() { super("#frag"); }
}

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function serialise(n) {
  if (typeof n !== "object" || n === null) return n;
  if (n instanceof Text) return esc(n.data);
  const inner = (n.text === null ? "" : esc(n.text)) + n.kids.map(serialise).join("");
  if (n.tag === "#frag") return inner;
  const style = Object.entries(n.style).map(([k, v]) => `${k}:${v}`).join(";");
  const attrs = { ...n.attrs, ...(style ? { style } : {}) };
  const rendered = Object.entries(attrs).map(([k, v]) => ` ${k}="${esc(v)}"`).join("");
  return `<${n.tag}${rendered}>${inner}</${n.tag}>`;
}

const document = {
  createElement: (t) => new Node(t),
  createElementNS: (_ns, t) => new Node(t),
  createTextNode: (t) => new Text(t),
  createDocumentFragment: () => new Frag(),
};

const fns = new Function(
  "document",
  src + "\nreturn { md, modelLabel, modelChip, avatarColor };"
)(document);

const request = JSON.parse(readFileSync(0, "utf8"));
const out = {};
for (const [name, args] of Object.entries(request)) {
  if (!fns[name]) throw new Error(`no such function in the page: ${name}`);
  out[name] = args.map((a) => serialise(fns[name](a)));
}
process.stdout.write(JSON.stringify(out));
