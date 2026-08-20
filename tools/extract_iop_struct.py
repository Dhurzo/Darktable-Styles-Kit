#!/usr/bin/env python3
"""Extract an IOPRegistry draft from a darktable C source file.

Parses ``src/iop/<name>.c`` and prints a ready-to-paste Python block for
``dtstylekit/codec/iop_registry.py``: the struct fields with their
``$MIN/$MAX/$DEFAULT`` annotations, the ``DT_MODULE_INTROSPECTION``
version, a computed ``pack_format`` (enums/gboolean -> ``i``, floats ->
``f``, arrays -> repetition) and ``size_bytes`` via ``struct.calcsize``.

Usage:
    python tools/extract_iop_struct.py src/iop/colorharmonizer.c [--blendop 2|3|4]

Output is best-effort: array dimensions, nested structs and enum members
still need human review against the C source before the block is trusted.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

# field type -> (struct char, kind)
_FIELD_TYPES = {
    "float": ("f", "float"),
    "double": ("d", "float"),
    "gboolean": ("i", "int"),
    "int": ("i", "int"),
    "uint32_t": ("i", "int"),
    "size_t": ("i", "int"),
}

_ANNOT_RE = re.compile(r"\$(\w+):\s*([-\d.]+)")
_INTROSPECTION_RE = re.compile(r"DT_MODULE_INTROSPECTION\s*\(\s*(\d+)\s*,")


def _strip_block_comments(text: str) -> str:
    """Remove /* */ comments (keeps // comments: they carry $ annotations)."""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _find_struct(text: str, iop_name: str) -> str | None:
    """Return the dt_iop_<name>_params_t struct body (first match)."""
    pat = re.compile(
        rf"struct\s+dt_iop_{iop_name}_params_t\s*\{{(.*?)\}}",
        re.DOTALL,
    )
    m = pat.search(text)
    return m.group(1) if m else None


def _annotations(field: str) -> dict[str, float]:
    anns: dict[str, float] = {}
    for kind, val in _ANNOT_RE.findall(field):
        try:
            anns[kind] = float(val)
        except ValueError:
            pass
    return anns


def _parse_fields(body: str) -> list[dict]:
    """Parse individual C field declarations from a struct body.

    Annotations (``$MIN: x $MAX: y $DEFAULT: z``) live in trailing
    ``//`` comments on the SAME line as the declaration, so each line
    is processed whole: annotations first, then the comment is
    stripped, then the declaration is matched.
    """
    fields: list[dict] = []
    for line in body.split("\n"):
        anns = _annotations(line)
        decl = re.sub(r"//.*", "", line).strip().rstrip(";")
        if not decl:
            continue
        if "struct" in decl and "params_t" not in decl:
            continue
        m = re.match(
            r"(float|double|gboolean|int|uint32_t|size_t|dt_iop_\w+_t)\s+"
            r"([A-Za-z_]\w*)\s*(\[[^\]]*\])?",
            decl,
        )
        if not m:
            continue
        ctype, name, arr = m.groups()
        arr_dim = None
        if arr:
            inner = arr.strip("[]")
            if inner.isdigit():
                arr_dim = int(inner)
        fields.append(
            {
                "ctype": ctype,
                "name": name,
                "array": arr_dim,
                "anns": anns,
            }
        )
    return fields


def extract(c_path: Path) -> dict | None:
    """Extract (version, fields, pack_format, size_bytes, blendop guess)."""
    text = _strip_block_comments(c_path.read_text(encoding="utf-8"))
    iop_name = c_path.stem

    m = _INTROSPECTION_RE.search(text)
    version = int(m.group(1)) if m else None

    body = _find_struct(text, iop_name)
    if body is None:
        return None
    fields = _parse_fields(body)
    if not fields:
        return None

    fmt = "<"
    for f in fields:
        if f["ctype"] in _FIELD_TYPES:
            fmt += _FIELD_TYPES[f["ctype"]][0] * (f["array"] or 1)
        else:
            # enum / unknown typedef → int (4 bytes), warn
            fmt += "i" * (f["array"] or 1)

    try:
        size = struct.calcsize(fmt)
    except struct.error:
        size = None

    return {
        "name": iop_name,
        "version": version,
        "fields": fields,
        "pack_format": fmt,
        "size_bytes": size,
    }


def render_block(info: dict, blendop: int | None = None) -> str:
    """Render the Python IOPRegistry block."""
    name = info["name"]
    lines = [
        f'    "{name}": IOPRegistry(',
        f'        operation="{name}",',
        f"        version={info['version']},",
        f"        # {len(info['fields'])} fields, {info['size_bytes']} bytes",
        f'        pack_format="{info["pack_format"]}",',
        "        fields=(",
    ]
    for f in info["fields"]:
        fname = f["name"]
        if f["array"]:
            fname = f"{fname}_{{0..{f['array'] - 1}}}"
        lines.append(f'            "{fname}",')
    lines.append("        ),")
    lines.append("        defaults={")
    for f in info["fields"]:
        d = f["anns"].get("DEFAULT")
        if d is None:
            continue
        fname = f["name"]
        if f["array"]:
            lines.append(f"            # {fname}[{f['array']}]: default {d}")
            continue
        val = repr(int(d)) if f["ctype"] != "float" else repr(d)
        lines.append(f'            "{fname}": {val},')
    lines.append("        },")
    lines.append("        ranges={")
    for f in info["fields"]:
        lo = f["anns"].get("MIN")
        hi = f["anns"].get("MAX")
        if lo is None or hi is None:
            continue
        fname = f["name"]
        if f["array"]:
            lines.append(f"            # {fname}[{f['array']}]: [{lo}, {hi}]")
            continue
        lines.append(f'            "{fname}": ({lo}, {hi}),')
    lines.append("        },")
    lines.append(f"        size_bytes={info['size_bytes']},")
    if blendop is not None:
        lines.append(f"        blendop_cst={blendop},  # manual: 2=LAB 3=RGB_DISPLAY 4=RGB_SCENE")
    lines.append("    ),")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("c_file", type=Path, help="Path to src/iop/<name>.c")
    parser.add_argument(
        "--blendop",
        type=int,
        choices=(2, 3, 4),
        default=None,
        help="blendop_cst (2=LAB, 3=RGB_DISPLAY, 4=RGB_SCENE) — from get_colorspace",
    )
    args = parser.parse_args(argv)

    if not args.c_file.exists():
        print(f"ERROR: {args.c_file} not found", file=sys.stderr)
        return 1

    info = extract(args.c_file)
    if info is None:
        print(
            f"ERROR: could not find struct dt_iop_{args.c_file.stem}_params_t",
            file=sys.stderr,
        )
        return 1

    print(f"# {args.c_file} — DT_MODULE_INTROSPECTION({info['version']})")
    print(f"# pack_format={info['pack_format']} size={info['size_bytes']}B")
    for f in info["fields"]:
        ann = ", ".join(f"{k}={v}" for k, v in f["anns"].items()) or "no annotations"
        dim = f"[{f['array']}]" if f["array"] else ""
        print(f"#   {f['ctype']} {f['name']}{dim}  ({ann})")
    print()
    print("IOP_REGISTRY.update({")
    print(render_block(info, args.blendop))
    print("})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
