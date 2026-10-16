from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from openkitsune.integrations.marketplace.installer import (
    MarketplaceInstallError,
    MarketplaceInstallManager,
    _safe_extract,
    validate_marketplace_endpoint,
)


def test_endpoint_requires_https_except_loopback() -> None:
    assert validate_marketplace_endpoint("https://marketplace.openkitsune.cn/") == (
        "https://marketplace.openkitsune.cn"
    )
    assert validate_marketplace_endpoint("http://localhost:3001") == "http://localhost:3001"
    with pytest.raises(MarketplaceInstallError) as error:
        validate_marketplace_endpoint("http://marketplace.example.com")
    assert error.value.code == "marketplace_endpoint_invalid"


def test_safe_extract_rejects_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../outside.txt", "unsafe")
    with pytest.raises(MarketplaceInstallError) as error:
        _safe_extract(archive, tmp_path / "content")
    assert error.value.code == "marketplace_package_unsafe_path"


def test_verify_accepts_matching_digest_and_ed25519_signature(tmp_path: Path) -> None:
    package = tmp_path / "resource.zip"
    manifest = {
        "resource_id": "resource-test",
        "resource_type": "plugin",
        "version": "1.0.0",
        "permissions": [],
        "dependencies": [],
    }
    with zipfile.ZipFile(package, "w") as output:
        output.writestr("manifest.json", json.dumps(manifest))
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    resource_id = "resource-test"
    version = "1.0.0"
    message = f"sha256:{digest}\nresource:{resource_id}\nversion:{version}".encode()
    job = {
        "digest_sha256": digest,
        "resource_id": resource_id,
        "resource_type": "plugin",
        "version": version,
        "signature": base64.b64encode(private_key.sign(message)).decode(),
        "verification": {"public_key": base64.b64encode(public_key).decode()},
        "manifest": {
            "resource_id": resource_id,
            "resource_type": "plugin",
            "version": version,
        },
        "permissions": [],
        "dependencies": [],
    }

    MarketplaceInstallManager._verify(job, package)

    job["digest_sha256"] = "0" * 64
    with pytest.raises(MarketplaceInstallError) as error:
        MarketplaceInstallManager._verify(job, package)
    assert error.value.code == "marketplace_digest_mismatch"
