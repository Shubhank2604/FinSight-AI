"""Pinned MiniLM inference on CPU, with complete token-window coverage."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
DIMENSIONS = 384
MAX_TOKENS = 256
POOLING = 'token-window-weighted-mean-v1'


class MiniLMEncoder:
    def __init__(self, cache_dir: str):
        from huggingface_hub import snapshot_download
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = dict(repo_id=MODEL, revision=REVISION, cache_dir=cache_dir,
                       allow_patterns=['onnx/model.onnx', 'tokenizer.json'], token=False)
        try:
            # Once installed, normal startup and inference need no network.
            directory = snapshot_download(**options, local_files_only=True)
            if not (Path(directory) / 'onnx/model.onnx').is_file():
                raise FileNotFoundError('Model is not cached')
        except (OSError, ValueError):
            directory = snapshot_download(**options)
        self.tokenizer = Tokenizer.from_file(str(Path(directory) / 'tokenizer.json'))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.cls = self.tokenizer.token_to_id('[CLS]')
        self.sep = self.tokenizer.token_to_id('[SEP]')
        self.pad = self.tokenizer.token_to_id('[PAD]')
        if any(value is None for value in (self.cls, self.sep, self.pad)):
            raise ValueError('MiniLM tokenizer lacks required special tokens')
        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = 4
        session_options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(Path(directory) / 'onnx/model.onnx'),
                                           sess_options=session_options,
                                           providers=['CPUExecutionProvider'])
        self.input_names = {item.name for item in self.session.get_inputs()}

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        windows, owners, weights = [], [], []
        for owner, text in enumerate(texts):
            ids = self.tokenizer.encode(text, add_special_tokens=False).ids
            for start in range(0, max(len(ids), 1), MAX_TOKENS - 2):
                window = ids[start:start + MAX_TOKENS - 2]
                windows.append([self.cls, *window, self.sep])
                owners.append(owner)
                weights.append(max(len(window), 1))
        accumulators = np.zeros((len(texts), DIMENSIONS), dtype=np.float64)
        for start in range(0, len(windows), 16):
            batch = windows[start:start + 16]
            width = max(map(len, batch))
            input_ids = np.full((len(batch), width), self.pad, dtype=np.int64)
            attention = np.zeros_like(input_ids)
            for row, ids in enumerate(batch):
                input_ids[row, :len(ids)] = ids
                attention[row, :len(ids)] = 1
            inputs = {'input_ids': input_ids, 'attention_mask': attention,
                      'token_type_ids': np.zeros_like(input_ids)}
            token_vectors = self.session.run(None, {k: v for k, v in inputs.items()
                                                   if k in self.input_names})[0]
            mask = attention[..., None]
            pooled = (token_vectors * mask).sum(axis=1) / mask.sum(axis=1)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            pooled = pooled / np.maximum(norms, 1e-12)
            for index, vector in enumerate(pooled, start=start):
                accumulators[owners[index]] += vector * weights[index]
        norms = np.linalg.norm(accumulators, axis=1, keepdims=True)
        if (accumulators.shape[1] != DIMENSIONS or not np.isfinite(accumulators).all()
                or (norms <= 0).any()):
            raise ValueError('MiniLM returned invalid vectors')
        return (accumulators / norms).tolist()


@lru_cache(maxsize=2)
def load_encoder(cache_dir: str) -> MiniLMEncoder:
    return MiniLMEncoder(cache_dir)
