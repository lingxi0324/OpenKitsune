"""出站远程媒体下载

Agent 回复里经常直接给出图片/文件 URL（Markdown 图片、裸链接）。旧实现
在 ``_send_extracted_media`` 里对 ``is_url`` 一律跳过，导致用户只看到被
清理后的文本，附件消失。

本模块负责把远程 URL 落到本地缓存，再交给适配器按平台能力发送：

- 只允许 http/https，拒绝 URL 内嵌凭据
- 解析域名并拒绝私有/回环/保留地址（防 SSRF，模型输出不可信）
- 手动跟随有限次重定向，每一跳都重新做地址校验
- 按 ``Content-Length`` 与累计读取量双重限制大小

失败抛 :class:`MediaFetchError`，调用方负责降级（例如把 URL 作为文本回显）。
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import socket
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx

from .base import sanitize_filename

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_DEST_DIR = Path("data/media/outbound")
MAX_REDIRECTS = 3
_READ_CHUNK = 64 * 1024

_ALLOWED_SCHEMES = frozenset({"http", "https"})

_CONTENT_TYPE_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/amr": ".amr",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "text/plain": ".txt",
}

_MEDIA_TYPE_FALLBACK_SUFFIX = {
    "image": ".jpg",
    "audio": ".bin",
    "video": ".mp4",
    "file": ".bin",
}


class MediaFetchError(RuntimeError):
    """远程媒体无法安全下载或超过大小限制。"""


def _assert_public_address(host: str, port: int | None) -> None:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise MediaFetchError(f"无法解析媒体域名 {host!r}: {exc}") from exc
    if not infos:
        raise MediaFetchError(f"媒体域名 {host!r} 无可用地址")
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise MediaFetchError(f"非法解析结果: {address!r}") from None
        if not ip.is_global:
            raise MediaFetchError(f"拒绝访问非公网地址: {address}")


async def _assert_public_host(host: str | None, port: int | None) -> None:
    if not host:
        raise MediaFetchError("URL 缺少主机名")
    await asyncio.to_thread(_assert_public_address, host, port)


def _pick_filename(url: str, content_type: str, media_type: str) -> str:
    parsed = urlparse(url)
    raw_name = sanitize_filename(unquote(Path(parsed.path).name or "")) or "media"
    suffix = Path(raw_name).suffix.lower()

    if not suffix:
        suffix = _CONTENT_TYPE_SUFFIX.get(content_type, "") or _MEDIA_TYPE_FALLBACK_SUFFIX.get(
            media_type, ".bin"
        )
        raw_name = f"{raw_name}{suffix}"

    digest = hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()[:10]
    stem = Path(raw_name).stem[:60] or "media"
    return f"{stem}_{digest}{Path(raw_name).suffix}"


async def fetch_remote_media(
    url: str,
    *,
    media_type: str = "file",
    max_bytes: int = DEFAULT_MAX_BYTES,
    dest_dir: Path | None = None,
) -> Path:
    """把 ``url`` 下载到本地并返回路径。

    Raises:
        MediaFetchError: URL 非法、目标地址非公网、HTTP 失败或超出大小限制。
    """
    if not url:
        raise MediaFetchError("URL 为空")

    target_dir = Path(dest_dir) if dest_dir else DEFAULT_DEST_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    current = url
    timeout = httpx.Timeout(DEFAULT_TIMEOUT_SECONDS)

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": "OpenKitsune/1.0 (+im-media)"},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme not in _ALLOWED_SCHEMES:
                raise MediaFetchError(f"不支持的协议: {parsed.scheme!r}")
            if parsed.username or parsed.password:
                raise MediaFetchError("拒绝带凭据的媒体 URL")
            await _assert_public_host(parsed.hostname, parsed.port)

            async with client.stream("GET", current) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise MediaFetchError("重定向缺少 Location")
                    current = urljoin(current, location)
                    continue

                if response.status_code != 200:
                    raise MediaFetchError(f"HTTP {response.status_code}")

                declared = response.headers.get("content-length")
                if declared:
                    try:
                        if int(declared) > max_bytes:
                            raise MediaFetchError(
                                f"媒体超过大小限制 ({declared} > {max_bytes} bytes)"
                            )
                    except ValueError:
                        pass

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes(_READ_CHUNK):
                    total += len(chunk)
                    if total > max_bytes:
                        raise MediaFetchError(f"媒体超过大小限制 ({max_bytes} bytes)")
                    chunks.append(chunk)

                content_type = (response.headers.get("content-type") or "").split(";")[0]
                filename = _pick_filename(current, content_type.strip().lower(), media_type)
                path = target_dir / filename
                await asyncio.to_thread(path.write_bytes, b"".join(chunks))
                logger.info(
                    "[MediaFetch] Downloaded %s -> %s (%d bytes)",
                    current[:120],
                    path,
                    total,
                )
                return path

    raise MediaFetchError("重定向次数过多")
