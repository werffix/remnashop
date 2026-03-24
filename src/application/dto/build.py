from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True, kw_only=True)
class BuildInfoDto:
    has_build: Optional[bool] = field(default=None)
    time: Optional[str] = field(default=None)
    branch: Optional[str] = field(default=None)
    tag: Optional[str] = field(default=None)
    commit_url: Optional[str] = field(default=None)
    commit: Optional[str] = field(default=None)
