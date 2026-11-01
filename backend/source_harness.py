"""The generated-file contract and bounded repair feedback shared by model and runner."""

from __future__ import annotations

import re
import posixpath
from typing import Any


REQUIRED_FILES = {"src/App.tsx", "src/app.css", "src/hooks/useAppState.ts", "readme.md"}
GENERATED_FILE = re.compile(r"(?:src/App\.tsx|src/app\.css|src/hooks/[A-Za-z][A-Za-z0-9]*\.ts|src/components/[A-Za-z][A-Za-z0-9]*\.tsx|readme\.md)\Z")
MAX_GENERATED_FILES = 12
MAX_GENERATED_BYTES = 180_000
MAX_FILE_BYTES = 60_000
MAX_README_BYTES = 10_000
MAX_COMPONENTS = 6
MAX_HOOKS = 4

SOURCE_FAILURE_REASONS = {
    "updater_side_effect": "状态更新函数中包含持久化或再次更新状态",
    "component_state": "页面或组件使用了应放在 hooks/ 的状态逻辑",
    "ui_storage_access": "页面或组件直接访问 localStorage",
    "missing_files_mapping": "模型未返回源码文件映射",
    "invalid_partial_files": "局部修复只允许返回指定文件，不能增删其他候选文件",
    "invalid_layout": "文件布局、数量或入口不符合固定模板",
    "invalid_import": "源码导入了未生成或不允许的模块",
    "unsafe_capability": "源码使用了当前模板禁止的能力",
    "unsupported_capability": "源码使用了当前模板不支持的接口或资源",
    "invalid_source": "源码未通过生成边界校验",
}


def source_violation_code(exc: Exception) -> str:
    if isinstance(exc, (KeyError, TypeError)):
        return "missing_files_mapping"
    message = str(exc)
    if "状态更新函数" in message:
        return "updater_side_effect"
    if "状态与业务逻辑须放" in message:
        return "component_state"
    if "业务持久化逻辑只能写" in message:
        return "ui_storage_access"
    if "导入" in message:
        return "invalid_import"
    if "不允许的能力" in message:
        matched = message.rsplit("：", 1)[-1].strip().lower()
        return "unsafe_capability" if any(matched.startswith(prefix) for prefix in (
            "eval(", "function(", "require(", "document.cookie", "window.parent", "window.top",
            "process.env", "import.meta.env", "navigator.serviceworker", "dangerouslysetinnerhtml", "srcdoc",
        )) else "unsupported_capability"
    if any(word in message for word in ("生成文件", "App.tsx", "数量超过", "长度限制")):
        return "invalid_layout"
    return "invalid_source"


def source_validation_reason(codes: tuple[str, ...]) -> str:
    reasons = [SOURCE_FAILURE_REASONS.get(code, SOURCE_FAILURE_REASONS["invalid_source"]) for code in codes[-3:]]
    return f"源码校验未通过（最近 {len(reasons)} 次）：" + "；".join(reasons) + "。本轮候选未进入构建。"


def source_contract_prompt(target_files: list[str] | None = None) -> str:
    files = target_files or []
    output = (f"本次只返回 files 对象，其中路径必须且只能是 {', '.join(files)}；每个值为该文件完整内容，不输出其他文件。"
              if files else "本次返回完整 files 路径映射。")
    return (
        "你是固定模板 React+TypeScript+Vite 应用工程师。只输出 JSON 对象。" + output
        + f"完整应用必须包含 {', '.join(sorted(REQUIRED_FILES))}。"
        + f"只允许 App、app.css、readme.md、src/components/Name.tsx 与 src/hooks/useName.ts；最多 {MAX_COMPONENTS} 个组件、{MAX_HOOKS} 个 hook（包含必需的 useAppState.ts，因此其他 hook 最多 {MAX_HOOKS - 1} 个）、{MAX_GENERATED_FILES} 个生成文件、总计 {MAX_GENERATED_BYTES} 字节；"
        + f"单文件最多 {MAX_FILE_BYTES} 字节，readme.md 最多 {MAX_README_BYTES} 字节。"
        + "App.tsx 必须导入 './app.css' 和 './hooks/useAppState'；组件和 App 只组合界面，不调用 useState/useEffect/useReducer/useRef；状态、持久化和业务逻辑都放 hooks/。"
        + "React 状态更新函数只计算下一状态，不在更新函数内保存数据或再次调用 setState；副作用放在事件处理函数。"
        + "样式只写 src/app.css；readme.md 用中文说明功能和本地数据范围。"
        + "生成应用业务数据只使用本项目独立预览 origin 的 localStorage，且只在 hooks/ 内访问；刷新后读取，读写异常在界面明确提示，写入失败不能显示已保存。"
        + "同一项目跨版本共享 origin，但业务数据不随代码版本回滚；读取旧格式时要明确提示。"
        + "涉及计时用 Date.now() 真实时间差；结算使用稳定标识防止重复计数。涉及提交的按钮防连续重复触发。"
        + "只允许 React、模板文件和已生成文件的静态导入；禁止外部接口、图片 URL、fetch、服务端 CRUD、SQL、浏览器凭证、动态 import、eval 和第三方库。"
        + "不要生成 package.json、main.tsx 或其他模板配置。输出前在内部核对 files 路径、hook 数量与 TypeScript 状态引用；只输出形如 {\"files\":{\"src/App.tsx\":\"...\"}} 的合法 JSON，源码字符串里的换行和双引号必须转义，不输出清单或解释。"
    )


def repair_feedback(issues: list[dict[str, Any]], *, origin: str) -> dict[str, Any]:
    """Only a concrete, allowlisted file set permits a partial regeneration."""
    safe_issues = [{"code": issue["code"], "file": issue.get("file"),
                    "feedback": str(issue.get("feedback") or issue.get("detail") or SOURCE_FAILURE_REASONS.get(issue["code"], SOURCE_FAILURE_REASONS["invalid_source"]))[:400]}
                   for issue in issues[:12]]
    targets = sorted({issue["file"] for issue in safe_issues if issue.get("file") and GENERATED_FILE.fullmatch(issue["file"])})
    if not targets or len(targets) != len({issue.get("file") for issue in safe_issues}):
        targets = []
    return {"origin": origin, "issues": safe_issues, "target_files": targets,
            "mode": "partial" if targets else "full"}


def source_signatures(issues: list[dict[str, Any]]) -> list[str]:
    return sorted({f"source:{issue['code']}:{issue.get('file') or '*'}" for issue in issues})


def repair_interface_context(files: dict[str, str], targets: list[str], *, max_chars: int = 24000) -> dict[str, str]:
    """Give a partial repair the existing imports it must preserve, never new output targets."""
    imports = re.compile(r"^\s*import\s+(?:.*?\s+from\s+)?['\"](\.[^'\"]+)['\"]", re.MULTILINE)
    selected: dict[str, str] = {}
    remaining = max_chars
    for target in targets:
        source = files.get(target, "")
        for module in imports.findall(source):
            base = posixpath.normpath(posixpath.join(posixpath.dirname(target), module))
            path = next((name for name in (base, base + ".ts", base + ".tsx") if name in files), None)
            if not path or path in targets or path in selected or not path.endswith((".ts", ".tsx")):
                continue
            content = files[path]
            if len(content) > remaining:
                continue
            selected[path] = content
            remaining -= len(content)
    return selected
