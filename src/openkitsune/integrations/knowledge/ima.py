"""Async client for Tencent ima's public knowledge-base OpenAPI."""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any

import httpx

IMA_BASE_URL = "https://ima.qq.com"


class IMAAPIError(RuntimeError):
    """A sanitized failure returned by the ima service or its transport."""

    def __init__(self, message: str, *, code: str = "ima_error") -> None:
        super().__init__(message)
        self.code = code


class IMAClient:
    """Minimal ima knowledge-base client used for validation and retrieval."""

    def __init__(
        self,
        client_id: str,
        api_key: str,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id.strip()
        self._api_key = api_key.strip()
        self._timeout = timeout
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._api_key)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise IMAAPIError("请填写 ima Client ID 和 API Key", code="missing_credentials")

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "ima-openapi-clientid": self._client_id,
            "ima-openapi-apikey": self._api_key,
        }
        kwargs: dict[str, Any] = {
            "base_url": IMA_BASE_URL,
            "timeout": self._timeout,
            "follow_redirects": False,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**kwargs) as client:
                response = await client.post(path, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise IMAAPIError("连接 ima 超时，请稍后重试", code="timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise IMAAPIError(
                f"ima 服务返回 HTTP {exc.response.status_code}",
                code="http_error",
            ) from exc
        except httpx.RequestError as exc:
            raise IMAAPIError("无法连接 ima 服务，请检查网络", code="network_error") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise IMAAPIError("ima 返回了无法解析的响应", code="invalid_response") from exc
        if not isinstance(body, dict):
            raise IMAAPIError("ima 返回了无效的数据格式", code="invalid_response")

        retcode = body.get("retcode", body.get("code", 0))
        if retcode not in (0, "0", None):
            message = str(body.get("errmsg") or body.get("msg") or "ima 拒绝了本次请求")
            raise IMAAPIError(message, code=f"ima_{retcode}")

        data = body.get("data") or {}
        if not isinstance(data, dict):
            raise IMAAPIError("ima 返回了无效的业务数据", code="invalid_response")
        return data

    async def list_addable_knowledge_bases(self, *, limit: int = 50) -> list[dict[str, str]]:
        """List knowledge bases the current credentials may add content to."""
        data = await self._post(
            "/openapi/wiki/v1/get_addable_knowledge_base_list",
            {"cursor": "", "limit": max(1, min(limit, 50))},
        )
        raw_items = data.get("addable_knowledge_base_list") or []
        if not isinstance(raw_items, list):
            return []
        items: list[dict[str, str]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            kb_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if kb_id and name:
                items.append({"id": kb_id, "name": name})
        return items

    async def search_knowledge(
        self,
        *,
        knowledge_base_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Search one ima knowledge base and normalize its public result fields."""
        page = await self.search_knowledge_page(
            knowledge_base_id=knowledge_base_id,
            query=query,
        )
        return page["items"]

    async def search_knowledge_page(
        self,
        *,
        knowledge_base_id: str,
        query: str,
        cursor: str = "",
    ) -> dict[str, Any]:
        """Search one ima knowledge base and retain its pagination metadata."""
        kb_id = knowledge_base_id.strip()
        clean_query = query.strip()
        if not kb_id or not clean_query:
            raise IMAAPIError("知识库和搜索关键词不能为空", code="invalid_request")
        data = await self._post(
            "/openapi/wiki/v1/search_knowledge",
            {"query": clean_query, "cursor": cursor.strip(), "knowledge_base_id": kb_id},
        )
        raw_items = data.get("info_list") or []
        if not isinstance(raw_items, list):
            raw_items = []
        results: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            media_id = str(item.get("media_id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not media_id and not title:
                continue
            highlight = str(item.get("highlight_content") or "")
            results.append(
                {
                    "media_id": media_id,
                    "title": title or "未命名资料",
                    "parent_folder_id": str(item.get("parent_folder_id") or ""),
                    "highlight_content": highlight,
                    "excerpt_available": bool(highlight),
                    "match_type": "content" if highlight else "title_only",
                }
            )
        return {
            "items": results,
            "is_end": bool(data.get("is_end", True)),
            "next_cursor": str(data.get("next_cursor") or ""),
        }

    async def get_knowledge_list(
        self,
        *,
        knowledge_base_id: str,
        folder_id: str = "",
        cursor: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Browse one ima knowledge-base folder without modifying remote content."""
        kb_id = knowledge_base_id.strip()
        if not kb_id:
            raise IMAAPIError("知识库不能为空", code="invalid_request")

        payload: dict[str, Any] = {
            "cursor": cursor.strip(),
            "limit": max(1, min(int(limit), 50)),
            "knowledge_base_id": kb_id,
        }
        clean_folder_id = folder_id.strip()
        if clean_folder_id:
            payload["folder_id"] = clean_folder_id

        data = await self._post("/openapi/wiki/v1/get_knowledge_list", payload)
        raw_items = data.get("knowledge_list") or []
        if not isinstance(raw_items, list):
            raw_items = []

        items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            media_id = str(item.get("media_id") or "").strip()
            item_folder_id = str(item.get("folder_id") or "").strip()
            title = str(item.get("title") or item.get("name") or "").strip()
            if not media_id and not item_folder_id and not title:
                continue
            item_type = "folder" if item_folder_id and not media_id else "file"
            normalized: dict[str, Any] = {
                "type": item_type,
                "title": title or ("未命名文件夹" if item_type == "folder" else "未命名资料"),
                "parent_folder_id": str(item.get("parent_folder_id") or ""),
            }
            if media_id:
                normalized["media_id"] = media_id
            if item_folder_id:
                normalized["folder_id"] = item_folder_id
            if item.get("media_type") is not None:
                normalized["media_type"] = item.get("media_type")
            if item_type == "folder":
                normalized["file_count"] = int(item.get("file_number") or 0)
                normalized["folder_count"] = int(item.get("folder_number") or 0)
            items.append(normalized)

        raw_path = data.get("current_path") or []
        current_path: list[dict[str, str]] = []
        if isinstance(raw_path, list):
            for item in raw_path:
                if not isinstance(item, dict):
                    continue
                path_folder_id = str(item.get("folder_id") or "").strip()
                name = str(item.get("name") or "").strip()
                if path_folder_id or name:
                    current_path.append({"folder_id": path_folder_id, "name": name})

        return {
            "items": items,
            "is_end": bool(data.get("is_end", True)),
            "next_cursor": str(data.get("next_cursor") or ""),
            "current_path": current_path,
        }

    async def get_media_info(self, *, media_id: str) -> dict[str, Any]:
        """Resolve the temporary read-only access information for one knowledge item."""
        clean_media_id = media_id.strip()
        if not clean_media_id:
            raise IMAAPIError("媒体 ID 不能为空", code="invalid_request")

        data = await self._post(
            "/openapi/wiki/v1/get_media_info",
            {"media_id": clean_media_id},
        )
        try:
            media_type = int(data.get("media_type") or 0)
        except (TypeError, ValueError):
            media_type = 0

        url_info = data.get("url_info") or {}
        if not isinstance(url_info, dict):
            url_info = {}
        raw_headers = url_info.get("headers") or {}
        headers: dict[str, str] = {}
        if isinstance(raw_headers, dict):
            for key, value in list(raw_headers.items())[:32]:
                clean_key = str(key or "").strip()
                clean_value = str(value or "").strip()
                if clean_key and "\r" not in clean_key and "\n" not in clean_key:
                    if "\r" not in clean_value and "\n" not in clean_value:
                        headers[clean_key] = clean_value

        notebook_info = data.get("notebook_ext_info") or {}
        if not isinstance(notebook_info, dict):
            notebook_info = {}
        return {
            "media_type": media_type,
            "url": str(url_info.get("url") or "").strip(),
            "headers": headers,
            "notebook_id": str(notebook_info.get("notebook_id") or "").strip(),
        }

    async def get_note_content(self, *, note_id: str) -> str:
        """Read a note-backed knowledge item as plain text."""
        clean_note_id = note_id.strip()
        if not clean_note_id:
            raise IMAAPIError("笔记 ID 不能为空", code="invalid_request")
        data = await self._post(
            "/openapi/note/v1/get_doc_content",
            {"doc_id": clean_note_id, "target_content_format": 0},
        )
        return str(data.get("content") or "")

    async def read_media_text(
        self,
        *,
        media_id: str,
        start_page: int = 1,
        max_pages: int = 20,
        max_chars: int = 40_000,
        max_bytes: int = 20 * 1024 * 1024,
    ) -> dict[str, Any]:
        """Read text from an ima knowledge item without persisting the source file."""
        info = await self.get_media_info(media_id=media_id)
        media_type = int(info["media_type"] or 0)
        char_limit = max(1_000, min(int(max_chars), 80_000))

        if media_type == 11 and info["notebook_id"]:
            content = await self.get_note_content(note_id=info["notebook_id"])
            return {
                "media_type": media_type,
                "content": content[:char_limit],
                "char_count": min(len(content), char_limit),
                "truncated": len(content) > char_limit,
                "content_type": "text/plain",
            }

        url = str(info["url"] or "")
        if not url:
            raise IMAAPIError(
                "ima 未提供该资料的可访问原文",
                code="content_unavailable",
            )
        content, content_type = await self._download_media(
            url=url,
            headers=info["headers"],
            max_bytes=max_bytes,
        )

        if media_type == 1 or "application/pdf" in content_type:
            extracted = await asyncio.to_thread(
                _extract_pdf_text,
                content,
                start_page=max(1, int(start_page)),
                max_pages=max(1, min(int(max_pages), 50)),
                max_chars=char_limit,
            )
            return {"media_type": media_type, "content_type": "application/pdf", **extracted}

        if media_type in {2, 6} or "text/html" in content_type:
            text = _extract_html_text(content)
        elif media_type in {7, 13} or content_type.startswith("text/"):
            text = content.decode("utf-8", errors="replace")
        else:
            raise IMAAPIError(
                f"当前尚不支持读取该资料类型（media_type={media_type}）",
                code="unsupported_media_type",
            )

        clean_text = text.strip()
        if not clean_text:
            raise IMAAPIError("该资料未提取到可读文字", code="empty_content")
        return {
            "media_type": media_type,
            "content_type": content_type or "text/plain",
            "content": clean_text[:char_limit],
            "char_count": min(len(clean_text), char_limit),
            "truncated": len(clean_text) > char_limit,
        }

    async def _download_media(
        self,
        *,
        url: str,
        headers: dict[str, str],
        max_bytes: int,
    ) -> tuple[bytes, str]:
        """Download an ima media resource into bounded memory after SSRF validation."""
        from openkitsune.utils.url_safety import is_safe_url

        safe, reason = await is_safe_url(url)
        if not safe:
            raise IMAAPIError(f"ima 原文地址未通过安全检查：{reason}", code="unsafe_media_url")

        byte_limit = max(1, int(max_bytes))
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    declared_size = int(response.headers.get("content-length") or 0)
                    if declared_size > byte_limit:
                        raise IMAAPIError(
                            f"ima 原文超过可读取大小上限（{byte_limit} 字节）",
                            code="content_too_large",
                        )
                    chunks: list[bytes] = []
                    downloaded = 0
                    async for chunk in response.aiter_bytes():
                        downloaded += len(chunk)
                        if downloaded > byte_limit:
                            raise IMAAPIError(
                                f"ima 原文超过可读取大小上限（{byte_limit} 字节）",
                                code="content_too_large",
                            )
                        chunks.append(chunk)
                    return b"".join(chunks), response.headers.get("content-type", "")
        except IMAAPIError:
            raise
        except httpx.TimeoutException as exc:
            raise IMAAPIError("读取 ima 原文超时，请稍后重试", code="timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise IMAAPIError(
                f"ima 原文服务返回 HTTP {exc.response.status_code}",
                code="http_error",
            ) from exc
        except httpx.RequestError as exc:
            raise IMAAPIError("无法读取 ima 原文", code="network_error") from exc


def _extract_pdf_text(
    content: bytes,
    *,
    start_page: int,
    max_pages: int,
    max_chars: int,
) -> dict[str, Any]:
    """Extract a bounded page window from in-memory PDF bytes."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IMAAPIError(
            "PDF 正文读取组件未安装，请修复 OpenKitsune 运行环境",
            code="pdf_reader_unavailable",
        ) from exc

    try:
        reader = PdfReader(BytesIO(content))
        total_pages = len(reader.pages)
        first_index = min(max(start_page - 1, 0), total_pages)
        stop_index = min(first_index + max_pages, total_pages)
        parts: list[str] = []
        pages_read = 0
        char_count = 0
        clipped = False
        for index in range(first_index, stop_index):
            page_text = (reader.pages[index].extract_text() or "").strip()
            page_block = f"\n\n--- Page {index + 1} ---\n\n{page_text}"
            remaining = max_chars - char_count
            if remaining <= 0:
                clipped = True
                break
            if len(page_block) > remaining:
                page_block = page_block[:remaining]
                clipped = True
            parts.append(page_block)
            char_count += len(page_block)
            pages_read += 1
            if clipped:
                break
    except IMAAPIError:
        raise
    except Exception as exc:
        raise IMAAPIError("无法解析 ima 中的 PDF 原文", code="pdf_parse_error") from exc

    text = "".join(parts).strip()
    if not text:
        raise IMAAPIError(
            "PDF 中未提取到可读文字，文件可能是扫描件",
            code="empty_content",
        )
    next_page = first_index + pages_read + 1
    truncated = clipped or next_page <= total_pages
    return {
        "content": text,
        "char_count": len(text),
        "start_page": first_index + 1,
        "pages_read": pages_read,
        "total_pages": total_pages,
        "next_page": next_page if truncated else None,
        "truncated": truncated,
    }


def _extract_html_text(content: bytes) -> str:
    """Extract readable text from an in-memory HTML resource."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(content, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
