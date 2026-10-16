use crate::prelude::*;

pub(crate) fn pypi_json_urls(package: &str, index_url: Option<&str>) -> Vec<String> {
    let mut urls = Vec::new();
    if let Some(index_url) = index_url {
        let root = index_url.trim_end_matches('/').trim_end_matches("/simple");
        let json_root = if root.ends_with("/pypi") {
            root.to_string()
        } else {
            format!("{root}/pypi")
        };
        urls.push(format!("{json_root}/{package}/json"));
    }

    for fallback_root in ["https://pypi.tuna.tsinghua.edu.cn", "https://pypi.org"] {
        let fallback = format!("{fallback_root}/pypi/{package}/json");
        if !urls.contains(&fallback) {
            urls.push(fallback);
        }
    }
    urls
}

/// Fetch available versions of a package from PyPI JSON API.
/// Returns JSON array of version strings, newest first.
#[tauri::command]
pub(crate) async fn fetch_pypi_versions(
    package: String,
    index_url: Option<String>,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        // 构建候选 URL 列表，多源回退
        // 注意：并非所有 PyPI 镜像都支持 /pypi/<pkg>/json API（阿里云不支持）
        // 因此即使用户指定了 index_url，也要带上已验证可用的回退源
        let urls = pypi_json_urls(&package, index_url.as_deref());

        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(10))
            .user_agent("openkitsune-desktop/1.0")
            .build()
            .map_err(|e| format!("HTTP client error: {e}"))?;

        // 多源自动回退
        let mut last_err = String::new();
        let mut resp_ok = None;
        for url in &urls {
            match client.get(url).send() {
                Ok(r) => match r.error_for_status() {
                    Ok(r) => {
                        resp_ok = Some(r);
                        break;
                    }
                    Err(e) => {
                        last_err = format!("fetch PyPI versions failed ({}): {}", url, e);
                    }
                },
                Err(e) => {
                    last_err = format!("fetch PyPI versions failed ({}): {}", url, e);
                }
            }
        }
        let resp = resp_ok.ok_or(last_err)?;

        let body: serde_json::Value = resp
            .json()
            .map_err(|e| format!("parse PyPI JSON failed: {e}"))?;

        // PyPI JSON API: { "releases": { "1.0.0": [...], "1.2.3": [...], ... } }
        let releases = body
            .get("releases")
            .and_then(|v| v.as_object())
            .ok_or_else(|| "unexpected PyPI JSON format: missing 'releases'".to_string())?;

        let mut versions: Vec<String> = releases
            .keys()
            .filter(|v| {
                // Skip pre-release / dev versions with letters like "a", "b", "rc", "dev"
                // unless the version contains only dots and digits
                let v_lower = v.to_lowercase();
                !v_lower.contains("dev") && !v_lower.contains("alpha")
            })
            .cloned()
            .collect();

        // Sort by semver-ish descending (newest first).
        // Use a simple tuple-based comparison: split on '.', parse each part.
        versions.sort_by(|a, b| {
            let parse = |s: &str| -> Vec<i64> {
                s.split('.')
                    .map(|p| {
                        // strip pre-release suffixes for sorting: "1a0" -> 1
                        let numeric: String =
                            p.chars().take_while(|c| c.is_ascii_digit()).collect();
                        numeric.parse::<i64>().unwrap_or(0)
                    })
                    .collect()
            };
            parse(b).cmp(&parse(a))
        });

        Ok(serde_json::to_string(&versions).unwrap_or_else(|_| "[]".into()))
    })
    .await
}

/// Generic HTTP GET JSON proxy – bypasses CORS for the webview.
/// Returns the response body as a JSON string.
#[tauri::command]
pub(crate) async fn http_get_json(url: String) -> Result<String, String> {
    spawn_blocking_result(move || {
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .user_agent("openkitsune-desktop/1.0")
            .build()
            .map_err(|e| format!("HTTP client error: {e}"))?;

        let resp = client
            .get(&url)
            .send()
            .map_err(|e| format!("HTTP GET failed ({}): {}", url, e))?
            .error_for_status()
            .map_err(|e| format!("HTTP GET failed ({}): {}", url, e))?;

        let text = resp
            .text()
            .map_err(|e| format!("read response body failed: {e}"))?;

        Ok(text)
    })
    .await
}

/// Generic HTTP proxy – supports GET/POST with custom headers, bypasses CORS for the webview.
/// `method`: "GET" | "POST"
/// `headers`: JSON object of header key-value pairs, e.g. {"Authorization": "Bearer sk-xxx"}
/// `body`: optional request body string (for POST)
/// Returns `{ status, body }` as JSON string.
#[tauri::command]
pub(crate) async fn http_proxy_request(
    url: String,
    method: Option<String>,
    headers: Option<std::collections::HashMap<String, String>>,
    body: Option<String>,
    timeout_secs: Option<u64>,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let timeout = timeout_secs.unwrap_or(30);
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(timeout))
            .user_agent("openkitsune-desktop/1.0")
            .build()
            .map_err(|e| format!("HTTP client error: {e}"))?;

        let m = method.as_deref().unwrap_or("GET").to_uppercase();
        let mut req_builder = match m.as_str() {
            "POST" => client.post(&url),
            "PUT" => client.put(&url),
            "DELETE" => client.delete(&url),
            _ => client.get(&url),
        };

        if let Some(h) = headers {
            for (k, v) in h {
                req_builder = req_builder.header(&k, &v);
            }
        }
        if let Some(b) = body {
            req_builder = req_builder.body(b);
        }

        let resp = req_builder
            .send()
            .map_err(|e| format!("HTTP {} failed ({}): {}", m, url, e))?;

        let status = resp.status().as_u16();
        let resp_body = resp
            .text()
            .map_err(|e| format!("read response body failed: {e}"))?;

        Ok(format!(
            "{{\"status\":{},\"body\":{}}}",
            status,
            serde_json::to_string(&resp_body).unwrap_or_else(|_| "\"\"".to_string())
        ))
    })
    .await
}

// ── Local backend fetch (proxy-safe) ─────────────────────────────────
//
// On macOS, Clash / V2Ray set a *system-level* proxy via Network Preferences.
// WKWebView's native fetch() and @tauri-apps/plugin-http's reqwest client
// both honour that proxy, causing requests to 127.0.0.1 to be routed through
// the external proxy server — which cannot reach the user's localhost.
//
// `.no_proxy()` on the reqwest Client builder **completely disables** all proxy
// detection (env vars, system-configuration, everything) so the request always
// goes directly to the local backend.
//
// The response body is streamed back to JS via a Tauri Channel, preserving
// SSE / chunked-transfer behaviour for the chat view.

#[derive(Clone, Serialize)]
#[serde(tag = "event", content = "data", rename_all = "camelCase")]
pub(crate) enum BackendFetchEvent {
    Chunk { text: String },
    Done,
    Error { message: String },
}

/// Drain the longest decodable UTF-8 prefix, retaining an incomplete trailing
/// character so the next stream chunk can complete it.
pub(crate) fn take_valid_utf8_prefix(buf: &mut Vec<u8>) -> String {
    let mut output = String::new();
    loop {
        match std::str::from_utf8(buf) {
            Ok(text) => {
                output.push_str(text);
                buf.clear();
                break;
            }
            Err(error) => {
                let valid_up_to = error.valid_up_to();
                if valid_up_to > 0 {
                    if let Ok(text) = std::str::from_utf8(&buf[..valid_up_to]) {
                        output.push_str(text);
                    }
                }
                match error.error_len() {
                    None => {
                        buf.drain(..valid_up_to);
                        break;
                    }
                    Some(invalid_len) => {
                        output.push('\u{FFFD}');
                        buf.drain(..valid_up_to + invalid_len);
                    }
                }
            }
        }
    }
    output
}

/// Active streaming fetches keyed by the frontend-supplied `fetch_id`.
///
/// When the JS-side `ReadableStream.cancel()` fires (user closes a chat
/// turn, navigates away, AbortController.abort, …) the frontend now calls
/// `backend_fetch_cancel(fetch_id)`. We flip the matching `AtomicBool`
/// and the spawned chunk loop exits on its next iteration, dropping the
/// `reqwest::Response` which in turn closes the TCP/SSE connection and
/// frees the chunk buffers. Without this, the Rust task would continue
/// reading from a backend that may not stop sending (LLM streams in
/// particular run to completion), uselessly piling chunks into IPC and
/// keeping ~10-50 MB of intermediate strings allocated.
///
/// Pre-cancel race: if `backend_fetch_cancel` arrives *before*
/// `backend_fetch` has registered (extremely tight but possible across
/// the IPC boundary), we still insert the entry as already-cancelled so
/// the subsequent fetch sees `true` on its first check and short-circuits.
use std::sync::Arc;
pub(crate) static MANAGED_FETCHES: Lazy<Mutex<HashMap<String, Arc<AtomicBool>>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

pub(crate) fn fetch_cancel_handle(fetch_id: &str) -> Arc<AtomicBool> {
    if let Ok(mut map) = MANAGED_FETCHES.lock() {
        return map
            .entry(fetch_id.to_string())
            .or_insert_with(|| Arc::new(AtomicBool::new(false)))
            .clone();
    }
    // Mutex poisoned (a previous panic left the map in an indeterminate
    // state). Hand the caller a fresh detached handle so the fetch still
    // runs — it just won't be cancellable from JS. Better than panicking
    // the Tauri command thread.
    Arc::new(AtomicBool::new(false))
}

pub(crate) fn fetch_unregister(fetch_id: &str) {
    if let Ok(mut map) = MANAGED_FETCHES.lock() {
        map.remove(fetch_id);
    }
}

/// Frontend-callable cancel: flips the cancel flag for an in-flight
/// `backend_fetch`. Idempotent and never errors — calling cancel on an
/// unknown id (because the fetch already finished, or hadn't yet
/// registered) pre-arms a flag so the registration sees it.
#[tauri::command]
pub(crate) fn backend_fetch_cancel(fetch_id: String) {
    let map = MANAGED_FETCHES.lock();
    if let Ok(mut map) = map {
        match map.get(&fetch_id) {
            Some(flag) => flag.store(true, Ordering::SeqCst),
            None => {
                map.insert(fetch_id, Arc::new(AtomicBool::new(true)));
            }
        }
    }
}

#[tauri::command]
pub(crate) async fn backend_fetch(
    on_event: tauri::ipc::Channel<BackendFetchEvent>,
    fetch_id: String,
    url: String,
    method: Option<String>,
    headers: Option<std::collections::HashMap<String, String>>,
    body: Option<String>,
    timeout_secs: Option<u64>,
) -> Result<serde_json::Value, String> {
    if !url.starts_with("http://127.0.0.1") && !url.starts_with("http://localhost") {
        return Err("backend_fetch only allows localhost URLs".into());
    }

    // Register cancel flag *before* the network round-trip so a cancel
    // arriving mid-handshake (e.g. user hits stop right after submit)
    // still aborts.
    let cancel = fetch_cancel_handle(&fetch_id);
    if cancel.load(Ordering::SeqCst) {
        fetch_unregister(&fetch_id);
        return Err("backend_fetch cancelled before start".into());
    }

    let mut builder = reqwest::Client::builder()
        .no_proxy()
        .connect_timeout(std::time::Duration::from_secs(10));
    if let Some(t) = timeout_secs {
        builder = builder.timeout(std::time::Duration::from_secs(t));
    }
    let client = match builder.build() {
        Ok(c) => c,
        Err(e) => {
            // Important: unregister before returning so the cancel-flag
            // entry doesn't leak forever in MANAGED_FETCHES.
            fetch_unregister(&fetch_id);
            return Err(format!("HTTP client error: {e}"));
        }
    };

    let m = method.as_deref().unwrap_or("GET").to_uppercase();
    let mut req = match m.as_str() {
        "POST" => client.post(&url),
        "PUT" => client.put(&url),
        "DELETE" => client.delete(&url),
        "PATCH" => client.patch(&url),
        _ => client.get(&url),
    };
    if let Some(h) = headers {
        for (k, v) in h {
            req = req.header(&k, &v);
        }
    }
    if let Some(b) = body {
        req = req.body(b);
    }

    let resp = match req.send().await {
        Ok(r) => r,
        Err(e) => {
            fetch_unregister(&fetch_id);
            return Err(format!("HTTP {} failed ({}): {}", m, url, e));
        }
    };

    let status = resp.status().as_u16();
    let resp_headers: std::collections::HashMap<String, String> = resp
        .headers()
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_str().unwrap_or("").to_string()))
        .collect();

    let fetch_id_for_task = fetch_id.clone();
    tauri::async_runtime::spawn(async move {
        let mut response = resp;
        // Chunk-read inactivity timeout. `response.chunk().await` has no
        // built-in deadline: if the backend sent headers and then stops
        // emitting bytes without closing (Python deadlock, TCP half-open,
        // kernel buffer wedged), this future hangs forever, the cancel flag
        // is never observed, the tokio task and the underlying connection
        // both leak.
        //
        // 90s is conservative: legitimate slow models still stream tokens
        // continuously (long pauses happen during initial prefill or tool
        // round-trips, both of which complete in seconds). If a real upstream
        // legitimately needs >90s of silence we surface it as a stream
        // error — frontend's recovery polling will still rebuild state from
        // backend session history.
        const CHUNK_INACTIVITY_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(90);
        let mut pending = Vec::new();
        loop {
            if cancel.load(Ordering::SeqCst) {
                // Drop happens implicitly on loop exit; explicit log here
                // would be nice but isn't worth the perf cost.
                break;
            }
            // Convert the chunk to Vec<u8> inside the async block so the
            // Output type doesn't depend on `bytes::Bytes` (which isn't a
            // direct dependency of this crate and confuses type inference
            // when the future is wrapped). The copy is cheap — chunks are
            // typically a few KB of SSE payload that we'd be converting to
            // String::from_utf8_lossy anyway.
            let timed: Result<reqwest::Result<Option<Vec<u8>>>, tokio::time::error::Elapsed> =
                tokio::time::timeout(CHUNK_INACTIVITY_TIMEOUT, async {
                    response.chunk().await.map(|opt| opt.map(|b| b.to_vec()))
                })
                .await;
            let chunk_res = match timed {
                Ok(r) => r,
                Err(_) => {
                    // Inactivity timeout. Surface as error so frontend tears
                    // down the stream and reconciles via session history.
                    let _ = on_event.send(BackendFetchEvent::Error {
                        message: format!(
                            "backend stream stalled for {}s",
                            CHUNK_INACTIVITY_TIMEOUT.as_secs()
                        ),
                    });
                    break;
                }
            };
            match chunk_res {
                Ok(Some(chunk)) => {
                    pending.extend_from_slice(&chunk);
                    let text = take_valid_utf8_prefix(&mut pending);
                    if !text.is_empty() && on_event.send(BackendFetchEvent::Chunk { text }).is_err()
                    {
                        break;
                    }
                }
                Ok(None) => {
                    if !pending.is_empty() {
                        let text = String::from_utf8_lossy(&pending).into_owned();
                        pending.clear();
                        let _ = on_event.send(BackendFetchEvent::Chunk { text });
                    }
                    let _ = on_event.send(BackendFetchEvent::Done);
                    break;
                }
                Err(e) => {
                    let _ = on_event.send(BackendFetchEvent::Error {
                        message: e.to_string(),
                    });
                    break;
                }
            }
        }
        // response drops here → closes TCP connection, frees chunk buffers
        drop(response);
        fetch_unregister(&fetch_id_for_task);
    });

    Ok(serde_json::json!({
        "status": status,
        "headers": resp_headers,
    }))
}

pub(crate) const READ_FILE_BASE64_MAX_BYTES: u64 = 50 * 1024 * 1024;
pub(crate) const READ_FILE_BASE64_CHUNK_SIZE: usize = 256 * 1024;

#[derive(Serialize)]
pub(crate) struct LocalFileInfo {
    size: u64,
    is_file: bool,
    is_directory: bool,
}

#[derive(Serialize, Clone)]
pub(crate) struct LocalFileReadProgress {
    loaded: u64,
    total: u64,
}

struct ProgressReader<R, F> {
    inner: R,
    loaded: u64,
    total: u64,
    on_progress: F,
}

impl<R, F> ProgressReader<R, F> {
    fn new(inner: R, total: u64, on_progress: F) -> Self {
        Self {
            inner,
            loaded: 0,
            total,
            on_progress,
        }
    }
}

impl<R: Read, F: FnMut(u64, u64)> Read for ProgressReader<R, F> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let read = self.inner.read(buf)?;
        if read > 0 {
            self.loaded = self.loaded.saturating_add(read as u64);
            (self.on_progress)(self.loaded, self.total);
        }
        Ok(read)
    }
}

#[derive(Serialize)]
pub(crate) struct LocalFileUploadResponse {
    status: u16,
    body: String,
}

/// Return local file metadata without reading the file contents.
/// Used by drag/drop handling to reject or route large files before they can
/// exhaust WebView memory.
#[tauri::command]
pub(crate) fn get_local_file_info(path: String) -> Result<LocalFileInfo, String> {
    let p = std::path::Path::new(&path);
    let meta = std::fs::metadata(p).map_err(|e| format!("Failed to stat {}: {}", path, e))?;
    Ok(LocalFileInfo {
        size: meta.len(),
        is_file: meta.is_file(),
        is_directory: meta.is_dir(),
    })
}

/// Stream a Tauri-native dropped path to the regular upload endpoint.
///
/// Browser and mobile callers already receive a `File` and use multipart fetch
/// directly. Native drag/drop only provides a filesystem path, so this adapter
/// keeps bytes out of the WebView while preserving the same `/api/upload`
/// response contract for the shared chat UI.
#[tauri::command]
pub(crate) async fn upload_local_file(
    path: String,
    url: String,
    filename: String,
    mime_type: Option<String>,
    authorization: Option<String>,
    on_progress: tauri::ipc::Channel<LocalFileReadProgress>,
) -> Result<LocalFileUploadResponse, String> {
    spawn_blocking_result(move || {
        let parsed_url =
            reqwest::Url::parse(&url).map_err(|e| format!("Invalid upload URL: {e}"))?;
        if !matches!(parsed_url.scheme(), "http" | "https") {
            return Err("Upload URL must use HTTP or HTTPS".to_string());
        }

        let file_path = PathBuf::from(&path);
        let metadata = fs::metadata(&file_path)
            .map_err(|e| format!("Failed to stat {}: {e}", file_path.display()))?;
        if !metadata.is_file() {
            return Err(format!("Not a file: {}", file_path.display()));
        }
        let total = metadata.len();
        let file = fs::File::open(&file_path)
            .map_err(|e| format!("Failed to open {}: {e}", file_path.display()))?;
        let progress_channel = on_progress.clone();
        let _ = on_progress.send(LocalFileReadProgress { loaded: 0, total });
        let reader = ProgressReader::new(file, total, move |loaded, total| {
            let _ = progress_channel.send(LocalFileReadProgress { loaded, total });
        });

        let mut part = reqwest::blocking::multipart::Part::reader_with_length(reader, total)
            .file_name(filename);
        if let Some(candidate) = mime_type.filter(|value| !value.trim().is_empty()) {
            part = part
                .mime_str(&candidate)
                .map_err(|e| format!("Invalid attachment MIME type: {e}"))?;
        }
        let form = reqwest::blocking::multipart::Form::new().part("file", part);

        let host = parsed_url.host_str().unwrap_or_default();
        let mut client_builder = reqwest::blocking::Client::builder()
            .connect_timeout(std::time::Duration::from_secs(10))
            .timeout(std::time::Duration::from_secs(15 * 60));
        if matches!(host, "localhost" | "127.0.0.1" | "::1") {
            client_builder = client_builder.no_proxy();
        }
        let client = client_builder
            .build()
            .map_err(|e| format!("HTTP client error: {e}"))?;
        let mut request = client.post(parsed_url).multipart(form);
        if let Some(token) = authorization.filter(|value| !value.trim().is_empty()) {
            request = request.bearer_auth(token);
        }
        let response = request
            .send()
            .map_err(|e| format!("Local file upload failed: {e}"))?;
        let status = response.status().as_u16();
        let body = response
            .text()
            .map_err(|e| format!("Failed to read upload response: {e}"))?;
        Ok(LocalFileUploadResponse { status, body })
    })
    .await
}

/// Read a file from disk and return its contents as a base64 data-URL.
/// Used by the frontend to handle small Tauri media file-drop events.
#[tauri::command]
pub(crate) async fn read_file_base64(
    path: String,
    on_progress: tauri::ipc::Channel<LocalFileReadProgress>,
) -> Result<String, String> {
    let p = std::path::Path::new(&path);
    let meta = std::fs::metadata(p).map_err(|e| format!("Failed to stat {}: {}", path, e))?;
    if !meta.is_file() {
        return Err(format!("Not a file: {}", path));
    }
    if meta.len() > READ_FILE_BASE64_MAX_BYTES {
        return Err(format!(
            "File too large for base64 preview: {:.1} MB (max 50 MB)",
            meta.len() as f64 / 1024.0 / 1024.0
        ));
    }
    let total = meta.len();
    let mut file = std::fs::File::open(p).map_err(|e| format!("Failed to open {}: {}", path, e))?;
    let mut data = Vec::with_capacity(total as usize);
    let mut loaded = 0_u64;
    let mut buf = vec![0_u8; READ_FILE_BASE64_CHUNK_SIZE];

    let _ = on_progress.send(LocalFileReadProgress { loaded, total });

    loop {
        let n = file
            .read(&mut buf)
            .map_err(|e| format!("Failed to read {}: {}", path, e))?;
        if n == 0 {
            break;
        }
        data.extend_from_slice(&buf[..n]);
        loaded += n as u64;
        let _ = on_progress.send(LocalFileReadProgress { loaded, total });
        tokio::task::yield_now().await;
    }
    let mime = match p
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase()
        .as_str()
    {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "bmp" => "image/bmp",
        "svg" => "image/svg+xml",
        "pdf" => "application/pdf",
        "txt" | "md" => "text/plain",
        "json" => "application/json",
        "csv" => "text/csv",
        _ => "application/octet-stream",
    };
    let b64 = base64::engine::general_purpose::STANDARD.encode(&data);
    Ok(format!("data:{};base64,{}", mime, b64))
}

pub(crate) fn sanitize_download_filename(candidate: &str) -> String {
    let leaf = std::path::Path::new(candidate)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or(candidate);
    let sanitized: String = leaf
        .chars()
        .map(|ch| match ch {
            '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*' => '_',
            ch if ch.is_control() => '_',
            ch => ch,
        })
        .collect();
    let trimmed = sanitized.trim_matches(|ch| ch == ' ' || ch == '.');
    let name = if trimmed.is_empty() {
        "download"
    } else {
        trimmed
    };
    let stem = std::path::Path::new(name)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(name);
    let reserved = matches!(
        stem.to_ascii_uppercase().as_str(),
        "CON"
            | "PRN"
            | "AUX"
            | "NUL"
            | "COM1"
            | "COM2"
            | "COM3"
            | "COM4"
            | "COM5"
            | "COM6"
            | "COM7"
            | "COM8"
            | "COM9"
            | "LPT1"
            | "LPT2"
            | "LPT3"
            | "LPT4"
            | "LPT5"
            | "LPT6"
            | "LPT7"
            | "LPT8"
            | "LPT9"
    );
    if reserved {
        format!("_{name}")
    } else {
        name.to_string()
    }
}

pub(crate) fn unique_download_path(filename: &str) -> Result<std::path::PathBuf, String> {
    let downloads_dir = dirs_next::download_dir()
        .or_else(|| dirs_next::home_dir().map(|h| h.join("Downloads")))
        .ok_or_else(|| "Cannot determine Downloads directory".to_string())?;
    std::fs::create_dir_all(&downloads_dir)
        .map_err(|e| format!("Cannot create Downloads dir: {e}"))?;

    let safe_filename = sanitize_download_filename(filename);
    let stem = std::path::Path::new(&safe_filename)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("download")
        .to_string();
    let ext = std::path::Path::new(&safe_filename)
        .extension()
        .and_then(|s| s.to_str())
        .map(|s| format!(".{s}"))
        .unwrap_or_default();
    let mut dest = downloads_dir.join(&safe_filename);
    let mut counter = 1u32;
    while dest.exists() {
        dest = downloads_dir.join(format!("{stem} ({counter}){ext}"));
        counter += 1;
    }
    Ok(dest)
}

/// Download a file from a URL and save it to the user's Downloads folder.
/// Returns the saved file path on success.
#[tauri::command]
pub(crate) async fn download_file(url: String, filename: String) -> Result<String, String> {
    let dest = unique_download_path(&filename)?;

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .no_proxy()
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {e}"))?;
    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("Download request failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("Download failed with status {}", resp.status()));
    }
    let bytes = resp
        .bytes()
        .await
        .map_err(|e| format!("Failed to read response body: {e}"))?;
    std::fs::write(&dest, &bytes).map_err(|e| format!("Failed to write file: {e}"))?;

    Ok(dest.to_string_lossy().to_string())
}

/// Copy an existing local file to the user's Downloads folder.
/// Returns the saved file path on success.
#[tauri::command]
pub(crate) fn copy_file_to_downloads(
    path: String,
    filename: Option<String>,
) -> Result<String, String> {
    let source = std::path::Path::new(&path);
    if !source.is_file() {
        return Err(format!("Source file does not exist: {path}"));
    }

    let source_name = source
        .file_name()
        .and_then(|s| s.to_str())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or("download");
    let requested_name = filename
        .as_deref()
        .and_then(|name| std::path::Path::new(name).file_name())
        .and_then(|s| s.to_str())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or(source_name);
    let dest = unique_download_path(requested_name)?;

    std::fs::copy(source, &dest).map_err(|e| format!("Failed to copy file: {e}"))?;

    Ok(dest.to_string_lossy().to_string())
}

/// Open the OS file manager and highlight the given file.
#[tauri::command]
pub(crate) fn show_item_in_folder(path: String) -> Result<(), String> {
    let p = std::path::Path::new(&path);
    if !p.exists() {
        return Err(format!("Path does not exist: {path}"));
    }
    #[cfg(target_os = "windows")]
    {
        let mut c = std::process::Command::new("explorer");
        c.args(["/select,", &path]);
        apply_no_window(&mut c);
        c.spawn()
            .map_err(|e| format!("Failed to open explorer: {e}"))?;
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .args(["-R", &path])
            .spawn()
            .map_err(|e| format!("Failed to reveal in Finder: {e}"))?;
    }
    #[cfg(target_os = "linux")]
    {
        if let Some(parent) = p.parent() {
            std::process::Command::new("xdg-open")
                .arg(parent)
                .spawn()
                .map_err(|e| format!("Failed to open file manager: {e}"))?;
        }
    }
    Ok(())
}

/// Open a local file with the system default application.
#[tauri::command]
pub(crate) fn open_file_with_default(path: String) -> Result<(), String> {
    let p = std::path::Path::new(&path);
    if !p.exists() {
        return Err(format!("File does not exist: {path}"));
    }
    #[cfg(target_os = "windows")]
    {
        let mut c = std::process::Command::new("cmd");
        c.args(["/C", "start", "", &path]);
        apply_no_window(&mut c);
        c.spawn().map_err(|e| format!("Failed to open file: {e}"))?;
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to open file: {e}"))?;
    }
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to open file: {e}"))?;
    }
    Ok(())
}

/// Export the workspace .env file. If `dest_path` is given (from a save dialog),
/// write there; otherwise fall back to Downloads with a timestamped name.
#[tauri::command]
pub(crate) fn export_env_backup(
    workspace_id: String,
    dest_path: Option<String>,
) -> Result<String, String> {
    let env_path = workspace_dir(&workspace_id).join(".env");
    if !env_path.exists() {
        return Err("No .env file found in workspace".to_string());
    }

    let dest = if let Some(p) = dest_path {
        PathBuf::from(p)
    } else {
        let downloads_dir = dirs_next::download_dir()
            .or_else(|| dirs_next::home_dir().map(|h| h.join("Downloads")))
            .ok_or_else(|| "Cannot determine Downloads directory".to_string())?;
        fs::create_dir_all(&downloads_dir)
            .map_err(|e| format!("Cannot create Downloads dir: {e}"))?;
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        downloads_dir.join(format!("openkitsune-env-backup-{ts}.env"))
    };

    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("Cannot create directory: {e}"))?;
    }

    fs::copy(&env_path, &dest).map_err(|e| format!("Failed to copy .env: {e}"))?;

    Ok(dest.to_string_lossy().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pypi_json_urls_keep_requested_source_then_known_fallbacks() {
        assert_eq!(
            pypi_json_urls("openkitsune", Some("https://mirrors.aliyun.com/pypi/simple/")),
            vec![
                "https://mirrors.aliyun.com/pypi/openkitsune/json",
                "https://pypi.tuna.tsinghua.edu.cn/pypi/openkitsune/json",
                "https://pypi.org/pypi/openkitsune/json",
            ]
        );
    }

    #[test]
    fn pypi_json_urls_do_not_duplicate_an_official_source() {
        assert_eq!(
            pypi_json_urls("openkitsune", Some("https://pypi.org/simple/")),
            vec![
                "https://pypi.org/pypi/openkitsune/json",
                "https://pypi.tuna.tsinghua.edu.cn/pypi/openkitsune/json",
            ]
        );
    }

    #[test]
    fn test_utf8_prefix_passes_through_complete_text() {
        let mut buf = "Hello, 你好!".as_bytes().to_vec();
        assert_eq!(take_valid_utf8_prefix(&mut buf), "Hello, 你好!");
        assert!(buf.is_empty());
    }

    #[test]
    fn test_utf8_prefix_holds_split_cjk_character() {
        let bytes = "有什么".as_bytes();
        let (first, second) = bytes.split_at(5);
        let mut buf = first.to_vec();

        let first_text = take_valid_utf8_prefix(&mut buf);
        assert_eq!(first_text, "有");
        assert_eq!(buf, bytes[3..5]);

        buf.extend_from_slice(second);
        let second_text = take_valid_utf8_prefix(&mut buf);
        assert_eq!(format!("{first_text}{second_text}"), "有什么");
        assert!(buf.is_empty());
    }

    #[test]
    fn test_utf8_prefix_holds_split_four_byte_character() {
        let bytes = "\u{1F389}".as_bytes();
        let mut buf = bytes[..1].to_vec();
        assert_eq!(take_valid_utf8_prefix(&mut buf), "");
        assert_eq!(buf, bytes[..1]);

        buf.extend_from_slice(&bytes[1..]);
        assert_eq!(take_valid_utf8_prefix(&mut buf), "\u{1F389}");
        assert!(buf.is_empty());
    }

    #[test]
    fn test_utf8_prefix_replaces_invalid_bytes_without_stalling() {
        let mut buf = vec![b'a', 0xFF, b'b'];
        assert_eq!(take_valid_utf8_prefix(&mut buf), "a\u{FFFD}b");
        assert!(buf.is_empty());
    }

    #[test]
    fn test_incomplete_utf8_tail_is_available_for_eof_flush() {
        let mut buf = vec![0xE4, 0xBB];
        assert_eq!(take_valid_utf8_prefix(&mut buf), "");
        assert_eq!(String::from_utf8_lossy(&buf), "\u{FFFD}");
    }

    #[test]
    fn progress_reader_streams_bytes_and_reports_cumulative_progress() {
        let updates = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let captured = updates.clone();
        let input = b"streamed attachment".to_vec();
        let total = input.len() as u64;
        let mut reader = ProgressReader::new(
            std::io::Cursor::new(input.clone()),
            total,
            move |loaded, total| {
                captured.lock().unwrap().push((loaded, total));
            },
        );
        let mut output = Vec::new();
        let mut chunk = [0_u8; 4];
        loop {
            let read = reader.read(&mut chunk).unwrap();
            if read == 0 {
                break;
            }
            output.extend_from_slice(&chunk[..read]);
        }

        assert_eq!(output, input);
        let updates = updates.lock().unwrap();
        assert!(updates.len() > 1);
        assert_eq!(updates.last(), Some(&(total, total)));
    }
}
