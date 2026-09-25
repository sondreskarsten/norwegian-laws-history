"""Independent gate for a strict observed document-body projection.

Grammar: observed documentBody title, section/article hierarchy, legalP text and
explicit numbered lists. Unknown semantics reject the whole document. No imports
from the producer, formatter, or history consumer occur in this acceptance oracle.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

VERSION = "strict-document-body-v1"
SCOPE = {
    "contract": VERSION,
    "projection": "complete documentBody text, ordered lists and containers",
    "outside_body": "excluded; original metadata remains in retained raw XML",
    "inventoried_but_not_projected_attributes": ["id", "data-lovdata-url"],
    "projected_markers": ["legalArticle data-name", "li data-name", "li value", "ol type"],
    "unrepresented_named_nodes": "data-name on legalP, listArticle and section is rejected",
    "wrapper_policy": "typed header spans and listArticle wrappers preserve ordered text; wrapper identity is not projected",
    "whitespace": "collapse HTML ASCII whitespace only; preserve Unicode and punctuation",
    "model_header_rule": "append a period to a bare section-sign number, then require exact source equality",
    "legal_valid_time": "unresolved",
}
ROOT_FIELDS = {"paragraph": "top_level_paragraphs", "remainder": "remainders", "section": "sections", "article": "top_level_articles"}
SECTION_FIELDS = {"preamble": "preamble", "article": "articles", "section": "subsections", "footnote": "footnotes", "remainder": "remainders"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def normalized(text):
    # HTML ASCII whitespace only: no punctuation or Unicode-space normalization.
    return re.sub(r"[ \t\r\n\f]+", " ", text).strip(" \t\r\n\f")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Rejected(ValueError):
    def __init__(self, code, path, detail):
        super().__init__(detail)
        self.reason = {"code": code, "path": path, "detail": detail}


@dataclass
class Node:
    tag: str
    attrs: dict
    path: str
    position: tuple
    children: list = field(default_factory=list)
    text: str = ""


class SourceTree(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.root = Node("document", {}, "", (1, 0))
        self.stack = [self.root]
        self.errors = []
        self.feed(content.decode("utf-8")); self.close()
        if len(self.stack) != 1:
            self.errors.append({"code": "unclosed_source_element", "path": self.stack[-1].path})

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1]
        ordinal = 1 + sum(c.tag == tag for c in parent.children)
        node = Node(tag, dict(attrs), f"{parent.path}/{tag}[{ordinal}]", self.getpos())
        if len(node.attrs) != len(attrs):
            self.errors.append({"code": "duplicate_source_attribute", "path": node.path})
        parent.children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            self.errors.append({"code": "non_well_nested_source", "path": self.stack[-1].path, "end_tag": tag})
            return
        self.stack.pop()

    def handle_data(self, data):
        if not data:
            return
        parent = self.stack[-1]
        if parent.children and parent.children[-1].tag == "#text":
            parent.children[-1].text += data
        else:
            ordinal = 1 + sum(c.tag == "#text" for c in parent.children)
            parent.children.append(Node("#text", {}, f"{parent.path}/text()[{ordinal}]", self.getpos(), text=data))

    def handle_comment(self, data):
        self.stack[-1].children.append(Node("#comment", {}, self.stack[-1].path + "/comment()", self.getpos(), text=data))


def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def classes(node):
    return set((node.attrs.get("class") or "").split())


def source_preflight(body):
    reasons = []
    permitted = {
        "main": {"documentBody"}, "section": {"section"},
        "article": {"legalArticle", "legalP", "listArticle"},
        "span": {"legalArticleValue", "legalArticleTitle"},
        "ol": {"defaultList"}, "ul": {"defaultList"}, "li": set(),
    }
    attrs = {"class", "id", "data-lovdata-url"}
    for node in walk(body):
        if node.tag == "#text":
            continue
        # Only these markers have explicit event fields. A named legalP,
        # listArticle or section is rejected rather than silently losing its name.
        allowed = attrs | ({"data-name"} if node.tag == "li" or
                          (node.tag == "article" and classes(node) == {"legalArticle"}) else set())
        allowed |= {"type"} if node.tag in {"ol", "ul"} else set()
        allowed |= {"value"} if node.tag == "li" else set()
        if re.fullmatch(r"h[1-6]", node.tag):
            valid = not classes(node) or classes(node) == {"legalArticleHeader"}
        else:
            valid = node.tag in permitted and classes(node) <= permitted[node.tag]
            if node.tag in {"article", "span"}:
                valid = valid and len(classes(node)) == 1
        if not valid:
            reasons.append({"code": "unsupported_source_form", "path": node.path,
                            "tag": node.tag, "classes": sorted(classes(node)), "attributes": node.attrs,
                            "detail": "No faithful model representation is qualified for this form."})
        extra = set(node.attrs) - allowed
        if extra:
            reasons.append({"code": "unsupported_source_attribute", "path": node.path,
                            "attributes": {k: node.attrs[k] for k in sorted(extra)}})
    return reasons


def source_events(content):
    tree = SourceTree(content)
    bodies = [n for n in walk(tree.root) if n.tag == "main" and classes(n) == {"documentBody"}]
    if len(bodies) != 1:
        raise Rejected("source_body_count", "/", "Exactly one documentBody is required")
    body = bodies[0]
    reasons = tree.errors + source_preflight(body)
    inventory = [{"path": n.path, "tag": n.tag, "attributes": n.attrs,
                  "position": list(n.position), "text_sha256": digest(n.text.encode()) if n.tag == "#text" else None,
                  "disposition": "ascii_whitespace_only" if n.tag == "#text" and not normalized(n.text)
                  else "pending"} for n in walk(body)]
    if reasons:
        return [], [], inventory, reasons
    events, paths, touched = [], [], set()

    def emit(event, node):
        events.append(event); paths.append(node.path)

    def children(node):
        touched.add(node.path)
        for child in node.children:
            if child.tag == "#text" and not normalized(child.text):
                touched.add(child.path)
                continue
            yield child

    def plain(node, *, heading=False):
        touched.add(node.path)
        if node.tag == "#text":
            return node.text
        parts = []
        for child in node.children:
            if child.tag == "#text" or (heading and child.tag == "span"):
                parts.append(plain(child, heading=heading))
            else:
                raise Rejected("unsupported_inline_structure", child.path, "Only plain text and typed header spans are supported")
        return "".join(parts)

    def paragraph(node):
        emit(["open", "paragraph"], node)
        for child in children(node):
            if child.tag == "#text":
                touched.add(child.path); text = normalized(child.text)
                if text: emit(["text", text], child)
            elif child.tag in {"ol", "ul"}:
                listing(child)
            else:
                raise Rejected("unsupported_paragraph_child", child.path, "Cannot flatten inline or block semantics")
        emit(["close", "paragraph"], node)

    def listing(node):
        style = node.attrs.get("type", "1" if node.tag == "ol" else "disc")
        if node.tag != "ol" or style not in {"1", "a", "A", "i", "I"}:
            raise Rejected("unsupported_list_style", node.path, "Initial grammar requires an explicit ordered-list style")
        emit(["open", "list", style], node)
        for li in children(node):
            if li.tag != "li" or not li.attrs.get("data-name") or not li.attrs.get("value"):
                raise Rejected("unsupported_list_item", li.path, "List marker and ordinal must be explicit")
            emit(["open", "item", li.attrs["data-name"], li.attrs["value"]], li)
            for child in children(li):
                if child.tag == "article" and classes(child) == {"listArticle"}:
                    for nested in children(child):
                        if nested.tag == "article" and classes(nested) == {"legalP"}: paragraph(nested)
                        else: raise Rejected("unsupported_list_wrapper", nested.path, "List wrapper must contain legal paragraphs only")
                elif child.tag == "article" and classes(child) == {"legalP"}: paragraph(child)
                else: raise Rejected("unsupported_list_item_body", child.path, "Unwrapped list text is not yet qualified")
            emit(["close", "item"], li)
        emit(["close", "list"], node)

    def article(node, depth):
        name = node.attrs.get("data-name")
        if not name: raise Rejected("missing_article_name", node.path, "An explicit article marker is required")
        emit(["open", "article", name], node)
        parts = list(children(node))
        if not parts or parts[0].tag != f"h{depth+2}" or classes(parts[0]) != {"legalArticleHeader"}:
            raise Rejected("article_header_shape", node.path, "One leading header at the container depth is required")
        emit(["heading", normalized(plain(parts.pop(0), heading=True))], node)
        for child in parts:
            if child.tag == "article" and classes(child) == {"legalP"}: paragraph(child)
            else: raise Rejected("unsupported_article_child", child.path, "Article child cannot be flattened into trailing text")
        emit(["close", "article"], node)

    def section(node, depth):
        emit(["open", "section"], node)
        parts = list(children(node))
        if not parts or parts[0].tag != f"h{depth+2}":
            raise Rejected("section_header_shape", node.path, "One leading section heading at the container depth is required")
        emit(["heading", normalized(plain(parts.pop(0)))], node)
        for child in parts: component(child, depth+1)
        emit(["close", "section"], node)

    def component(node, depth):
        if node.tag == "section": section(node, depth)
        elif node.tag == "article" and classes(node) == {"legalArticle"}: article(node, depth)
        elif node.tag == "article" and classes(node) == {"legalP"}: paragraph(node)
        else: raise Rejected("unsupported_container_child", node.path, "Unclassified container child")

    try:
        parts = list(children(body))
        if not parts or parts[0].tag != "h1":
            raise Rejected("document_title_shape", body.path, "One leading h1 is required")
        title = normalized(plain(parts.pop(0)))
        emit(["open", "document", title], body)
        for child in parts: component(child, 0)
        emit(["close", "document"], body)
    except Rejected as exc:
        reasons.append(exc.reason)
    for row in inventory:
        if row["path"] in touched: row["disposition"] = "represented_or_declared_whitespace"
        elif row["disposition"] == "pending":
            row["disposition"] = "unclassified"
    if not reasons and any(row["disposition"] == "unclassified" for row in inventory):
        reasons.append({"code": "unclassified_source_remainder", "path": body.path})
    return events, paths, inventory, reasons


def model_events(model):
    events = []

    def emit(event): events.append(event)

    def order(node, fields, path):
        for name in fields.values():
            if not isinstance(node.get(name, []), list): raise Rejected("model_array_type", path + "/" + name, "Expected an array")
        refs = node.get("content_order", [])
        if not isinstance(refs, list): raise Rejected("model_order_type", path, "Expected order array")
        expected = {(kind, i) for kind, name in fields.items() for i in range(len(node.get(name, [])))}
        if refs:
            seen = []
            for ref in refs:
                if not isinstance(ref, dict) or set(ref) != {"kind", "index"} or type(ref["index"]) is not int:
                    raise Rejected("model_order_reference", path, "Malformed kind/index")
                seen.append((ref["kind"], ref["index"]))
            if len(seen) != len(set(seen)) or set(seen) != expected:
                raise Rejected("model_order_coverage", path, "References must cover each item exactly once")
        else:
            seen = [(kind, i) for kind, field in fields.items() for i in range(len(node.get(field, [])))]
        for kind, i in seen:
            yield kind, node[fields[kind]][i], f"{path}/{fields[kind]}/{i}"

    def paragraph(node, path):
        emit(["open", "paragraph"])
        blocks = node.get("ordered_blocks", [])
        if blocks:
            if any(node.get(k) for k in ("text", "list_items", "list_style", "trailing_text")):
                raise Rejected("model_mixed_paragraph_ownership", path, "Ordered and legacy fields overlap")
            for i, block in enumerate(blocks):
                if block["kind"] == "text": emit(["text", normalized(block["text"])])
                elif block["kind"] == "list": listing(block["list_items"], block["list_style"], f"{path}/ordered_blocks/{i}")
                else: raise Rejected("model_block_kind", path, "Unknown ordered paragraph block")
        else:
            if node.get("text"): emit(["text", normalized(node["text"])])
            if node.get("list_items"): listing(node["list_items"], node["list_style"], path + "/list_items")
            if node.get("trailing_text"): emit(["text", normalized(node["trailing_text"])])
        emit(["close", "paragraph"])

    def listing(items, style, path):
        if style not in {"1", "a", "A", "i", "I"}: raise Rejected("model_list_style", path, "Unsupported list style")
        emit(["open", "list", style])
        for i, item in enumerate(items):
            emit(["open", "item", item["marker"], item["value"]])
            for j, para in enumerate(item["paragraphs"]): paragraph(para, f"{path}/{i}/paragraphs/{j}")
            emit(["close", "item"])
        emit(["close", "list"])

    def article(node, path):
        if node.get("trailing_text") or node.get("remainders"):
            raise Rejected("model_untyped_article_remainder", path, "Trailing text cannot retain annotation/footnote roles")
        emit(["open", "article", node["name"]])
        header = normalized(node["header_text"])
        # Exact, declared visible header rule, checked against source punctuation.
        # No arbitrary punctuation is removed: a nonconforming source will fail.
        if re.fullmatch(r"§\s*\d+[a-z]?(?:-\d+[a-z]?)?", header): header += "."
        emit(["heading", header])
        for i, para in enumerate(node.get("paragraphs", [])): paragraph(para, f"{path}/paragraphs/{i}")
        emit(["close", "article"])

    def component(kind, node, path):
        if kind == "section":
            emit(["open", "section"]); emit(["heading", normalized(node["heading"])])
            for k, child, child_path in order(node, SECTION_FIELDS, path): component(k, child, child_path)
            emit(["close", "section"])
        elif kind == "article": article(node, path)
        elif kind == "paragraph": paragraph(node, path)
        else: raise Rejected("model_untyped_container_text", path, f"{kind} loses its original semantic element role")

    emit(["open", "document", normalized(model["title"])])
    for kind, node, path in order(model, ROOT_FIELDS, "model"): component(kind, node, path)
    emit(["close", "document"])
    return events


def canonical_html(events, refid, source_sha):
    root, stack = None, []
    for event in events:
        if event[0] == "open":
            kind = event[1]
            if kind == "document":
                root = ET.Element("main", {"id": "canonical-body"}); stack.append((kind, root))
                ET.SubElement(root, "h1").text = event[2]
                continue
            tag, attrs = {"section": ("section", {}), "article": ("article", {"data-name": event[2]} if len(event) > 2 else {}),
                          "paragraph": ("div", {"class": "legal-paragraph"}), "list": ("ol", {"type": event[2]} if len(event) > 2 else {}),
                          "item": ("li", {"value": event[3]} if len(event) > 3 else {})}[kind]
            element = ET.SubElement(stack[-1][1], tag, attrs)
            if kind == "item": ET.SubElement(element, "span", {"class": "marker"}).text = event[2]
            stack.append((kind, element))
        elif event[0] == "close":
            if not stack or stack.pop()[0] != event[1]: raise ValueError("Unbalanced canonical event stream")
        elif event[0] == "heading":
            depth = 1 + sum(kind in {"article", "section"} for kind, _ in stack)
            ET.SubElement(stack[-1][1], f"h{depth}").text = event[1]
        elif event[0] == "text": ET.SubElement(stack[-1][1], "span", {"class": "text-run"}).text = event[1]
        else: raise ValueError("Unknown canonical event")
    if stack or root is None: raise ValueError("Unclosed canonical events")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    return ('<!doctype html><html lang="nb"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>'
            '<title>' + html.escape(events[0][2]) + '</title><style>body{margin:0;background:#f3f4f0;color:#172c32;font:18px/1.65 Georgia,serif}'
            '.wrap{max-width:850px;margin:auto;padding:36px 24px}header{font:14px/1.5 system-ui;color:#54666a;border-bottom:1px solid #c4cecc;padding-bottom:20px}'
            'h1{font-size:34px;line-height:1.2}h2,h3,h4{line-height:1.3}article,section{margin:28px 0}.legal-paragraph{margin:16px 0}'
            'ol{list-style:none;padding-left:26px}li{display:grid;grid-template-columns:max-content minmax(0,1fr);column-gap:8px;margin:12px 0}'
            '.marker{font-weight:bold;grid-column:1;grid-row:1}li>.legal-paragraph{grid-column:2;margin:0 0 8px}'
            'footer{font:13px/1.5 system-ui;border-top:1px solid #c4cecc;margin-top:30px;padding-top:16px;overflow-wrap:anywhere}</style></head><body><div class="wrap">'
            '<header>Observed document-body projection<br/>Legal effective dates unresolved · Source observation only</header>' + body +
            '<footer>Lovdata · NLOD 2.0<br/>Source: ' + html.escape(refid) + '<br/>XML SHA-256: ' + source_sha + '</footer></div></body></html>')


def reverse_canonical_html(output):
    # Independently read visible DOM structure/text; no embedded event JSON.
    document = ET.fromstring(output[output.index("<html"):])
    bodies = document.findall(".//main[@id='canonical-body']")
    if len(bodies) != 1: raise ValueError("Expected one canonical body")
    events = []

    def clean_text(node):
        if list(node): raise ValueError("Unexpected markup in canonical text leaf")
        return node.text or ""

    def traverse(node, depth=1):
        if node.tag == "main":
            if node.attrib != {"id": "canonical-body"}: raise ValueError("Unexpected canonical body attributes")
            if not list(node) or node[0].tag != "h1" or node[0].attrib: raise ValueError("Invalid canonical title")
            events.append(["open", "document", clean_text(node[0])]); children = list(node)[1:]; kind = "document"
        elif node.tag in {"section", "article"}:
            kind = node.tag
            if set(node.attrib) != ({"data-name"} if kind == "article" else set()): raise ValueError("Unexpected canonical container attributes")
            events.append(["open", kind, node.attrib["data-name"]] if kind == "article" else ["open", kind])
            depth += 1
            if not list(node) or node[0].tag != f"h{depth}" or node[0].attrib: raise ValueError("Invalid canonical container heading")
            events.append(["heading", clean_text(node[0])]); children = list(node)[1:]
        elif node.tag == "div" and node.attrib == {"class": "legal-paragraph"}:
            kind = "paragraph"; events.append(["open", kind]); children = list(node)
        elif node.tag == "ol" and set(node.attrib) == {"type"}:
            kind = "list"; events.append(["open", kind, node.attrib["type"]]); children = list(node)
        elif node.tag == "li" and set(node.attrib) == {"value"}:
            if not list(node) or node[0].tag != "span" or node[0].attrib != {"class": "marker"}: raise ValueError("Missing visible marker")
            kind = "item"; events.append(["open", kind, clean_text(node[0]), node.attrib["value"]]); children = list(node)[1:]
        elif node.tag == "span" and node.attrib == {"class": "text-run"}:
            events.append(["text", clean_text(node)]); return
        else: raise ValueError(f"Unexpected canonical element: {node.tag}")
        if normalized(node.text or ""): raise ValueError("Injected unclassified canonical text")
        for child in list(node):
            if normalized(child.tail or ""): raise ValueError("Injected canonical tail text")
        for child in children: traverse(child, depth)
        events.append(["close", kind])
    traverse(bodies[0])
    return events


def first_difference(left, right):
    for i in range(max(len(left), len(right))):
        a = left[i] if i < len(left) else None; b = right[i] if i < len(right) else None
        if a != b: return {"event_index": i, "source": a, "model_or_output": b}
    return None


def qualify(raw, model, refid):
    """Return per-projection report and traversals; unsupported input yields no HTML.

    The caller must bind raw/model bytes to an independently verified receipt and
    occurrence. A scoped pass never promotes the observation or legal valid time.
    """
    result = {"refid": refid, "verifier_version": VERSION, "projection_contract": VERSION,
              "status": "failed", "scope": SCOPE.copy(), "observation_canonical_status": "not_verified",
              "source_sha256": digest(raw), "legal_valid_time_status": "unresolved", "reasons": []}
    try:
        source, paths, inventory, reasons = source_events(raw)
    except Rejected as exc:
        source, paths, inventory, reasons = [], [], [], [exc.reason]
    except (UnicodeError, ValueError, TypeError) as exc:
        source, paths, inventory, reasons = [], [], [], [{"code": "invalid_source", "detail": str(exc)}]
    result["source_element_count"] = sum(row["tag"] != "#text" for row in inventory)
    result["source_text_leaf_count"] = sum(row["tag"] == "#text" for row in inventory)
    result["reasons"].extend(reasons)
    try: modeled = model_events(model)
    except Rejected as exc:
        modeled = []; result["reasons"].append(exc.reason)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        modeled = []; result["reasons"].append({"code": "invalid_model", "detail": str(exc)})
    if not result["reasons"]:
        difference = first_difference(source, modeled)
        if difference:
            result["reasons"].append({"code": "ordered_source_model_mismatch", **difference,
                                      "path": paths[difference["event_index"]] if difference["event_index"] < len(paths) else "model-extra"})
    output = None
    if not result["reasons"]:
        try:
            candidate = canonical_html(modeled, refid, result["source_sha256"])
            reversed_events = reverse_canonical_html(candidate)
            difference = first_difference(source, reversed_events)
        except (ValueError, KeyError, TypeError, IndexError, ET.ParseError) as exc:
            result["reasons"].append({"code": "invalid_canonical_output", "detail": str(exc)})
        else:
            if difference: result["reasons"].append({"code": "canonical_reverse_mismatch", **difference})
        if not result["reasons"]:
            output = candidate
            result.update(status="passed", event_count=len(source), ordered_events_sha256=digest(encoded(source)),
                          canonical_html_sha256=digest(output.encode()), unclassified_source_remainder=0,
                          qualification="strict document-body projection only; no whole-corpus or legal-state claim")
    result["reason_counts"] = dict(Counter(reason["code"] for reason in result["reasons"]))
    return result, inventory, source, paths, modeled, output
