#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import os
from pathlib import Path
from typing import List, Optional, Set, Tuple


DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".ipynb_checkpoints",
    "node_modules",
    "venv", ".venv", "env",
    "dist", "build", "target", "out",
    ".idea", ".vscode",
}

DEFAULT_IGNORE_FILES = {
    ".DS_Store",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock",
    "prompt_context.md",
    "generate_prompt_context.py",  # s'exclure soi-même
}

DEFAULT_EXCLUDE_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".pdf",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".mp3", ".wav", ".mp4", ".mov", ".avi", ".mkv",
    ".parquet", ".feather", ".arrow", ".orc",
    ".npz", ".npy",
    ".pt", ".pth", ".onnx",
    ".pkl", ".pickle",
    ".db", ".sqlite", ".sqlite3",
    ".exe", ".dll", ".so", ".dylib",
}

LANG_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".swift": "swift",
    ".sh": "bash",
    ".zsh": "zsh",
    ".ps1": "powershell",
    ".sql": "sql",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".md": "markdown",
    ".tex": "tex",
}


def parse_csv_set(value: Optional[str]) -> Set[str]:
    if not value:
        return set()
    return {v.strip() for v in value.split(",") if v.strip()}


def to_ext_set(value: Optional[str]) -> Set[str]:
    raw = parse_csv_set(value)
    return {x if x.startswith(".") else f".{x}" for x in raw}


def is_probably_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    if not data:
        return False
    sample = data[:4096]
    text_chars = set(range(32, 127)) | {9, 10, 13}
    non_text = sum(1 for b in sample if b not in text_chars)
    return (non_text / len(sample)) > 0.30


def matches_any_glob(rel_posix: str, patterns: Set[str], is_dir: bool) -> bool:
    if not patterns:
        return False
    # Pour les dirs, on teste aussi rel_posix + "/" pour mieux matcher "data/**"
    candidates = [rel_posix]
    if is_dir and not rel_posix.endswith("/"):
        candidates.append(rel_posix + "/")
    return any(fnmatch.fnmatch(c, pat) for c in candidates for pat in patterns)


def fence_lang(path: Path) -> str:
    ext = path.suffix.lower()
    if path.name.lower() == "dockerfile":
        return "dockerfile"
    return LANG_MAP.get(ext, "text")


def read_text_file(path: Path, max_bytes: int) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = path.read_bytes()
    except Exception:
        return None, None

    if is_probably_binary(data):
        return None, None

    note = None
    if max_bytes and len(data) > max_bytes:
        data = data[:max_bytes]
        note = f"TRUNCATED to first {max_bytes} bytes (use --max-bytes 0 for full content)"

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        note = (note + " | " if note else "") + "invalid utf-8 replaced"

    return text, note


def collect_files(
    root: Path,
    include_exts: Set[str],
    ignore_dirs: Set[str],
    ignore_files: Set[str],
    exclude_exts: Set[str],
    exclude_globs: Set[str],
) -> List[Path]:
    files: List[Path] = []

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirpath_p = Path(dirpath)

        # prune dirs
        kept_dirnames = []
        for d in dirnames:
            if d in ignore_dirs:
                continue
            rel_dir = (dirpath_p / d).relative_to(root).as_posix()
            if matches_any_glob(rel_dir, exclude_globs, is_dir=True):
                continue
            kept_dirnames.append(d)
        dirnames[:] = kept_dirnames

        # files
        for fn in filenames:
            if fn in ignore_files:
                continue
            p = dirpath_p / fn
            if p.is_symlink():
                continue

            rel = p.relative_to(root).as_posix()
            if matches_any_glob(rel, exclude_globs, is_dir=False):
                continue

            ext = p.suffix.lower()
            if ext in exclude_exts:
                continue
            if include_exts and ext not in include_exts:
                continue

            files.append(p)

    files.sort(key=lambda x: x.relative_to(root).as_posix().lower())
    return files


def build_tree_lines(root: Path, files: List[Path]) -> List[str]:
    nodes = set()
    for f in files:
        rel = f.relative_to(root)
        parts = rel.parts
        for i in range(1, len(parts) + 1):
            nodes.add(Path(*parts[:i]))

    def children(of: Path) -> List[Path]:
        pref = of.parts
        out = []
        for n in nodes:
            if len(n.parts) == len(pref) + 1 and n.parts[:len(pref)] == pref:
                out.append(n)
        out.sort(key=lambda p: (0 if (root / p).is_dir() else 1, p.name.lower()))
        return out

    lines: List[str] = ["."]
    def walk(prefix: str, parent: Path):
        kids = children(parent)
        for idx, k in enumerate(kids):
            is_last = idx == len(kids) - 1
            connector = "└── " if is_last else "├── "
            full = root / k
            suffix = "/" if full.is_dir() else ""
            lines.append(f"{prefix}{connector}{k.name}{suffix}")
            if full.is_dir():
                extension = "    " if is_last else "│   "
                walk(prefix + extension, k)

    walk("", Path())
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate a Markdown prompt with project tree + file contents."
    )
    ap.add_argument("--root", default=".", help="Project root directory (default: .)")
    ap.add_argument("--out", default="prompt_context.md", help="Output markdown file name")
    ap.add_argument("--include-ext", default="", help="Comma-separated extensions to include (e.g. py,md,sql). Empty = all text-ish.")
    ap.add_argument("--exclude-ext", default="", help="Comma-separated extensions to exclude (adds to defaults).")
    ap.add_argument("--exclude-glob", default="", help="Comma-separated glob patterns on relative paths (e.g. 'data/**,**/*.csv').")
    ap.add_argument("--max-bytes", type=int, default=0, help="Max bytes per file (0 = no limit).")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out_path = (root / args.out).resolve()

    include_exts = to_ext_set(args.include_ext)
    exclude_exts = DEFAULT_EXCLUDE_EXTS | to_ext_set(args.exclude_ext)
    exclude_globs = parse_csv_set(args.exclude_glob)

    files = collect_files(
        root=root,
        include_exts=include_exts,
        ignore_dirs=DEFAULT_IGNORE_DIRS,
        ignore_files=DEFAULT_IGNORE_FILES,
        exclude_exts=exclude_exts,
        exclude_globs=exclude_globs,
    )

    tree_lines = build_tree_lines(root, files)

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md: List[str] = []
    md.append("# Project Context\n\n")
    md.append(f"_Generated: {now}_\n\n")
    md.append(f"_Root: `{root}`_\n\n")
    md.append("---\n\n")

    md.append("## 1) Project Tree (included files)\n\n```text\n")
    md.append("\n".join(tree_lines))
    md.append("\n```\n\n---\n\n")

    md.append("## 2) File Contents\n\n")
    for fp in files:
        rel = fp.relative_to(root).as_posix()
        content, note = read_text_file(fp, max_bytes=args.max_bytes)
        if content is None:
            continue  # skip silencieusement

        lang = fence_lang(fp)
        md.append(f"### FILE: `{rel}`\n")
        if note:
            md.append(f"> NOTE: {note}\n")
        md.append(f"\n```{lang}\n{content}\n```\n\n---\n\n")

    out_path.write_text("".join(md), encoding="utf-8")
    print(f"✅ Wrote: {out_path} ({len(files)} files included)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
