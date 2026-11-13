#!/usr/bin/env python3
"""维护内容收录总索引（Markdown 表格，默认 $CC_OUTPUT_ROOT/索引.md）。

表格固定 5 列：标题 | 来源（平台） | 标签 | 摘要 | 文档链接
- 来源（平台）写成 [平台](<原链接>)，原链接就是这一行的主键；没有原链接时只写平台名。
- 文档链接是相对索引文件所在目录的 Markdown 链接，指向正文 .md（日期-平台-标题.md）。
- 同一个原链接、或同一个正文文档，只会更新已有的那一行，不会重复。
- 写入先写临时文件再 os.replace，过程中用文件锁防并发。

用法:
  cc_index.py add --doc 正文.md [--title T] [--platform P] [--tags "a,b"] [--summary S]
                  [--url 原链接] [--index 索引.md]
  cc_index.py reserve --url 原链接 --platform P --title T --doc-dir 目录 [--index 索引.md]
      （collect 成功后调用：按原链接预留一行，标签、摘要留空；已有的行不覆盖已填内容。
        stdout 输出正文文档应写到的绝对路径）
  cc_index.py path [--index 索引.md]      输出索引文件的绝对路径
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fcntl
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, unquote

COLUMNS = ["标题", "来源（平台）", "标签", "摘要", "文档链接"]
HEADER = "| " + " | ".join(COLUMNS) + " |"
SEP = "|" + "|".join(["---"] * len(COLUMNS)) + "|"
INTRO = (
    "# 内容收录索引\n\n"
    "> 由 `content-capture index add` 维护：同一原链接或同一文档只占一行。"
    "请用命令更新，不要手改表格。\n"
)

PLATFORM_NAMES = {
    "douyin": "抖音",
    "xhs": "小红书",
    "x": "X",
    "twitter": "X",
    "youtube": "YouTube",
    "wechat": "公众号",
}


def platform_name(p: str) -> str:
    p = (p or "").strip()
    return PLATFORM_NAMES.get(p.lower(), p)


# ---------- 转义 ----------

def esc_cell(s: str) -> str:
    """表格单元格：反斜杠、竖线转义，换行变 <br>。"""
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    s = s.replace("\\", "\\\\").replace("|", "\\|")
    s = re.sub(r"\n+", "<br>", s)
    return s


def unesc_cell(s: str) -> str:
    s = s.strip()
    s = re.sub(r"<br\s*/?>", "\n", s)
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in "\\|":
            out.append(s[i + 1])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def split_row(line: str) -> list[str]:
    """按未转义的 | 切分一行表格。"""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i : i + 2])
            i += 2
            continue
        if c == "|":
            cells.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    cells.append("".join(cur))
    return [c.strip() for c in cells]


def norm_tags(raw: str) -> str:
    parts = [t.strip().lstrip("#") for t in re.split(r"[,，、;；\n]+", raw or "")]
    seen: list[str] = []
    for t in parts:
        if t and t not in seen:
            seen.append(t)
    return "、".join(seen)


# 链接目标放在 <> 里（允许空格、中文）；只把会破坏链接或表格的字符百分号编码
_LINK_UNSAFE = set("%<>|#?\\")


def link_target(rel: str) -> str:
    out = []
    for ch in rel:
        if ch in _LINK_UNSAFE or ord(ch) < 0x20 or ch == "\x7f":
            out.append(quote(ch, safe=""))
        else:
            out.append(ch)
    return "<" + "".join(out) + ">"


def url_target(url: str) -> str:
    return "<" + url.replace("<", "%3C").replace(">", "%3E").replace("|", "%7C").replace(" ", "%20") + ">"


_LINK_RE = re.compile(r"\[(?:[^\]\\]|\\.)*\]\((<[^>]*>|[^)\s]*)\)")


def parse_link(cell: str) -> str:
    m = _LINK_RE.search(cell)
    if not m:
        return ""
    t = m.group(1)
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1]
    return unquote(t)


def link_label(text: str) -> str:
    return esc_cell(text).replace("[", "\\[").replace("]", "\\]")


# ---------- 文件名 ----------

def safe_title(title: str, limit: int = 50) -> str:
    t = re.sub(r"[\\/:*?\"<>|#%\x00-\x1f\x7f]+", " ", title or "")
    t = re.sub(r"\s+", " ", t).strip(" .")
    return t[:limit].rstrip(" .") or "未命名"


def short_title(title: str, limit: int = 60) -> str:
    """collect 预留行用：抖音等平台的「标题」常是整段文案，取第一句、去掉话题标签。"""
    t = (title or "").strip().split("\n", 1)[0]
    t = re.split(r"#[^\s#]", t, maxsplit=1)[0].strip() or t
    t = re.sub(r"\s+", " ", t)
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def doc_filename(date: str, platform: str, title: str) -> str:
    return f"{date}-{safe_title(platform_name(platform), 20)}-{safe_title(title)}.md"


# ---------- 读写 ----------

class Row:
    def __init__(self, title="", platform="", url="", tags="", summary="", doc=""):
        self.title, self.platform, self.url = title, platform, url
        self.tags, self.summary, self.doc = tags, summary, doc  # doc 为绝对路径

    def render(self, index_dir: Path) -> str:
        src = esc_cell(self.platform)
        if self.url:
            src = f"[{link_label(self.platform) or '原链接'}]({url_target(self.url)})"
        if self.doc:
            rel = os.path.relpath(self.doc, index_dir)
            rel = rel.replace(os.sep, "/")
            doc = f"[{link_label(Path(self.doc).name)}]({link_target(rel)})"
        else:
            doc = ""
        cells = [esc_cell(self.title), src, esc_cell(self.tags), esc_cell(self.summary), doc]
        return "| " + " | ".join(cells) + " |"


def parse_index(text: str, index_dir: Path) -> tuple[list[str], list[Row], list[str]]:
    """返回 (表格前的行, 表格行, 表格后的行)。没有表格时 rows 为空。"""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if [c for c in split_row(line)] == COLUMNS:
            start = i
            break
    if start is None:
        return lines, [], []
    before = lines[:start]
    rows: list[Row] = []
    j = start + 2  # 跳过表头和分隔行
    while j < len(lines) and lines[j].strip().startswith("|"):
        cells = split_row(lines[j])
        cells += [""] * (len(COLUMNS) - len(cells))
        title, src, tags, summary, doc = cells[:5]
        m = _LINK_RE.search(src)
        if m:
            plat = unesc_cell(re.sub(r"\\([\[\]])", r"\1", src[1 : src.index("](")]))
            url = parse_link(src)
        else:
            plat, url = unesc_cell(src), ""
        doc_rel = parse_link(doc)
        doc_abs = str((index_dir / doc_rel).resolve()) if doc_rel else ""
        rows.append(Row(unesc_cell(title), plat, url, unesc_cell(tags), unesc_cell(summary), doc_abs))
        j += 1
    return before, rows, lines[j:]


def render_index(before: list[str], rows: list[Row], after: list[str], index_dir: Path) -> str:
    head = "\n".join(before).rstrip() if any(l.strip() for l in before) else INTRO.rstrip()
    body = [HEADER, SEP] + [r.render(index_dir) for r in rows]
    tail = "\n".join(after).strip()
    return head + "\n\n" + "\n".join(body) + "\n" + ("\n" + tail + "\n" if tail else "")


@contextmanager
def locked(index: Path):
    index.parent.mkdir(parents=True, exist_ok=True)
    lock = index.parent / f".{index.name}.lock"
    with open(lock, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def norm_url(u: str) -> str:
    return (u or "").strip()


def find_row(rows: list[Row], url: str, doc: str) -> Row | None:
    if url:
        for r in rows:
            if r.url and r.url == url:
                return r
    if doc:
        for r in rows:
            if r.doc and r.doc == doc:
                return r
    return None


def upsert(index: Path, **kw) -> tuple[Row, bool]:
    with locked(index):
        return _upsert(index, **kw)


def _upsert(index: Path, *, url: str, doc: str, title, platform, tags, summary, reserve: bool = False) -> tuple[Row, bool]:
    """title/platform/tags/summary 为 None 表示不改。reserve=True 时只填空着的字段。调用方负责加锁。"""
    index_dir = index.parent.resolve()
    text = index.read_text(encoding="utf-8") if index.exists() else ""
    before, rows, after = parse_index(text, index_dir)
    row = find_row(rows, url, doc)
    created = row is None
    if created:
        row = Row()
        rows.append(row)
    # 同一文档又被另一个原链接占着时，不合并两行
    if doc and not created and row.url and url and row.url != url:
        raise ValueError(f"文档 {doc} 已属于另一个原链接 {row.url}，请换一个文档路径")

    def setf(name, val):
        if val is None:
            return
        if reserve and getattr(row, name):
            return
        setattr(row, name, val)

    setf("url", url or None)
    setf("doc", doc or None)
    setf("title", title)
    setf("platform", platform_name(platform) if platform is not None else None)
    setf("tags", norm_tags(tags) if tags is not None else None)
    setf("summary", summary)
    # 同一文档被另一行占着（例如先只按文档加过、后来才带上原链接）：合并掉重复行
    if row.doc:
        for other in [r for r in rows if r is not row and r.doc == row.doc]:
            if other.url and row.url and other.url != row.url:
                raise ValueError(f"文档 {row.doc} 已属于另一个原链接 {other.url}，请换一个文档路径")
            for name in ("title", "platform", "tags", "summary"):
                if not getattr(row, name) and getattr(other, name):
                    setattr(row, name, getattr(other, name))
            rows.remove(other)
    atomic_write(index, render_index(before, rows, after, index_dir))
    return row, created


def planned_doc(index: Path, doc_dir: Path, platform: str, title: str, url: str) -> str:
    """为 reserve 选一个正文路径：同一原链接已有行就沿用；文件名撞了别的链接就加 -2、-3。"""
    index_dir = index.parent.resolve()
    rows: list[Row] = []
    if index.exists():
        _, rows, _ = parse_index(index.read_text(encoding="utf-8"), index_dir)
    for r in rows:
        if url and r.url == url and r.doc:
            return r.doc
    taken = {r.doc for r in rows if r.doc}
    date = _dt.date.today().isoformat()
    name = doc_filename(date, platform, title)
    cand = (doc_dir / name).resolve()
    n = 2
    while str(cand) in taken:
        cand = (doc_dir / (name[:-3] + f"-{n}.md")).resolve()
        n += 1
    return str(cand)


def default_index() -> Path:
    env = os.environ.get("CC_INDEX_FILE")
    if env:
        return Path(env).expanduser()
    root = os.environ.get("CC_OUTPUT_ROOT") or os.path.join(os.getcwd(), "content-capture-out")
    return Path(root).expanduser() / "索引.md"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="content-capture index", description="维护内容收录总索引（索引.md）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="新增或更新一行（同一原链接 / 同一文档只更新）")
    a.add_argument("--doc", required=True, help="正文 Markdown 路径（日期-平台-标题.md），必须已存在")
    a.add_argument("--title")
    a.add_argument("--platform", help="douyin|xhs|x|youtube|wechat 或中文平台名")
    a.add_argument("--tags", help="逗号、顿号或分号分隔")
    a.add_argument("--summary")
    a.add_argument("--url", help="原始链接（主键）")
    a.add_argument("--index", help="索引文件，默认 $CC_INDEX_FILE 或 $CC_OUTPUT_ROOT/索引.md")

    r = sub.add_parser("reserve", help="collect 用：按原链接预留一行")
    r.add_argument("--url", required=True)
    r.add_argument("--platform", required=True)
    r.add_argument("--title", default="")
    r.add_argument("--doc-dir", help="正文目录，默认与索引同目录")
    r.add_argument("--index")

    p = sub.add_parser("path", help="输出索引文件路径")
    p.add_argument("--index")

    args = ap.parse_args(argv)
    index = (Path(args.index).expanduser() if getattr(args, "index", None) else default_index()).resolve()

    if args.cmd == "path":
        print(index)
        return 0

    if args.cmd == "reserve":
        doc_dir = Path(args.doc_dir).expanduser().resolve() if args.doc_dir else index.parent
        url = norm_url(args.url)
        args.title = short_title(args.title)
        with locked(index):
            doc = planned_doc(index, doc_dir, args.platform, args.title, url)
            _upsert(index, url=url, doc=doc, title=args.title or None, platform=args.platform,
                    tags="", summary="", reserve=True)
        print(doc)
        return 0

    # add
    doc_p = Path(args.doc).expanduser().resolve()
    if not doc_p.is_file():
        print(f"找不到正文文档: {doc_p}（先写好正文 Markdown 再登记索引）", file=sys.stderr)
        return 1
    if doc_p.suffix.lower() != ".md":
        print(f"正文文档必须是 .md: {doc_p}", file=sys.stderr)
        return 1
    try:
        row, created = upsert(
            index, url=norm_url(args.url or ""), doc=str(doc_p),
            title=args.title, platform=args.platform, tags=args.tags, summary=args.summary,
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not row.title:
        row.title = doc_p.stem
        upsert(index, url=row.url, doc=row.doc, title=row.title, platform=None, tags=None, summary=None)
    print(f"{'新增' if created else '更新'}: {index}", file=sys.stderr)
    print(index)
    return 0


if __name__ == "__main__":
    sys.exit(main())
