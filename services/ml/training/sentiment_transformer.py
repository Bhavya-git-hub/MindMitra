"""A small transformer encoder for note sentiment, trained from scratch (needs the nlp group).

This is the transformer-based approach that could be evaluated here: a 2-layer encoder over a
word vocabulary built from the training sentences, with mean pooling and a linear classifier.
A pretrained model (for example a DistilBERT fine-tuned for sentiment) would normally do far
better on real notes, but its weights cannot be downloaded in this environment, and it would
add hundreds of megabytes and a GPU-friendly runtime to the service.
"""

import dataclasses
import re
from collections import Counter
from collections.abc import Sequence

import numpy as np
import torch
from torch import nn

MAX_LEN = 32
PAD, UNK = 0, 1
_TOKEN = re.compile(r"[a-z']+|[!?.:)(]")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class _Vocab:
    def __init__(self, texts: Sequence[str], min_count: int = 2) -> None:
        counts = Counter(t for s in texts for t in _tokens(s))
        self.index = {w: i + 2 for i, (w, c) in enumerate(counts.most_common()) if c >= min_count}

    def __len__(self) -> int:
        return len(self.index) + 2

    def encode(self, texts: Sequence[str]) -> torch.Tensor:
        out = torch.full((len(texts), MAX_LEN), PAD, dtype=torch.long)
        for row, s in enumerate(texts):
            ids = [self.index.get(t, UNK) for t in _tokens(s)][:MAX_LEN]
            if ids:
                out[row, : len(ids)] = torch.tensor(ids)
        return out


class _Encoder(nn.Module):
    def __init__(self, vocab: int, n_classes: int, d_model: int = 64) -> None:
        super().__init__()
        self.embed = nn.Embedding(vocab, d_model, padding_idx=PAD)
        self.position = nn.Embedding(MAX_LEN, d_model)
        layer = nn.TransformerEncoderLayer(
            d_model, nhead=4, dim_feedforward=128, dropout=0.1, batch_first=True
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=2, enable_nested_tensor=False)
        self.head = nn.Linear(d_model, n_classes)

    def forward(self, ids: torch.Tensor) -> torch.Tensor:
        pad = ids == PAD
        positions = torch.arange(ids.shape[1], device=ids.device).unsqueeze(0)
        h = self.encoder(self.embed(ids) + self.position(positions), src_key_padding_mask=pad)
        keep = (~pad).unsqueeze(-1).float()
        pooled = (h * keep).sum(1) / keep.sum(1).clamp(min=1.0)
        logits: torch.Tensor = self.head(pooled)
        return logits


@dataclasses.dataclass
class Scored:
    test_proba: np.ndarray
    extra_proba: np.ndarray
    parameters: int


def train_and_score(
    train_texts: Sequence[str],
    y_train: np.ndarray,
    test_texts: Sequence[str],
    extra_texts: Sequence[str],
    *,
    seed: int,
    epochs: int = 8,
) -> Scored:
    torch.manual_seed(seed)
    vocab = _Vocab(train_texts)
    model = _Encoder(len(vocab), int(y_train.max()) + 1)
    ids = vocab.encode(train_texts)
    labels = torch.tensor(y_train, dtype=torch.long)
    optimiser = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=0.01)
    loss_fn = nn.CrossEntropyLoss()
    generator = torch.Generator().manual_seed(seed)
    for _ in range(epochs):
        model.train()
        order = torch.randperm(len(labels), generator=generator)
        for start in range(0, len(order), 64):
            batch = order[start : start + 64]
            optimiser.zero_grad()
            loss = loss_fn(model(ids[batch]), labels[batch])
            loss.backward()
            optimiser.step()

    model.eval()
    with torch.no_grad():
        test = torch.softmax(model(vocab.encode(test_texts)), dim=1).numpy()
        extra = torch.softmax(model(vocab.encode(extra_texts)), dim=1).numpy()
    return Scored(test, extra, sum(p.numel() for p in model.parameters()))
