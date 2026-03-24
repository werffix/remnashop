from asyncio import Protocol
from types import TracebackType
from typing import Optional, Self, Type


class UnitOfWork(Protocol):
    async def __aenter__(self) -> Self: ...  # type: ignore[empty-body]

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
