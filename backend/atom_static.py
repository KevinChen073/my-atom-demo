"""Source contract for generated apps that run without a Node toolchain."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from .source_harness import MAX_FILE_BYTES, MAX_GENERATED_BYTES, MAX_README_BYTES


REQUIRED_FILES = {"index.html", "style.css", "app.js", "readme.md"}
GENERATED_FILE = re.compile(r"(?:index\.html|style\.css|app\.js|readme\.md)\Z")
FORBIDDEN = re.compile(
    r"\b(?:eval|Function|fetch|XMLHttpRequest|WebSocket|Worker|SharedWorker|importScripts|"
    r"ServiceWorker|sendBeacon|indexedDB|sessionStorage)\b|"
    r"\b(?:document\.cookie|window\.(?:parent|top|opener)|location\.(?:assign|replace))\b|"
    r"\b(?:import|export)\s*(?:\(|\{|\*|from)|https?://|"
    r"<\s*(?:script|iframe)\b|@import|url\s*\(", re.IGNORECASE,
)


class EntryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []
        self.links: list[dict[str, str | None]] = []
        self.roots = 0
        self.unsafe = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if any(name.lower().startswith("on") for name in values):
            self.unsafe = True
        if any(value and not (value == "./app.js" and name == "src" or
                              value == "./style.css" and name == "href" or
                              value.startswith("#") and name == "href")
               for name, value in values.items() if name in {"src", "href", "action"}):
            self.unsafe = True
        if tag in {"iframe", "object", "embed", "base", "form", "style", "meta"}:
            if tag != "meta" or not (values.get("charset", "").lower() == "utf-8" or
                                      values.get("name", "").lower() == "viewport" and
                                      values.get("content", "").startswith("width=device-width")):
                self.unsafe = True
        if tag == "script":
            self.scripts.append(values)
        if tag == "link":
            self.links.append(values)
        if values.get("id") == "root":
            self.roots += 1


def source_contract_prompt(target_files: list[str] | None = None) -> str:
    targets = target_files or []
    output = (f"本次只返回 files 对象，路径必须且只能是 {', '.join(targets)}，值为完整文件内容。" if targets
              else "本次返回完整 files 路径映射。")
    return (
        "你是无构建步骤的静态 Web 应用工程师。只输出 JSON 对象。" + output
        + "完整应用必须包含 index.html、style.css、app.js、readme.md。"
        + "index.html 必须含 id=\"root\"，只通过 ./style.css 和 ./app.js 引用资源；不写内联脚本、事件属性或外部资源。"
        + "app.js 使用浏览器原生 JavaScript，不用 import/export、Node、TypeScript、React 或第三方库。"
        + "业务状态只用本项目隔离预览 origin 的 localStorage 保存；刷新读回，异常时提示，失败不能显示已保存。"
        + "同项目跨版本共享 origin，但业务数据不随代码回滚。禁止网络请求、动态执行、iframe、浏览器凭证和服务端 CRUD。"
        + f"每个文件最多 {MAX_FILE_BYTES} 字节，readme.md 最多 {MAX_README_BYTES} 字节，总计 {MAX_GENERATED_BYTES} 字节。"
        + "不要生成构建配置；只输出形如 {\"files\":{\"index.html\":\"...\"}} 的合法 JSON。"
    )


def inspect_generated(files: Any) -> list[dict[str, str | None]]:
    if not isinstance(files, dict):
        return [{"code": "missing_files_mapping", "file": None, "detail": "模型必须返回 files 路径映射"}]
    issues: list[dict[str, str | None]] = []

    def add(code: str, name: str | None, detail: str) -> None:
        issues.append({"code": code, "file": name, "detail": detail})

    for name in sorted(REQUIRED_FILES - files.keys()):
        add("invalid_layout", name, f"缺少 {name}")
    if set(files) - REQUIRED_FILES:
        add("invalid_layout", None, "只允许四个固定静态文件")
    total = 0
    for name, content in files.items():
        if not isinstance(name, str) or not GENERATED_FILE.fullmatch(name) or not isinstance(content, str) or not content.strip():
            add("invalid_layout", name if isinstance(name, str) else None, "文件名或内容无效")
            continue
        size = len(content.encode("utf-8"))
        total += size
        if size > (MAX_README_BYTES if name == "readme.md" else MAX_FILE_BYTES):
            add("invalid_layout", name, "文件过大")
        if name in {"app.js", "style.css"} and FORBIDDEN.search(content):
            add("unsafe_capability", name, "静态源码使用了禁用的能力或外部资源")
    if total > MAX_GENERATED_BYTES:
        add("invalid_layout", None, "生成文件总量过大")
    html = files.get("index.html")
    if isinstance(html, str):
        parser = EntryParser()
        try:
            parser.feed(html)
        except ValueError:
            add("invalid_source", "index.html", "HTML 解析失败")
        if parser.unsafe or parser.roots != 1 or parser.scripts != [{"src": "./app.js"}] or parser.links != [{"rel": "stylesheet", "href": "./style.css"}]:
            add("invalid_layout", "index.html", "入口必须只有一个 root 和固定的本地 CSS/JS 引用")
    return issues


def repair_feedback(issues: list[dict[str, Any]], *, origin: str) -> dict[str, Any]:
    safe = [{"code": item["code"], "file": item.get("file"), "feedback": str(item.get("detail") or item.get("feedback") or "静态文件校验失败")[:400]}
            for item in issues[:12]]
    targets = sorted({item["file"] for item in safe if isinstance(item.get("file"), str) and GENERATED_FILE.fullmatch(item["file"])})
    if any(item.get("file") is None for item in safe):
        targets = []
    return {"origin": origin, "issues": safe, "target_files": targets,
            "mode": "partial" if targets else "full"}
