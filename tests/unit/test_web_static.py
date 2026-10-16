from fastapi import FastAPI
from fastapi.testclient import TestClient

from openkitsune.api.web_static import WebStaticFiles


def test_web_entry_and_marketplace_return_never_reuse_a_cached_document(tmp_path):
    (tmp_path / "index.html").write_text("<script src='/web/assets/current.js'></script>")
    (tmp_path / "sw.js").write_text("// current worker")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/current.js").write_text("// current bundle")
    app = FastAPI()
    app.mount("/web", WebStaticFiles(directory=tmp_path, html=True))
    client = TestClient(app)
    for path in ("/web/", "/web/index.html", "/web/marketplace-return", "/web/sw.js"):
        first = client.get(path)
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-store"
        repeated = client.get(
            path,
            headers={
                "If-None-Match": first.headers["etag"],
                "If-Modified-Since": first.headers["last-modified"],
            },
        )
        assert repeated.status_code == 200
        assert repeated.content == first.content
    assert client.get("/web/marketplace-return").text == client.get("/web/").text
    asset = client.get("/web/assets/current.js")
    assert (
        client.get(
            "/web/assets/current.js", headers={"If-None-Match": asset.headers["etag"]}
        ).status_code
        == 304
    )
    assert client.get("/web/missing").status_code == 404
