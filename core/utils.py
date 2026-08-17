from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def get_at_ids(raw_args: str) -> list[str]:
    """从命令参数中提取被 @ 的纯数字 QQ 号"""
    ats: list[str] = []
    for token in raw_args.split():
        if token.startswith("@") and token[1:].isdigit():
            ats.append(token[1:])
        elif token.isdigit() and len(token) >= 5:
            pass
    return ats


def parse_range(raw_args: str) -> tuple[int, int]:
    """解析范围参数，返回 (offset, limit)

    n     -> 第 n 条
    s~e   -> 第 s 到 e 条
    其它  -> 第 1 条
    """
    parts = raw_args.strip().split()
    if not parts:
        return 0, 1

    end = parts[-1]
    if "~" in end:
        try:
            s, e = end.split("~", 1)
            s_i = int(s)
            e_i = int(e)
            if s_i <= 0 or e_i < s_i:
                raise ValueError
            return s_i - 1, e_i - s_i + 1
        except ValueError:
            return 0, 1

    try:
        n = int(end)
        if n <= 0:
            raise ValueError
        return n - 1, 1
    except ValueError:
        return 0, 1


def extract_image_urls(raw_args: str) -> list[str]:
    """从命令参数中提取图片 URL"""
    return [m.group(0) for m in _URL_RE.finditer(raw_args)]