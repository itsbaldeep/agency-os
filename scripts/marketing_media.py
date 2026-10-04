"""Deterministic, draft-only marketing media artifacts.

This module has no provider or engagement dependency.  Raster assets are made
locally with Pillow.  Video work produces a reviewable HyperFrames composition
and invokes only a pinned local runtime when configured and available.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = ImageDraw = ImageFont = None

ARTIFACT_ROOT = Path("/home/agency/.local/share/agency-marketing/brands")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "media-runtime.json"
FFPROBE = Path("/home/agency/tools/marketing-media/node_modules/@ffprobe-installer/linux-x64/ffprobe")
FFMPEG = Path("/home/agency/.local/lib/python3.14/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2")
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
__all__ = ["create_media_artifacts", "ARTIFACT_ROOT"]
NAVY = (15, 38, 64)
CYAN = (43, 168, 190)


def _slug(value: Any) -> str:
    result = SAFE_NAME.sub("-", str(value or "draft")).strip("-.")
    return result[:80] or "draft"


def _root(item: dict[str, Any]) -> Path:
    brand_id = item.get("brand_id")
    if isinstance(brand_id, bool) or not isinstance(brand_id, int) or brand_id <= 0:
        raise ValueError("brand_id must be a positive integer")
    item_id = item.get("id", "draft")
    revision = item.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision must be a positive integer")
    root = ARTIFACT_ROOT / str(brand_id) / "work" / _slug(item_id) / f"revision-{revision}"
    _assert_no_symlink_ancestors(root, ARTIFACT_ROOT)
    try:
        root.resolve(strict=False).relative_to(ARTIFACT_ROOT.resolve(strict=False))
    except ValueError as exc:
        raise ValueError("artifact path escaped the brand root") from exc
    root.mkdir(parents=True, exist_ok=True)
    return root


def _font_source() -> Path | None:
    path = Path(__file__).resolve().parents[1] / "vendor" / "marketing-media" / "KaTeX_SansSerif-Regular.ttf"
    return path if path.is_file() else None


def _font(size: int):
    if ImageFont is None:
        return None
    source = _font_source()
    if source:
        return ImageFont.truetype(source, size)
    return ImageFont.load_default()


def _wrap(text: str, font: Any, max_width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _label(draw: Any, xy: tuple[int, int], text: str, size: int, fill: str, max_width: int) -> None:
    font = _font(size)
    for index, line in enumerate(_wrap(text, font, max_width)):
        draw.text((xy[0], xy[1] + index * (size + 10)), line, font=font, fill=fill)


def _write_png(path: Path, size: tuple[int, int], title: str, subtitle: str, accent: tuple[int, int, int], *, avatar: bool = False) -> dict[str, Any]:
    image = Image.new("RGB", size, NAVY)
    draw = ImageDraw.Draw(image)
    if avatar:
        inset = size[0] // 5
        draw.ellipse((inset, inset, size[0] - inset, size[1] - inset), fill=accent)
        initials = "".join(part[0] for part in str(title).split() if part)[:2].upper()
        bbox = draw.textbbox((0, 0), initials, font=_font(size[0] // 4))
        draw.text(((size[0] - (bbox[2] - bbox[0])) // 2, (size[1] - (bbox[3] - bbox[1])) // 2 - bbox[1]), initials, font=_font(size[0] // 4), fill="#F5F7FA")
    else:
        draw.rectangle((0, size[1] - max(12, size[1] // 80), size[0], size[1]), fill=accent)
        _label(draw, (size[0] // 12, size[1] // 5), title, max(28, size[1] // 10), "#F5F7FA", int(size[0] * .76))
        _label(draw, (size[0] // 12, size[1] // 2), subtitle, max(16, size[1] // 22), "#AAB7C7", int(size[0] * .76))
    image.save(path, format="PNG", optimize=True)
    return {"path": str(path), "mime": "image/png", "width": size[0], "height": size[1], "provenance": "generated editorial graphic from supplied brand text"}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _assert_no_symlink_ancestors(path: Path, stop: Path) -> None:
    current = path
    stop = stop.absolute()
    while True:
        if current.exists() and current.is_symlink():
            raise ValueError("artifact path cannot contain symlinks")
        if current == stop or current.parent == current:
            return
        current = current.parent


def _ui_asset(item: dict[str, Any], root: Path) -> Path | None:
    candidate = item.get("brief", {}).get("project_ui_asset")
    if not candidate:
        return None
    path = Path(str(candidate)).expanduser()
    brand_root = ARTIFACT_ROOT / str(item.get("brand_id"))
    if not path.is_absolute() or not _inside(path, brand_root):
        raise ValueError("project UI asset must be inside this brand's artifact root")
    _assert_no_symlink_ancestors(path, brand_root)
    if not path.is_file():
        raise ValueError("project UI asset does not exist")
    return path


def _runtime_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        config = json.loads(CONFIG_PATH.read_text())
        return config if isinstance(config, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _runtime() -> tuple[str, list[str], str] | None:
    try:
        config = _runtime_config()
        executable = config["executable"]
        args = config.get("args", [])
        if not isinstance(executable, str) or not os.path.isabs(executable) or not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            return None
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            return None
        return executable, args, str(config.get("version", "pinned"))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _composition(root: Path, brand_name: str, item: dict[str, Any], ui_asset: Path | None, facts: list[str], scene_images: list[Path]) -> Path:
    title = html.escape(str(item.get("title", "Launch")), quote=True)
    name = html.escape(brand_name, quote=True)
    image = ""
    if ui_asset:
        target = root / "assets" / "project-ui" / f"{_slug(ui_asset.stem)}{ui_asset.suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ui_asset, target)
        image = f'<img src="{html.escape(target.relative_to(root).as_posix(), quote=True)}" alt="Approved product UI asset">'
    font_source = _font_source()
    font_target = root / "assets" / "KaTeX_SansSerif-Regular.ttf"
    if font_source and font_source.is_file():
        font_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(font_source, font_target)
    cta = str(item.get("brief", {}).get("cta_text") or "Learn more")
    context = facts[0] if facts else "Product story needs approved facts"
    highlight = facts[1] if len(facts) > 1 else context
    scene_html = []
    for i, (start, duration, text) in enumerate(((0, 4, brand_name), (4, 5, title), (9, 6, f"{context} {highlight}"), (15, 5, cta))):
        image_src = scene_images[i].relative_to(root).as_posix() if i < len(scene_images) else ""
        scene_html.append(f'<section id="scene-{i}" class="clip" style="z-index:{i + 1}" data-start="{start}" data-duration="{duration}" data-track-index="{i}"><div class="scene-inner"><img src="{html.escape(image_src, quote=True)}" alt="{html.escape(text, quote=True)}">{image if i == 2 else ""}</div></section>')
    scenes = "".join(scene_html)
    content = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=1080,height=1920"><title>{title}</title><script src="assets/gsap.min.js"></script><style>@font-face{{font-family:StudioSans;src:url('assets/KaTeX_SansSerif-Regular.ttf') format('truetype');font-weight:400 800}}html,body{{margin:0;width:1080px;height:1920px;background:#0f2640;color:#f5f7fa;font:700 52px/1.2 StudioSans,sans-serif}}#root{{width:1080px;height:1920px;position:relative;overflow:hidden}}.clip{{position:absolute;inset:0;display:grid;place-items:center;text-align:center}}.scene-inner{{position:relative;z-index:2;width:82%;min-height:120px;padding:8%;box-sizing:border-box;overflow-wrap:anywhere;opacity:1;color:#f5f7fa}}img{{max-width:100%;max-height:48%;display:block;margin:40px auto}}</style></head><body><div id="root" data-composition-id="marketing-studio" data-start="0" data-width="1080" data-height="1920" data-duration="20">{scenes}</div><script>const tl=gsap.timeline({{paused:true}});tl.from("#scene-0 .scene-inner",{{y:30,duration:.6}},0);tl.from("#scene-1 .scene-inner",{{y:30,duration:.6}},4);tl.from("#scene-2 .scene-inner",{{y:30,duration:.6}},9);tl.from("#scene-3 .scene-inner",{{y:30,duration:.6}},15);window.__timelines["marketing-studio"]=tl;</script></body></html>'''
    path = root / "index.html"
    path.write_text(content, encoding="utf-8")
    return path


def _zip(root: Path, files: list[Path]) -> Path:
    target = root / "marketing-media.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_file() and _inside(path, root):
                archive.write(path, path.relative_to(root).as_posix())
    return target


def create_media_artifacts(brand: Any, profile: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Create draft media and return a manifest; never sends or publishes."""
    if not isinstance(item, dict) or not isinstance(item.get("brief", {}), dict):
        raise ValueError("item and item.brief must be objects")
    root = _root(item)
    name = brand.get("name", "Brand") if isinstance(brand, dict) else str(brand or "Brand")
    brief = item["brief"]
    facts = brief.get("approved_facts", [])
    body_facts = [line.strip() for line in str(brief.get("body", "")).splitlines() if line.strip()]
    facts = [str(value).strip() for value in facts if str(value).strip()] if isinstance(facts, list) else ([str(facts).strip()] if facts else [])
    facts.extend(value for value in body_facts if value not in facts)
    fact = facts[0] if facts else ""
    accent = CYAN
    outputs: list[dict[str, Any]] = []
    for filename, size, subtitle, avatar in (("avatar.png", (512, 512), "", True), ("banner.png", (1500, 500), str(profile.get("positioning") or fact or "Brand profile"), False), ("social-card.png", (1080, 1080), fact or str(profile.get("positioning") or "Brand profile"), False)):
        outputs.append(_write_png(root / filename, size, str(name), subtitle, accent, avatar=avatar))
    carousel_facts = [str(value) for value in facts[:3]] if isinstance(facts, list) else []
    for index, card_fact in enumerate(carousel_facts, 1):
        outputs.append(_write_png(root / f"carousel-{index:02d}.png", (1080, 1080), str(name), card_fact, accent))
    ui_asset = _ui_asset(item, root) if item.get("kind") == "video_brief" else None
    needs_input: list[str] = []
    if not facts:
        needs_input.append("approved_facts")
    if item.get("kind") == "video_brief":
        if ui_asset is None:
            needs_input.append("project_ui_asset")
        runtime_config = _runtime_config()
        gsap_source = Path(str(runtime_config.get("gsap_source", ""))) if runtime_config.get("gsap_source") else None
        vendor_root = Path(__file__).resolve().parents[1] / "vendor" / "marketing-media"
        if gsap_source and gsap_source.is_file() and _inside(gsap_source, vendor_root):
            (root / "assets").mkdir(exist_ok=True)
            shutil.copyfile(gsap_source, root / "assets" / "gsap.min.js")
        else:
            needs_input.append("gsap_runtime")
        scene_texts = [str(name), str(item.get("title", "Launch")), " ".join(facts[:2]) or "Product story needs more detail", str(brief.get("cta_text") or "Learn more")]
        scene_images = []
        for index, scene_text in enumerate(scene_texts):
            scene_path = root / f"scene-{index + 1:02d}.png"
            _write_png(scene_path, (1080, 1920), str(name), scene_text, CYAN)
            outputs.append({"path": str(scene_path), "mime": "image/png", "width": 1080, "height": 1920, "provenance": "generated storyboard scene"})
            scene_images.append(scene_path)
        composition = _composition(root, str(name), item, ui_asset, facts, scene_images)
        outputs.append({"path": str(composition), "mime": "text/html", "provenance": "deterministic HyperFrames composition"})
        runtime = _runtime()
        if runtime and not needs_input:
            executable, args, version = runtime
            try:
                check = subprocess.run([executable, *args, "check", "."], cwd=root, capture_output=True, text=True, timeout=120, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError("HyperFrames check could not complete") from exc
            outputs.append({"runtime": version, "check_returncode": check.returncode, "check_output": (check.stdout + check.stderr)[-1000:]})
            if check.returncode != 0:
                raise RuntimeError("HyperFrames check failed")
            mp4 = root / "launch-video.mp4"
            try:
                render = subprocess.run([executable, *args, "render", ".", "--output", "launch-video.mp4", "--quality", "draft"], cwd=root, capture_output=True, text=True, timeout=300, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError("HyperFrames render could not complete") from exc
            render_output = (render.stdout + render.stderr)[-1000:]
            outputs.append({"path": str(mp4), "mime": "video/mp4", "runtime_returncode": render.returncode, "runtime_output": render_output})
            if render.returncode != 0 or not mp4.is_file() or mp4.stat().st_size == 0:
                raise RuntimeError("HyperFrames render failed")
            if not FFPROBE.is_file():
                raise RuntimeError("ffprobe runtime is unavailable")
            try:
                probe = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=width,height,r_frame_rate", "-of", "json", str(mp4)], capture_output=True, text=True, timeout=30, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError("ffprobe verification could not complete") from exc
            if probe.returncode != 0:
                raise RuntimeError("ffprobe verification failed")
            outputs.append({"ffprobe": json.loads(probe.stdout)})
            if not FFMPEG.is_file():
                raise RuntimeError("ffmpeg runtime is unavailable")
            poster = root / "poster.jpg"
            try:
                subprocess.run([str(FFMPEG), "-y", "-ss", "17", "-i", str(mp4), "-frames:v", "1", "-q:v", "2", str(poster)], capture_output=True, text=True, timeout=60, check=True)
            except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                raise RuntimeError("poster extraction failed") from exc
            outputs.append({"path": str(poster), "mime": "image/jpeg", "provenance": "settled launch-video frame"})
        else:
            outputs.append({"runtime": "unavailable" if not runtime else "blocked_missing_input"})
    metadata = {"brand_id": item["brand_id"], "item_id": item.get("id", "draft"), "revision": item.get("revision", 1), "state": "draft", "reviewed": False, "rights": "generated from supplied brand inputs; no stock media", "provenance": "local deterministic generation", "needs_input": needs_input}
    meta_path = root / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    archive = _zip(root, [Path(x["path"]) for x in outputs if "path" in x] + [meta_path])
    metadata["outputs"] = outputs + [{"path": str(archive), "mime": "application/zip"}]
    return metadata
