#!/usr/bin/env python
"""改动分级后置校验。

按调用方指定的 Level，对本次改动的 .py / .sh 文件执行静态检查。

级别判定不属本脚本职责 —— 脚本只做机械部分：发现改动文件、探测工具、
并行执行、汇总结果与退出码。

复杂度（C901）随 ruff 一起跑，但阈值分两档：本次改动碰过的函数按 8 卡，
同一次改动里没碰过的存量函数放宽到 12；阈值判定在脚本内完成，不交给
ruff 的退出码。

另有两条与 Level 正交的可选轴，由调用方按「改动的性质」开启，不并入级别编号：

    --security  bandit 扫本次改动的 .py（源码安全）
    --deps      pip-audit 审依赖漏洞；来源取 lock 文件或 requirements*.txt，
                需要网络，跑不动时记为「未校验」而不是「失败」

退出码：
    0  该 Level 的全部校验都真实执行且通过；或改动仅为删除文件（无适用校验对象）
    1  存在校验失败，或存在未真正执行的校验（缺工具 / 无适用改动）
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
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

# 两个正交轴：源码安全扫描与依赖漏洞审计。它们与 L1–L4 的「类型检查深度」无关，
# 由改动的性质触发，因此不并入级别编号——否则「只改了一个依赖」也会被要求跑 mypy --strict。
SECURITY_TOOL = "bandit"
DEPS_TOOL = "pip-audit"

PROBE_TOOLS: tuple[str, ...] = (
    "ruff",
    "ty",
    "pyrefly",
    "pyright",
    "mypy",
    SHELL_TOOL,
    "shellcheck",
    SECURITY_TOOL,
    DEPS_TOOL,
    UV,
    GIT,
)

# 缺失即硬失败、不可降级的工具
REQUIRED_TOOLS: frozenset[str] = frozenset({"ruff"})

# 缺失则降级并显式标注“该级未真正校验”的工具
DEGRADABLE_TOOLS: frozenset[str] = frozenset(
    {"ty", "pyrefly", "pyright", "mypy", SHELL_TOOL, SECURITY_TOOL, DEPS_TOOL}
)

# 不能经 uv tool install 安装的工具（bash 由系统提供，缺失时只能提示用户自装）
NON_UV_TOOLS: frozenset[str] = frozenset({SHELL_TOOL})

# ruff 缺省兜底参数：仅当被测项目未自带 ruff 配置时才传给 ruff，
# 项目自带配置（pyproject.toml 的 [tool.ruff] / ruff.toml）时以项目为准。
# B(bugbear) / UP(pyupgrade) / DTZ(flake8-datetimez) 专门拦模型最容易犯的两类：
# 从训练数据里带出来的过时写法（datetime.utcnow()、typing.List）与时区裸 datetime
RUFF_SELECT = "E,F,W,I,S,PERF,B,UP,DTZ"
RUFF_IGNORE = "W291,W293,E203"
RUFF_LINE_LENGTH = "120"

RUFF_CONFIG_NAMES: tuple[str, ...] = ("ruff.toml", ".ruff.toml")
PYPROJECT_NAME = "pyproject.toml"
RUFF_SECTION_MARK = "[tool.ruff"

# bandit：只把本次改动的 .py 当 target（不传 -r .），存量噪音在源头就不进报告。
# 严重度与置信度都抬到 medium，挡掉最常见的低危噪音（如测试文件里的 B101 assert_used）
BANDIT_SEVERITY = "medium"
BANDIT_CONFIDENCE = "medium"

# pip-audit：必须显式给依赖来源。裸跑审计的是 uvx / uv tool 自己的隔离环境，
# 会给出「没发现漏洞」的假绿（实测：裸跑只收集到 pip-audit 自己的 28 个包）
DEPS_LOCK_NAMES: tuple[str, ...] = ("uv.lock", "poetry.lock", "Pipfile.lock")
DEPS_REQUIREMENT_GLOBS: tuple[str, ...] = (
    "requirements*.txt",
    "requirements/*.txt",
)
DEPS_SOURCE_NAME = "依赖来源"

# 解析不出 JSON 时的两类原因：环境坏了（依赖文件缺失）与跑不通（离线等）。
# 前者在本机实测发生过——杀软把 cyclonedx/model/vulnerability.py 当病毒删掉，
# 而它在导入链上（_format → cyclonedx → model.bom → model.vulnerability），
# 删了连 -f json 都起不来。两类原因的补救完全不同，必须分开说。
DEPS_ENV_BROKEN_MARKERS: tuple[str, ...] = ("ModuleNotFoundError", "ImportError")
DEPS_ENV_BROKEN_HINT = (
    "pip-audit 自身环境不完整（依赖文件缺失，实测 cyclonedx/model/vulnerability.py "
    "会被杀软误杀）——重装：uv tool install pip-audit --upgrade，"
    "并给 uv tool 目录加杀软白名单"
)
DEPS_UNPARSABLE_HINT = (
    "无法解析 pip-audit 的 JSON 输出，本次依赖审计未真正执行（原始输出见上）。"
    "常见原因：离线、漏洞库服务不可用、依赖来源文件无法解析"
)

# C901 复杂度双阈值：本次改动碰过的函数按新代码标准卡，存量函数放宽
COMPLEXITY_LABEL = "complexity"
COMPLEXITY_NEW_LIMIT = 8
COMPLEXITY_LEGACY_LIMIT = 12
COMPLEXITY_RULE = "C901"

# bash 不在 PATH 时的回退位置：Git for Windows 自带 bash，但默认不写进 PATH
BASH_FALLBACK_PARTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ProgramFiles", ("Git", "bin", "bash.exe")),
    ("ProgramFiles", ("Git", "usr", "bin", "bash.exe")),
    ("ProgramFiles(x86)", ("Git", "bin", "bash.exe")),
    ("LOCALAPPDATA", ("Programs", "Git", "bin", "bash.exe")),
)

# ruff concise 输出：<path>:<line>:<col>: C901 `name` is too complex (N > limit)
C901_LINE = re.compile(
    r"^(?P<path>.+):(?P<line>\d+):\d+: C901 .+ is too complex \((?P<value>\d+) > \d+\)$"
)
# 统一 diff 的块头；-U0 时新增行区间就是 [start, start+count-1]
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")

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
    """一条校验命令的执行结果。

    gap=True 表示「这条校验没能真正跑成」（例如依赖审计因离线无法完成）：
    既不算通过，也不该报成「失败」——后者会被读成代码有问题。
    """

    check: Check
    passed: bool
    detail: str
    gap: bool = False


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


def _bash_fallback() -> str | None:
    """PATH 上没有 bash 时，回退到 Git for Windows 的常见安装位置。

    Git for Windows 默认只把 cmd/ 加进 PATH，bin/bash.exe 往往不在其中；
    直接判「未安装」会让所有 .sh 改动变成不可校验，故按已知位置探测。
    """
    for env_name, parts in BASH_FALLBACK_PARTS:
        base = os.environ.get(env_name)
        if not base:
            continue
        candidate = Path(base).joinpath(*parts)
        if candidate.is_file():
            return str(candidate)
    return None


def _tool_path(name: str) -> str | None:
    """解析工具的可执行文件绝对路径，未安装时返回 None。"""
    found = shutil.which(name)
    if found is None and name == SHELL_TOOL:
        found = _bash_fallback()
    return found


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


def _needed_tools(
    level: str,
    has_py: bool,
    has_sh: bool,
    security: bool = False,
    deps: bool = False,
) -> list[str]:
    """得出该级别与本次开启的轴真正需要的工具清单。"""
    needed: list[str] = list(LEVEL_TOOLS[level]) if has_py else []
    if has_sh:
        needed.append(SHELL_TOOL)
    if security and has_py:
        needed.append(SECURITY_TOOL)
    if deps:
        needed.append(DEPS_TOOL)
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


def _find_ruff_config_root(start: Path) -> Path | None:
    """向上查找自带 ruff 配置的目录，找不到返回 None。

    返回的目录同时作为校验子进程的工作目录：ruff 的 per-file-ignores 按
    「文件相对工作目录的路径」匹配，工作目录与配置所在目录不一致时豁免规则会静默失配
    （表现为对 tests/** 之类规则的假阳性）。
    """
    for candidate in (start, *start.parents):
        if any((candidate / name).is_file() for name in RUFF_CONFIG_NAMES):
            return candidate
        pyproject = candidate / PYPROJECT_NAME
        if pyproject.is_file() and RUFF_SECTION_MARK in pyproject.read_text(
            encoding="utf-8", errors="replace"
        ):
            return candidate
    return None


def _relative_or_original(raw: str, root: Path) -> str:
    """单个路径相对化；不在 root 之内时原样返回。"""
    try:
        return Path(raw).relative_to(root).as_posix()
    except ValueError:
        return raw


def _relativize(paths: list[str], root: Path) -> list[str]:
    """把文件路径转成相对 root 的形式；不在 root 之内的保持原样。"""
    return [_relative_or_original(raw, root) for raw in paths]


def _config_root_for(cwd: Path, files: list[str]) -> Path | None:
    """定位配置根：先按 cwd 上溯，找不到再按首个目标文件所在目录上溯。

    调用方可能在项目之外（脚本被从任意目录调用），只按 cwd 找会漏掉配置，
    导致 per-file-ignores 失配。
    """
    found = _find_ruff_config_root(cwd)
    if found is not None or not files:
        return found
    return _find_ruff_config_root(Path(files[0]).resolve().parent)


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


def _build_security_check(bandit: str, py_files: list[str]) -> Check:
    """bandit 源码安全扫描。

    目标就是本次改动的 .py，不传 -r .：全仓扫描会把存量问题一起倒出来，
    而本技能的契约是「只校验本次改动」。代价是 .bandit 配置只在 -r 时自动加载，
    项目级 bandit 配置不生效——用 --severity-level medium 兜住最常见的低危噪音。
    """
    return _make_check(
        SECURITY_TOOL,
        bandit,
        (
            "--format",
            "json",
            "--severity-level",
            BANDIT_SEVERITY,
            "--confidence-level",
            BANDIT_CONFIDENCE,
            *py_files,
        ),
    )


def _resolve_deps_source(root: Path) -> tuple[str, ...] | None:
    """探测依赖来源，返回 pip-audit 的目标参数；找不到来源时返回 None。

    必须显式给来源：裸跑 pip-audit 审计的是它自己所在的隔离环境，
    会输出「没发现漏洞」的假绿。
    """
    for name in DEPS_LOCK_NAMES:
        if (root / name).is_file():
            return ("--locked", str(root))
    requirements: list[str] = []
    for pattern in DEPS_REQUIREMENT_GLOBS:
        requirements.extend(sorted(str(item) for item in root.glob(pattern)))
    if not requirements:
        return None
    args: list[str] = []
    for item in requirements:
        args.extend(("-r", item))
    return tuple(args)


def _build_deps_check(pip_audit: str, target: tuple[str, ...]) -> Check:
    """pip-audit 依赖漏洞审计。

    --strict 让依赖收集失败也整体失败，不静默放过；退出码 1 同时表示
    「有漏洞」与「跑挂了」，所以判定一律以 JSON 解析结果为准。
    """
    return _make_check(
        DEPS_TOOL,
        pip_audit,
        ("--format", "json", "--progress-spinner", "off", "--strict", *target),
    )


def _build_complexity_check(ruff: str, py_files: list[str], fast: bool) -> Check:
    """C901 复杂度：先按新代码阈值跑，超出的部分再由 diff 区分存量与新增。

    阈值判定不能交给 ruff 的退出码：存量 8~12 的函数要放过，只有新代码 >8
    或存量 >12 才算问题，因此单独成一条 check 并在结果里二次裁决。
    """
    nocache = () if fast else ("--no-cache",)
    return _make_check(
        COMPLEXITY_LABEL,
        ruff,
        (
            "check",
            "--select",
            COMPLEXITY_RULE,
            "--config",
            f"lint.mccabe.max-complexity={COMPLEXITY_NEW_LIMIT}",
            "--output-format",
            "concise",
            *nocache,
            *py_files,
        ),
    )


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
    deps_target: tuple[str, ...] | None = None,
) -> list[Check]:
    """按级别、已开启的轴与实际可用工具构造校验命令清单；不可用的工具自然缺席。

    两个正交轴不额外传布尔开关：`exe` 里有没有对应的可执行文件，就代表该轴是否开启
    （`_needed_tools` 只在开关打开时才把工具名加进探测清单）。
    """
    checks: list[Check] = []
    ruff = exe.get("ruff")
    if py_files and ruff:
        checks.extend(_build_ruff_checks(ruff, py_files, fast, respect_ruff_config))
        checks.append(_build_complexity_check(ruff, py_files, fast))
        checks.extend(
            _build_type_checks(
                level, py_files, exe, temp_root, fast, cwd, project_scope
            )
        )
    elif py_files:
        # 有 .py 改动却没有 ruff：用解释器自带的 py_compile 保住语法底线
        checks.append(_make_py_compile_check(py_files, temp_root))
    checks.extend(_build_shell_checks(sh_files))
    # 安全轴只扫本次改动的 .py；没有 .py 改动时无对象可扫，由调用方给出提示
    bandit = exe.get(SECURITY_TOOL)
    if py_files and bandit:
        checks.append(_build_security_check(bandit, py_files))
    # 依赖轴与文件改动无关：只改了 lock 文件时它照样要跑
    pip_audit = exe.get(DEPS_TOOL)
    if deps_target is not None and pip_audit:
        checks.append(_build_deps_check(pip_audit, deps_target))
    return checks


def _is_untracked(git_exe: str, repo: Path, relative: str) -> bool:
    """文件是否尚未进入 HEAD；新增/未跟踪文件整file都算本次改动。"""
    probe = _run((git_exe, "cat-file", "-e", f"HEAD:{relative}"), repo)
    return probe.code != 0


def _spans_from_diff(git_exe: str, repo: Path, relative: str) -> list[tuple[int, int]]:
    """解析 `git diff -U0` 的块头，得到该文件的新增行区间。"""
    spans: list[tuple[int, int]] = []
    diff = _git_lines(
        git_exe, ("diff", "-U0", "--no-color", "HEAD", "--", relative), repo
    )
    for line in diff:
        match = HUNK_HEADER.match(line)
        if match is None:
            continue
        start = int(match.group("start"))
        count = int(match.group("count") or 1)
        if count > 0:
            spans.append((start, start + count - 1))
    return spans


def _file_spans(
    cwd: Path, git_exe: str, repo: Path, name: str
) -> list[tuple[int, int]]:
    """单个文件的改动行区间；不在仓库内返回空，未跟踪文件整file算改动。"""
    absolute = Path(name)
    if not absolute.is_absolute():
        absolute = (cwd / name).resolve()
    try:
        relative = absolute.relative_to(repo).as_posix()
    except ValueError:
        return []
    spans = _spans_from_diff(git_exe, repo, relative)
    if not spans and _is_untracked(git_exe, repo, relative):
        return [(1, sys.maxsize)]
    return spans


def _changed_line_ranges(
    cwd: Path, git_exe: str | None, files: list[str]
) -> dict[str, list[tuple[int, int]]]:
    """取每个文件本次新增/修改的行区间，键为传入的路径原文（与 ruff 输出一致）。

    取不到 diff（非 git、路径不在仓库内、改动已提交）时返回空区间，调用方据此
    退化为存量口径，不会误判成"新代码"。
    """
    if git_exe is None or not files:
        return {}
    top_level = _git_lines(git_exe, ("rev-parse", "--show-toplevel"), cwd)
    if not top_level:
        return {}
    repo = Path(top_level[0])
    return {name: _file_spans(cwd, git_exe, repo, name) for name in files}


def _render_complexity(
    new_hits: list[tuple[str, int, int]],
    legacy_hits: list[tuple[str, int, int]],
    tolerated: int,
) -> str:
    """把复杂度裁决结果渲染成固定三段。"""
    lines = [
        f"新代码超限（>{COMPLEXITY_NEW_LIMIT}）{len(new_hits)} 处"
        + (
            ": "
            + "；".join(
                f"{path}:{line} 复杂度 {value}" for path, line, value in new_hits
            )
            if new_hits
            else ""
        ),
        f"存量超限（>{COMPLEXITY_LEGACY_LIMIT}）{len(legacy_hits)} 处"
        + (
            ": "
            + "；".join(
                f"{path}:{line} 复杂度 {value}" for path, line, value in legacy_hits
            )
            if legacy_hits
            else ""
        ),
        f"存量容忍（{COMPLEXITY_NEW_LIMIT}~{COMPLEXITY_LEGACY_LIMIT}）{tolerated} 处",
    ]
    return "\n".join(lines)


def _parse_complexity_findings(detail: str) -> list[tuple[str, int, int]]:
    """从 ruff concise 输出里取出 (路径, 行号, 复杂度)。"""
    findings: list[tuple[str, int, int]] = []
    for line in detail.splitlines():
        match = C901_LINE.match(line.strip())
        if match is not None:
            findings.append(
                (
                    match.group("path"),
                    int(match.group("line")),
                    int(match.group("value")),
                )
            )
    return findings


def _classify_complexity(
    findings: list[tuple[str, int, int]],
    ranges: dict[str, list[tuple[int, int]]],
) -> tuple[list[tuple[str, int, int]], list[tuple[str, int, int]], int]:
    """把命中分成 (新代码超限, 存量超限, 存量容忍数)。"""
    new_hits: list[tuple[str, int, int]] = []
    legacy_hits: list[tuple[str, int, int]] = []
    tolerated = 0
    for path, line, value in findings:
        spans = ranges.get(path, [])
        if any(start <= line <= end for start, end in spans):
            new_hits.append((path, line, value))
        elif value > COMPLEXITY_LEGACY_LIMIT:
            legacy_hits.append((path, line, value))
        else:
            tolerated += 1
    return new_hits, legacy_hits, tolerated


def _finalize_complexity(outcome: CheckOutcome, cwd: Path) -> CheckOutcome:
    """按「新代码 >8 / 存量 >12」重判 C901 结果，并替换成可读的三段式输出。

    改动过的函数按新代码阈值，同一次改动里没碰过的存量函数放宽到 12；
    取不到 diff 信息时一律按存量口径，避免把老函数误判成新代码而制造噪音。
    """
    findings = _parse_complexity_findings(outcome.detail)
    if not findings:
        if outcome.passed:
            # 无命中时 ruff 的成功输出（All checks passed!）对读者没有信息量
            return CheckOutcome(
                check=outcome.check,
                passed=True,
                detail=(
                    f"无超限（新代码 >{COMPLEXITY_NEW_LIMIT} / "
                    f"存量 >{COMPLEXITY_LEGACY_LIMIT}）"
                ),
            )
        # ruff 自身报错（例如文件找不到）：原样保留，别把真实错误吞掉
        return outcome
    ranges = _changed_line_ranges(
        cwd, _tool_path(GIT), [path for path, _, _ in findings]
    )
    new_hits, legacy_hits, tolerated = _classify_complexity(findings, ranges)
    detail = _render_complexity(new_hits, legacy_hits, tolerated)
    if tolerated and not new_hits and not legacy_hits:
        detail += "\n存量函数放宽到 12；改动过的函数卡 8"
    return CheckOutcome(
        check=outcome.check,
        passed=not (new_hits or legacy_hits),
        detail=detail,
    )


def _extract_json(text: str) -> object | None:
    """从可能夹着日志的输出里取出最外层 JSON 对象；取不到返回 None。"""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        # 先落到 object 再返回：json.loads 的返回类型是 Any，
        # 直接 return 会让 mypy --strict 报 no-any-return
        parsed: object = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return parsed


def _finalize_security(outcome: CheckOutcome) -> CheckOutcome:
    """bandit 的判定不看退出码：解析 JSON 后自行裁决，与复杂度检查同一原则。"""
    payload = _extract_json(outcome.detail)
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        # bandit 自身报错（参数错、文件找不到）：原样保留，别把真实错误吞掉
        return outcome
    if not results:
        return CheckOutcome(
            check=outcome.check,
            passed=True,
            detail=(
                f"无 {BANDIT_SEVERITY} 及以上的安全问题"
                f"（严重度 / 置信度均 ≥ {BANDIT_CONFIDENCE}）"
            ),
        )
    lines = [f"{len(results)} 处 {BANDIT_SEVERITY} 及以上问题："]
    for item in results:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"{item.get('filename')}:{item.get('line_number')} "
            f"{item.get('test_id')} "
            f"[{item.get('issue_severity')}/{item.get('issue_confidence')}] "
            f"{item.get('issue_text')}"
        )
    return CheckOutcome(check=outcome.check, passed=False, detail="\n".join(lines))


def _unique_vuln_ids(vulns: object) -> list[str]:
    """取出漏洞 ID 并去重。

    pip-audit 会对同一漏洞重复列出（同一个 ID 在一个依赖下出现两次很常见），
    原样打印会把一行撑成一屏。
    """
    ids: list[str] = []
    if not isinstance(vulns, list):
        return ids
    for vuln in vulns:
        if not isinstance(vuln, dict):
            continue
        identifier = vuln.get("id")
        if identifier and str(identifier) not in ids:
            ids.append(str(identifier))
    return ids


def _deps_gap_hint(detail: str) -> str:
    """按输出内容给出未执行的原因。

    认得出「环境坏了」就给可操作的补救；认不出只列可能原因，不硬猜一个——
    猜错原因比不给原因更坏。
    """
    if any(marker in detail for marker in DEPS_ENV_BROKEN_MARKERS):
        return DEPS_ENV_BROKEN_HINT
    return DEPS_UNPARSABLE_HINT


def _finalize_deps(outcome: CheckOutcome) -> CheckOutcome:
    """pip-audit 的退出码 1 同时表示「有漏洞」与「跑挂了」，必须解析 JSON 区分。

    解析不出 JSON 说明审计根本没跑成，记为 gap：既不算通过，也不写成「失败」。
    """
    payload = _extract_json(outcome.detail)
    deps = payload.get("dependencies") if isinstance(payload, dict) else None
    if not isinstance(deps, list):
        return CheckOutcome(
            check=outcome.check,
            passed=False,
            gap=True,
            detail=f"{outcome.detail or '(无输出)'}\n\n{_deps_gap_hint(outcome.detail)}",
        )
    vulnerable = [item for item in deps if isinstance(item, dict) and item.get("vulns")]
    if not vulnerable:
        return CheckOutcome(
            check=outcome.check,
            passed=True,
            detail=f"审计 {len(deps)} 个依赖，未发现已知漏洞",
        )
    lines = [f"{len(vulnerable)} 个依赖存在已知漏洞："]
    for item in vulnerable:
        ids = "、".join(_unique_vuln_ids(item["vulns"]))
        fixes = "、".join(str(version) for version in item.get("fix_versions") or [])
        suffix = f"（修复版本: {fixes}）" if fixes else ""
        lines.append(f"{item.get('name')} {item.get('version')}: {ids}{suffix}")
    return CheckOutcome(check=outcome.check, passed=False, detail="\n".join(lines))


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


def _report_sections(outcomes: list[CheckOutcome]) -> None:
    """逐条打印失败详情、未校验原因，以及通过时也必须露出的口径信息。"""
    for outcome in outcomes:
        if outcome.gap:
            # 没能真正跑成的校验：单独成段，别混进「失败」被读成代码有问题
            print(f"\n--- 未校验: {outcome.check.label} ---")
            print(outcome.detail or "(无输出)")
        elif not outcome.passed:
            _print_outcome(outcome)
        elif outcome.check.tool in (COMPLEXITY_LABEL, SECURITY_TOOL, DEPS_TOOL):
            # 通过时也打印：让「存量容忍了几处」「扫了多少依赖」可见，否则口径等于隐形
            print(f"\n--- {outcome.check.tool} ---")
            print(outcome.detail or "(无输出)")


def _report_missing(hard: list[str], degraded: list[str]) -> None:
    """打印缺失工具与补装提示。"""
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


def _report_verdict(
    label: str,
    outcomes: list[CheckOutcome],
    degraded: list[str],
    hard: list[str],
    notes: tuple[str, ...],
) -> bool:
    """裁决并打印 verify 行；未真正执行的校验一律不得算通过。"""
    if not outcomes:
        print("verify: 未校验 — 没有任何校验被真实执行，不得视为已通过")
        return False
    failed = [item for item in outcomes if not item.passed and not item.gap]
    if failed:
        print(f"verify: 失败 — {len(failed)} 项校验未通过")
        return False
    if hard:
        print(
            f"verify: 未通过 — 必需工具缺失: {', '.join(hard)}（不可降级），不得视为已通过"
        )
        return False
    gaps = [item for item in outcomes if item.gap]
    if degraded or gaps or notes:
        reasons: list[str] = []
        if degraded:
            reasons.append(f"{', '.join(degraded)} 缺失")
        if gaps:
            reasons.append(
                f"{', '.join(item.check.tool for item in gaps)} 未能真正执行"
            )
        reasons.extend(notes)
        print(
            f"verify: 未完全通过 — {'；'.join(reasons)}，对应校验未真正执行，不得视为已通过"
        )
        return False
    print(f"verify: 全部通过 ({label})")
    return True


def _report(
    label: str,
    outcomes: list[CheckOutcome],
    degraded: list[str],
    hard: list[str],
    notes: tuple[str, ...] = (),
) -> bool:
    """打印汇总，返回本次校验是否全部真实执行且通过。

    notes 放「工具在、但这次没有可审对象」这类原因（如依赖轴找不到 lock 文件）；
    它们不能混进 degraded——那里会被拼成 `uv tool install <名字>` 的安装提示。
    """
    print(f"后置校验 {label}")
    if outcomes:
        marks = " | ".join(
            f"{item.check.tool} {MARK_OK if item.passed else MARK_WARN}"
            for item in outcomes
        )
        print(f"执行: {marks}")
    _report_sections(outcomes)
    _report_missing(hard, degraded)
    return _report_verdict(label, outcomes, degraded, hard, notes)


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
    parser.add_argument(
        "--security",
        action="store_true",
        help="叠加 bandit 源码安全扫描（只扫本次改动的 .py，medium 及以上）",
    )
    parser.add_argument(
        "--deps",
        action="store_true",
        help="叠加 pip-audit 依赖漏洞审计（需 lock 文件或 requirements*.txt，需联网）",
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
    if args.deps:
        # 依赖轴的对象是 lock / requirements，与 .py / .sh 改动无关，不能在这里早退
        print("本次无 .py / .sh 改动，仅执行 --deps 依赖审计")
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
) -> tuple[Path, bool]:
    """打印本次运行的开关状态；返回 (校验工作目录, 是否启用项目自带 ruff 配置)。"""
    if args.project_scope:
        print("类型工具按项目级扫描（--project-scope）：可能连带暴露项目存量类型错误")
    if sh_files and _tool_path("shellcheck") is None:
        print(
            "可选增强: shellcheck 未安装，shell 校验仅 bash -n（不影响判定，可自行安装后重跑）"
        )
    if sh_files and shutil.which(SHELL_TOOL) is None and _tool_path(SHELL_TOOL):
        print(
            f"bash 不在 PATH，已回退到 {_tool_path(SHELL_TOOL)}"
            "（把该目录加进 PATH 可让其他工具也用上）"
        )
    config_root = _config_root_for(cwd, py_files)
    if config_root is not None:
        print(
            "检测到项目自带 ruff 配置（pyproject.toml / ruff.toml），不使用脚本兜底参数"
        )
    tool_root = config_root or cwd
    if tool_root != cwd:
        print(
            f"校验工作目录改为配置所在目录 {tool_root}"
            "（ruff 的 per-file-ignores 按相对工作目录的路径匹配）"
        )
    return tool_root, config_root is not None


def _finalize_outcome(outcome: CheckOutcome, cwd: Path) -> CheckOutcome:
    """按工具分派二次裁决。

    这三条都不看退出码，改由解析输出后自行判定：复杂度要分新代码与存量两档，
    bandit 命中即非零，pip-audit 的非零同时表示「有漏洞」与「跑挂了」。
    """
    if outcome.check.tool == COMPLEXITY_LABEL:
        return _finalize_complexity(outcome, cwd)
    if outcome.check.tool == SECURITY_TOOL:
        return _finalize_security(outcome)
    if outcome.check.tool == DEPS_TOOL:
        return _finalize_deps(outcome)
    return outcome


def _execute_checks(
    args: argparse.Namespace,
    py_files: list[str],
    sh_files: list[str],
    exe: dict[str, str | None],
    cwd: Path,
    respect_ruff_config: bool,
    deps_target: tuple[str, ...] | None = None,
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
            deps_target,
        )
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            outcomes = list(pool.map(partial(_execute, cwd=cwd), checks))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    return [_finalize_outcome(item, cwd) for item in outcomes]


def _axis_label(level: str, has_files: bool, security: bool, deps: bool) -> str:
    """报告头里的级别标注：L 级 + 本次开启的正交轴，让轴是否生效可见。

    没有 .py / .sh 改动时 L 级其实什么都没跑（例如只改了 lock 文件），
    此时不写 L 级，避免被读成「L 级通过了」。
    """
    parts = [level] if has_files else []
    if security:
        parts.append("S")
    if deps:
        parts.append("D")
    return " + ".join(parts) if parts else level


def _prepare_axes(
    args: argparse.Namespace, py_files: list[str], tool_root: Path
) -> tuple[tuple[str, ...] | None, list[str]]:
    """准备两个正交轴：解析依赖来源、判断安全轴有没有可扫对象。

    返回 (pip-audit 目标参数, 未真正执行的原因清单)；后者交给 `_report` 折进结论。
    """
    deps_target: tuple[str, ...] | None = None
    notes: list[str] = []
    if args.deps:
        deps_target = _resolve_deps_source(tool_root)
        if deps_target is None:
            print(
                "依赖轴未校验：未找到 "
                + " / ".join((*DEPS_LOCK_NAMES, "requirements*.txt"))
                + "，无法确定审计对象"
            )
            print(
                "  （裸跑 pip-audit 审计的是它自己的隔离环境，"
                "会给出「没发现漏洞」的假绿）"
            )
            notes.append("依赖轴无审计对象（未找到 lock 文件或 requirements*.txt）")
    if args.security and not py_files:
        print("安全轴未校验：本次没有 .py 改动，bandit 无对象可扫")
        notes.append("安全轴无对象（本次没有 .py 改动）")
    return deps_target, notes


def main(argv: list[str] | None = None) -> int:
    """入口。"""
    args = _parse_args(argv)
    _force_utf8_stdout()
    cwd = Path.cwd()

    if args.probe:
        _print_probe(_probe(PROBE_TOOLS))
        return 0

    if args.files:
        absent = [name for name in args.files if not (cwd / name).exists()]
        if absent:
            print(f"--files 找不到文件: {', '.join(absent)}")
            print(f"--files 相对当前工作目录解析（{cwd}），也可直接传绝对路径")
            print("verify: 未校验 — 不得视为已通过")
            return 1

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

    tool_root, respect_ruff_config = _print_mode_notes(args, py_files, sh_files, cwd)
    py_files = _relativize(py_files, tool_root)
    sh_files = _relativize(sh_files, tool_root)

    deps_target, notes = _prepare_axes(args, py_files, tool_root)

    needed = _needed_tools(
        args.level, bool(py_files), bool(sh_files), args.security, args.deps
    )
    exe = _resolve_missing(needed, cwd, args.install_missing)
    missing = [tool for tool in needed if exe[tool] is None]
    hard = [tool for tool in missing if tool in REQUIRED_TOOLS]
    degraded = [tool for tool in missing if tool in DEGRADABLE_TOOLS]
    outcomes = _execute_checks(
        args, py_files, sh_files, exe, tool_root, respect_ruff_config, deps_target
    )
    label = _axis_label(
        args.level, bool(py_files or sh_files), args.security, args.deps
    )
    return 0 if _report(label, outcomes, degraded, hard, tuple(notes)) else 1


if __name__ == "__main__":
    sys.exit(main())
