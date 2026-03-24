from collections.abc import Iterable, Iterator
from typing import List, TypeVar

from src.core.constants import BATCH_SIZE_20

T = TypeVar("T")


def chunked(iterable: Iterable[T], size: int = BATCH_SIZE_20) -> Iterator[List[T]]:
    if size <= 0:
        raise ValueError("Chunk size must be greater than zero")

    chunk: List[T] = []

    for item in iterable:
        chunk.append(item)

        if len(chunk) == size:
            yield chunk
            chunk = []

    if chunk:
        yield chunk
