# 核心数据结构

from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class NextAction:
    type: str            # ASK | READY | BLOCK
    question: Optional[str] = None
    message: Optional[str] = None
