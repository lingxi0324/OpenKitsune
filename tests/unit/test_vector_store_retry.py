from unittest.mock import patch


def test_failed_vector_store_retry_resets_lazy_import_state(tmp_path):
    import openkitsune.memory.vector_store as vector_store_module

    original_transformers = vector_store_module._sentence_transformers_available
    original_chromadb = vector_store_module._chromadb
    try:
        vector_store_module._sentence_transformers_available = False
        vector_store_module._chromadb = None
        with patch.object(vector_store_module.VectorStore, "_start_background_init"):
            store = vector_store_module.VectorStore(data_dir=tmp_path, model_name="test")
        store._init_state = "failed"
        store._init_failed = True
        store._init_fail_time = 0
        store._init_retry_cooldown = 0

        with patch.object(vector_store_module.VectorStore, "_start_background_init"):
            result = store._ensure_initialized()

        assert vector_store_module._sentence_transformers_available is None
        assert vector_store_module._chromadb is None
        assert result is False
    finally:
        vector_store_module._sentence_transformers_available = original_transformers
        vector_store_module._chromadb = original_chromadb


def test_lazy_import_short_circuits_after_a_known_transformers_failure():
    import openkitsune.memory.vector_store as vector_store_module

    original_transformers = vector_store_module._sentence_transformers_available
    original_chromadb = vector_store_module._chromadb
    try:
        vector_store_module._sentence_transformers_available = False
        assert vector_store_module._lazy_import() is False
    finally:
        vector_store_module._sentence_transformers_available = original_transformers
        vector_store_module._chromadb = original_chromadb


def test_lazy_import_retries_after_its_state_is_reset():
    import openkitsune.memory.vector_store as vector_store_module

    original_transformers = vector_store_module._sentence_transformers_available
    original_chromadb = vector_store_module._chromadb
    try:
        vector_store_module._sentence_transformers_available = None
        vector_store_module._chromadb = None

        with patch(
            "openkitsune.runtime_env.inject_module_paths_runtime",
            side_effect=RuntimeError("no runtime"),
        ):
            vector_store_module._lazy_import()

        assert vector_store_module._sentence_transformers_available is not None
    finally:
        vector_store_module._sentence_transformers_available = original_transformers
        vector_store_module._chromadb = original_chromadb
