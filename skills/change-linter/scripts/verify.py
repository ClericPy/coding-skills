#!/usr/bin/env python
"""改动分级后置校验。

按调用方指定的 Level，对本次改动的 .py / .sh 文件执行静态检查。

级别判定不属本脚本职责 —— 脚本只做机械部分：发现改动文件、探测工具、
并行执行、汇总结果与退出码。

退出码：
    0  该 Level 的全部校验都真实执行且通过；或改动仅为删除文件（无适用校验对象）
    1  存在校验失败，或存在未真正执行的校验（缺工具 / 无适用改动）
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

# 需要探测的可执行文件名（执行时一律使用 shutil.which 解析出的绝对路径）
GIT = "git"
UV = "uv"

PY_SUFFIX = ".py"
SH_SUFFIX = ".sh"
SHELL_TOOL = "bash"

# ruff 缺失时的语法底线：解释器自带的 py_compile；字节码重定向，避免写入项目
PY_COMPILE_TOOL = "py_compile"
PYCACHE_ENV = "PYTHONPYCACHEPREFIX"

# 本技能自身的根目录：自动发现时排除，避免把技能的安装副本当成用户的改动
SKILL_ROOT = Path(__file__).resolve().parent.parent

# 每个 Level 需要参与校验的工具；bash 按是否存在 .sh 改动单独追加
LEVEL_TOOLS: dict[str, tuple[str, ...]] = {
    "L1": ("ruff",),
    "L2": ("ruff", "ty", "pyrefly"),
    "L3": ("ruff", "ty", "pyrefly", "pyright"),
    "L4": ("ruff", "ty", "pyrefly", "pyright", "mypy"),
}

PROBE_TOOLS: tuple[str, ...] = (
    "ruff",
    "ty",
    "pyrefly",
    "pyright",
    "mypy",
    SHELL_TOOL,
    "shellcheck",
    UV,
    GIT,
)

# 缺失即硬失败、不可降级的工具
REQUIRED_TOOLS: frozenset[str] = frozenset({"ruff"})

# 缺失则降级并显式标注“该级未真正校验”的工具
DEGRADABLE_TOOLS: frozenset[str] = frozenset(
    {"ty", "pyrefly", "pyright", "mypy", SHELL_TOOL}
)

# 不能经 uv tool install 安装的工具（bash 由系统提供，缺失时只能提示用户自装）
NON_UV_TOOLS: frozenset[str] = frozenset({SHELL_TOOL})

# ruff 缺省兜底参数：仅当被测项目未自带 ruff 配置时才传给 ruff，
# 项目自带配置（pyproject.toml 的 [tool.ruff] / ruff.toml）时以项目为准
RUFF_SELECT = "E,F,W,I,S,PERF"
RUFF_IGNORE = "W291,W293,E203"
RUFF_LINE_LENGTH = "120"

RUFF_CONFIG_NAMES: tuple[str, ...] = ("ruff.toml", ".ruff.toml")
PYPROJECT_NAME = "pyproject.toml"
RUFF_SECTION_MARK = "[tool.ruff"

CHECK_TIMEOUT_SECONDS = 900
MAX_WORKERS = 8

MARK_OK = "✓"
MARK_WARN = "⚠"
MARK_SKIP = "⊘"


@dataclass(frozen=True)
class RunResult:
    """一次子进程调用的结果。"""

    code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return "\n".join(
            part for part in (self.stdout.strip(), self.stderr.strip()) if part
        )


@dataclass(frozen=True)
class Check:
    """一条待执行的校验命令。"""

    tool: str
    label: str
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CheckOutcome:
    """一条校验命令的执行结果。"""

    check: Check
    passed: bool
    detail: str


def _run(
    argv: tuple[str, ...], cwd: Path, env: dict[str, str] | None = None
) -> RunResult:
    """执行一条命令；可执行文件缺失或超时都收敛为失败结果，不抛异常。"""
    try:
        # argv 全部由本脚本构造（首个元素是 shutil.which 解析出的绝对路径），非外部输入
        proc = subprocess.run(  # noqa: S603
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CHECK_TIMEOUT_SECONDS,
            shell=False,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return RunResult(code=-1, stdout="", stderr=f"{argv[0]}: not found")
    except subprocess.TimeoutExpired:
        return RunResult(
            code=-1, stdout="", stderr=f"timeout after {CHECK_TIMEOUT_SECONDS}s"
        )
    except OSError as exc:
        return RunResult(code=-1, stdout="", stderr=str(exc))
    return RunResult(code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def _tool_path(name: str) -> str | None:
    """解析工具的可执行文件绝对路径，未安装时返回 None。"""
    return shutil.which(name)


def _probe(tools: tuple[str, ...]) -> dict[str, str | None]:
    """探测工具是否可用，返回 工具名 -> 可执行文件路径 或 None。"""
    return {tool: _tool_path(tool) for tool in tools}


def _git_lines(git_exe: str, argv: tuple[str, ...], cwd: Path) -> list[str]:
    """取 git 命令的 stdout 行；git 报错时返回空列表。

    core.quotepath=false 让非 ASCII 路径按原文输出，否则会被转义成八进制，
    后续按转义串找文件必然落空。
    """
    result = _run((git_exe, "-c", "core.quotepath=false", *argv), cwd)
    if result.code != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _parse_porcelain(lines: list[str]) -> list[str]:
    """从 `git status --porcelain` 输出中取出路径，兼容重命名与引号包裹。"""
    paths: list[str] = []
    for line in lines:
        body = line[3:] if len(line) > 3 else line
        if " -> " in body:
            body = body.split(" -> ", 1)[1]
        cleaned = body.strip().strip('"')
        if cleaned:
            paths.append(cleaned)
    return paths


def _classify(paths: list[Path]) -> tuple[list[str], list[str]]:
    """按后缀把路径分成 (python, shell)。"""
    py_files = [str(path) for path in paths if path.suffix == PY_SUFFIX]
    sh_files = [str(path) for path in paths if path.suffix == SH_SUFFIX]
    return py_files, sh_files


def discover_changed_files(
    root: Path, git_exe: str
) -> tuple[list[str], list[str], int]:
    """发现本次改动的 (python, shell) 文件与被跳过的删除文件数；非 git 仓库返回空。

    `--untracked-files=all` 不可省略：默认模式下 git 对未跟踪目录只输出目录本身，
    新文件会被整体漏检。
    """
    top_level = _git_lines(git_exe, ("rev-parse", "--show-toplevel"), root)
    if not top_level:
        return [], [], 0
    repo = Path(top_level[0])
    tracked = _git_lines(git_exe, ("diff", "--name-only", "HEAD"), repo)
    staged = _parse_porcelain(
        _git_lines(git_exe, ("status", "--porcelain", "--untracked-files=all"), repo)
    )
    unique = sorted({*tracked, *staged})
    # 删除是合法改动：自动发现只送检仍存在的文件，避免对已删路径误报；
    # --files 显式指定不受此过滤影响，保持响亮失败。
    existing = [rel for rel in unique if (repo / rel).exists()]
    py_files, sh_files = _classify([repo / rel for rel in existing])
    return py_files, sh_files, len(unique) - len(existing)


def _explicit_files(root: Path, names: list[str]) -> tuple[list[str], list[str]]:
    """把 --files 传入的路径解析为绝对路径并分类。"""
    return _classify([(root / name).resolve() for name in names])


def _is_own_file(target: str) -> bool:
    """判断路径是否位于本技能目录之内（技能自身的安装副本）。"""
    try:
        Path(target).resolve().relative_to(SKILL_ROOT)
    except ValueError:
        return False
    return True


def _drop_own_files(files: list[str]) -> tuple[list[str], int]:
    """剔除技能自身文件，返回 (保留项, 被剔除数量)。"""
    kept = [item for item in files if not _is_own_file(item)]
    return kept, len(files) - len(kept)


def _needed_tools(level: str, has_py: bool, has_sh: bool) -> list[str]:
    """得出该级别在本次改动下真正需要的工具清单。"""
    needed: list[str] = list(LEVEL_TOOLS[level]) if has_py else []
    if has_sh:
        needed.append(SHELL_TOOL)
    return needed


def _make_check(
    tool: str, exe: str, args: tuple[str, ...], env: tuple[tuple[str, str], ...] = ()
) -> Check:
    """构造一条校验命令；label 用工具名代替可执行文件路径，便于阅读。"""
    return Check(tool=tool, label=" ".join((tool, *args)), argv=(exe, *args), env=env)


def _make_py_compile_check(py_files: list[str], temp_root: Path) -> Check:
    """ruff 缺失时的语法底线：用解释器自带的 py_compile，字节码重定向到临时目录。

    label 带上解释器版本：py_compile 的结论取决于运行它的解释器，与项目目标版本
    不一致时可能误报（例如 3.13 不认识 3.14 的 t-string 语法）。
    """
    version = sys.version.split()[0]
    return Check(
        tool=PY_COMPILE_TOOL,
        label=" ".join((PY_COMPILE_TOOL, f"Python {version}", *py_files)),
        argv=(sys.executable, "-m", "py_compile", *py_files),
        env=((PYCACHE_ENV, str(temp_root / "pycache")),),
    )


def _has_project_ruff_config(cwd: Path) -> bool:
    """被测项目自带 ruff 配置时返回 True；此时不传兜底参数，让 ruff 读项目自己的规则。"""
    if any((cwd / name).is_file() for name in RUFF_CONFIG_NAMES):
        return True
    pyproject = cwd / PYPROJECT_NAME
    return pyproject.is_file() and RUFF_SECTION_MARK in pyproject.read_text(
        encoding="utf-8", errors="replace"
    )


def _build_ruff_checks(
    ruff: str, py_files: list[str], fast: bool, respect_config: bool
) -> list[Check]:
    """ruff check + format --check；respect_config 时不传兜底参数，以项目配置为准。"""
    # 默认隔离：ruff 用 --no-cache（它默认会往 CWD 写 .ruff_cache）
    ruff_nocache = () if fast else ("--no-cache",)
    check_args: tuple[str, ...] = ("check",)
    if not respect_config:
        check_args += (
            "--select",
            RUFF_SELECT,
            "--ignore",
            RUFF_IGNORE,
            "--line-length",
            RUFF_LINE_LENGTH,
        )
    return [
        _make_check("ruff", ruff, (*check_args, *ruff_nocache, *py_files)),
        _make_check("ruff", ruff, ("format", "--check", *ruff_nocache, *py_files)),
    ]


def _build_type_checks(
    level: str,
    py_files: list[str],
    exe: dict[str, str | None],
    temp_root: Path,
    fast: bool,
    cwd: Path,
    project_scope: bool,
) -> list[Check]:
    """该级别要求的类型检查器；--project-scope 时扫整个项目，否则只扫改动文件。

    --project-scope 抓「改公共签名破坏下游调用方」这类单文件检查必然漏报的问题；
    ruff 与 bash 仍只查改动文件，避免存量风格噪音。
    """
    wanted = set(LEVEL_TOOLS[level])
    type_target: tuple[str, ...] = (str(cwd),) if project_scope else tuple(py_files)
    checks: list[Check] = []
    for tool, command in (
        ("ty", ("check",)),
        ("pyrefly", ("check",)),
        ("pyright", ()),
    ):
        if tool in wanted and exe.get(tool):
            checks.append(_make_check(tool, str(exe[tool]), (*command, *type_target)))
    if "mypy" in wanted and exe.get("mypy"):
        # 默认隔离：mypy 用临时 cache-dir，避免写项目
        mypy_cache = () if fast else ("--cache-dir", str(temp_root / "mypy"))
        checks.append(
            _make_check(
                "mypy", str(exe["mypy"]), ("--strict", *mypy_cache, *type_target)
            )
        )
    return checks


def _build_shell_checks(sh_files: list[str]) -> list[Check]:
    """bash -n 语法检查；shellcheck 存在则加跑（可选增强，缺失不影响判定）。"""
    if not sh_files:
        return []
    checks: list[Check] = []
    shell = _tool_path(SHELL_TOOL)
    if shell:
        checks.append(_make_check(SHELL_TOOL, shell, ("-n", *sh_files)))
        shellcheck = _tool_path("shellcheck")
        if shellcheck:
            checks.append(_make_check("shellcheck", shellcheck, (*sh_files,)))
    return checks


def _build_checks(
    level: str,
    py_files: list[str],
    sh_files: list[str],
    exe: dict[str, str | None],
    temp_root: Path,
    fast: bool,
    cwd: Path,
    project_scope: bool = False,
    respect_ruff_config: bool = False,
) -> list[Check]:
    """按级别与实际可用工具构造校验命令清单；不可用的工具自然缺席。"""
    checks: list[Check] = []
    ruff = exe.get("ruff")
    if py_files and ruff:
        checks.extend(_build_ruff_checks(ruff, py_files, fast, respect_ruff_config))
        checks.extend(
            _build_type_checks(
                level, py_files, exe, temp_root, fast, cwd, project_scope
            )
        )
    elif py_files:
        # 有 .py 改动却没有 ruff：用解释器自带的 py_compile 保住语法底线
        checks.append(_make_py_compile_check(py_files, temp_root))
    checks.extend(_build_shell_checks(sh_files))
    return checks


def _execute(check: Check, cwd: Path) -> CheckOutcome:
    """执行单条校验命令。"""
    env = {**os.environ, **dict(check.env)} if check.env else None
    result = _run(check.argv, cwd, env)
    return CheckOutcome(check=check, passed=result.code == 0, detail=result.output)


def _install_missing(tools: list[str], cwd: Path, uv_exe: str) -> None:
    """在调用方已获用户授权的前提下，用 uv 逐个安装工具。

    不返回安装结果：调用方随后重新探测工具，一律以探测结果为准。
    """
    for tool in tools:
        print(f"安装缺失工具: uv tool install {tool} --upgrade")
        result = _run((uv_exe, "tool", "install", tool, "--upgrade"), cwd)
        if result.code != 0:
            print(f"  安装失败: {result.output or 'unknown error'}")


def _print_probe(exe: dict[str, str | None]) -> None:
    """打印工具清单。"""
    print("工具清单:")
    for tool, path in exe.items():
        print(
            f"  {tool:<9} {MARK_OK} {path}"
            if path
            else f"  {tool:<9} {MARK_SKIP} 未安装"
        )


def _print_outcome(outcome: CheckOutcome) -> None:
    """打印单条失败校验的详情。"""
    print(f"\n--- 失败: {outcome.check.label} ---")
    print(outcome.detail or "(无输出)")


def _report(
    level: str, outcomes: list[CheckOutcome], degraded: list[str], hard: list[str]
) -> bool:
    """打印汇总，返回该级别的校验是否全部真实执行且通过。"""
    print(f"后置校验 {level}")
    if outcomes:
        marks = " | ".join(
            f"{item.check.tool} {MARK_OK if item.passed else MARK_WARN}"
            for item in outcomes
        )
        print(f"执行: {marks}")
    for outcome in outcomes:
        if not outcome.passed:
            _print_outcome(outcome)
    missing = [*hard, *degraded]
    uv_missing = [tool for tool in missing if tool not in NON_UV_TOOLS]
    if uv_missing:
        hint = ", ".join(
            f"{tool} → uv tool install {tool} --upgrade" for tool in uv_missing
        )
        print(f"缺失工具: {hint}")
    if SHELL_TOOL in missing:
        print(
            f"缺失工具: {SHELL_TOOL} → 需自行安装 bash（Git Bash / WSL 等），uv 无法代装"
        )

    failed = [item for item in outcomes if not item.passed]
    if not outcomes:
        print("verify: 未校验 — 没有任何校验被真实执行，不得视为已通过")
        return False
    if failed:
        print(f"verify: 失败 — {len(failed)} 项校验未通过")
        return False
    if hard:
        print(
            f"verify: 未通过 — 必需工具缺失: {', '.join(hard)}（不可降级），不得视为已通过"
        )
        return False
    if degraded:
        print(
            f"verify: 未完全通过 — {', '.join(degraded)} 缺失，对应校验未真正执行，不得视为已通过"
        )
        return False
    print(f"verify: 全部通过 ({level})")
    return True


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="改动分级后置校验")
    parser.add_argument(
        "--level", choices=sorted(LEVEL_TOOLS), help="本次改动适用的校验级别"
    )
    parser.add_argument(
        "--files", nargs="+", default=None, help="显式指定文件，默认自动发现改动"
    )
    parser.add_argument(
        "--fast", action="store_true", help="使用项目缓存换取增量速度（默认隔离缓存）"
    )
    parser.add_argument(
        "--project-scope",
        action="store_true",
        help="类型工具改扫整个项目目录（L3/L4 公共接口变更时用，防漏报下游调用方）",
    )
    parser.add_argument("--probe", action="store_true", help="只打印工具清单后退出")
    parser.add_argument(
        "--install-missing", action="store_true", help="经用户同意后安装缺失工具"
    )
    args = parser.parse_args(argv)
    if not args.probe and not args.level:
        parser.error("需要 --level，或用 --probe 只查看工具清单")
    return args


def _collect_files(
    args: argparse.Namespace, cwd: Path, git_exe: str | None
) -> tuple[list[str], list[str], int]:
    """按优先级收集待校验文件：--files 优先，否则从 git 发现；附带跳过的删除数。"""
    if args.files:
        py_files, sh_files = _explicit_files(cwd, args.files)
        return py_files, sh_files, 0
    if git_exe is None:
        return [], [], 0
    return discover_changed_files(cwd, git_exe)


def _resolve_missing(
    tools: list[str], cwd: Path, install_missing: bool
) -> dict[str, str | None]:
    """探测工具；在获授权时尝试用 uv 补齐，返回最终探测结果。"""
    exe = _probe(tuple(tools))
    installable = [
        tool for tool in tools if exe[tool] is None and tool not in NON_UV_TOOLS
    ]
    if not installable or not install_missing:
        return exe
    uv_exe = _tool_path(UV)
    if uv_exe is None:
        print("缺少 uv，无法安装校验工具链；请自行安装 uv 后重试")
        return exe
    _install_missing(installable, cwd, uv_exe)
    return _probe(tuple(tools))


def _force_utf8_stdout() -> None:
    """在 Windows 控制台强制 UTF-8 输出，避免非 ASCII 标记触发编码错误。"""
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _handle_empty_changes(
    args: argparse.Namespace, py_files: list[str], sh_files: list[str], skipped: int
) -> int | None:
    """无适用文件时的裁决：打印结论并返回退出码；仍有适用文件时返回 None。"""
    if py_files or sh_files:
        return None
    if skipped:
        # 改动仅为删除：本就没有静态校验对象，不是校验缺口，不算失败
        print("改动均为删除文件，无静态校验对象")
        print("verify: 通过 (无适用校验对象)")
        return 0
    if args.files:
        print(f"--files 传入的 {len(args.files)} 个路径中不含 .py / .sh 文件")
    else:
        print("未发现改动的 .py / .sh 文件（若改动已提交，请用 --files 显式指定）")
    print("verify: 未校验 — 不得视为已通过")
    return 1


def _print_mode_notes(
    args: argparse.Namespace, py_files: list[str], sh_files: list[str], cwd: Path
) -> bool:
    """打印本次运行的开关状态；返回是否启用项目自带 ruff 配置。"""
    if args.project_scope:
        print("类型工具按项目级扫描（--project-scope）：可能连带暴露项目存量类型错误")
    if sh_files and _tool_path("shellcheck") is None:
        print(
            "可选增强: shellcheck 未安装，shell 校验仅 bash -n（不影响判定，可自行安装后重跑）"
        )
    respect_ruff_config = bool(py_files and _has_project_ruff_config(cwd))
    if respect_ruff_config:
        print(
            "检测到项目自带 ruff 配置（pyproject.toml / ruff.toml），不使用脚本兜底参数"
        )
    return respect_ruff_config


def _execute_checks(
    args: argparse.Namespace,
    py_files: list[str],
    sh_files: list[str],
    exe: dict[str, str | None],
    cwd: Path,
    respect_ruff_config: bool,
) -> list[CheckOutcome]:
    """构造并并行执行全部校验命令；临时缓存目录用完即清。"""
    temp_root = Path(tempfile.mkdtemp(prefix="change-linter-"))
    try:
        checks = _build_checks(
            args.level,
            py_files,
            sh_files,
            exe,
            temp_root,
            args.fast,
            cwd,
            args.project_scope,
            respect_ruff_config,
        )
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            return list(pool.map(partial(_execute, cwd=cwd), checks))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    """入口。"""
    args = _parse_args(argv)
    _force_utf8_stdout()
    cwd = Path.cwd()

    if args.probe:
        _print_probe(_probe(PROBE_TOOLS))
        return 0

    py_files, sh_files, skipped = _collect_files(args, cwd, _tool_path(GIT))
    if not args.files:
        py_files, removed_py = _drop_own_files(py_files)
        sh_files, removed_sh = _drop_own_files(sh_files)
        if removed_py + removed_sh:
            print(
                f"已排除本技能自身文件 {removed_py + removed_sh} 个（确需检查请用 --files 显式指定）"
            )
    if skipped:
        print(f"已跳过已删除文件 {skipped} 个（删除属合法改动，无需送检）")
    empty_verdict = _handle_empty_changes(args, py_files, sh_files, skipped)
    if empty_verdict is not None:
        return empty_verdict

    respect_ruff_config = _print_mode_notes(args, py_files, sh_files, cwd)
    needed = _needed_tools(args.level, bool(py_files), bool(sh_files))
    exe = _resolve_missing(needed, cwd, args.install_missing)
    missing = [tool for tool in needed if exe[tool] is None]
    hard = [tool for tool in missing if tool in REQUIRED_TOOLS]
    degraded = [tool for tool in missing if tool in DEGRADABLE_TOOLS]
    outcomes = _execute_checks(args, py_files, sh_files, exe, cwd, respect_ruff_config)
    return 0 if _report(args.level, outcomes, degraded, hard) else 1


if __name__ == "__main__":
    sys.exit(main())
