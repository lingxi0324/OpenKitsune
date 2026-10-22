#!/usr/bin/env python3
"""Standalone NeuTTS synthesis helper（迁移自 hermes-agent ``tools/neutts_synth.py``）。

由 ``openkitsune.voice.tts_local._generate_neutts`` 以子进程调用，使 ~500MB 的
NeuTTS 模型只在合成期间驻留内存、进程退出即释放。用法：

    python neutts_synth.py --text "你好" --out out.wav \
        --ref-audio jo.wav --ref-text jo.txt --model neuphonic/neutts-air-q4-gguf

espeak-ng 为 NeuTTS 文本前端依赖（Windows 下一般随 neutts 自动处理）。
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def _write_wav(path: str, samples, sample_rate: int = 24000) -> None:
    """Write a WAV file from float32 samples (no soundfile dependency)."""
    import numpy as np
    if not isinstance(samples, np.ndarray):
        samples = np.array(samples, dtype=np.float32)
    pcm = (np.clip(samples.flatten(), -1.0, 1.0) * 32767).astype(np.int16)
    data_size = len(pcm) * 2  # 16-bit mono
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + data_size) + b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data" + struct.pack("<I", data_size) + pcm.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser(description="NeuTTS synthesis helper")
    parser.add_argument("--text", required=True, help="Text to synthesize")
    parser.add_argument("--out", required=True, help="Output WAV path")
    parser.add_argument("--ref-audio", required=True, help="Reference voice audio path")
    parser.add_argument("--ref-text", required=True, help="Reference voice transcript path")
    parser.add_argument("--model", default="neuphonic/neutts-air-q4-gguf",
                        help="HuggingFace backbone model repo")
    parser.add_argument("--device", default="cpu", help="Device (cpu/cuda)")
    args = parser.parse_args()

    ref_audio = Path(args.ref_audio).expanduser()
    ref_text_path = Path(args.ref_text).expanduser()
    if not ref_audio.exists() or str(args.ref_audio).strip() == "":
        print(
            "Error: reference audio not found; configure data/voice_config.json "
            "tts.neutts.ref_audio (a short recording of the voice to clone). "
            f"Looked at: {ref_audio}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not ref_text_path.exists() or str(args.ref_text).strip() == "":
        print(
            "Error: reference text not found; configure data/voice_config.json "
            "tts.neutts.ref_text (transcript of ref_audio). "
            f"Looked at: {ref_text_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    ref_text = ref_text_path.read_text(encoding="utf-8-sig").strip()
    try:
        from neutts import NeuTTS
    except ImportError:
        print("Error: neutts not installed. Run: pip install neutts", file=sys.stderr)
        sys.exit(1)

    # llama_cpp (backbone) offloads to GPU only for the literal string "gpu";
    # torch (codec) only accepts "cuda". A single --device value can't satisfy
    # both — "cuda" silently no-ops on the backbone, leaving it on CPU.
    tts = NeuTTS(
        backbone_repo=args.model,
        backbone_device="gpu" if args.device == "cuda" else args.device,
        codec_repo="neuphonic/neucodec",
        codec_device=args.device)
    wav = tts.infer(args.text, tts.encode_reference(str(ref_audio)), ref_text)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import soundfile as sf
        sf.write(str(out_path), wav, 24000)
    except ImportError:
        _write_wav(str(out_path), wav, 24000)
    print(f"OK: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
