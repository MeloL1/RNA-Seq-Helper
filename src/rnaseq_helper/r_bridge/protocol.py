from __future__ import annotations

import json
from typing import Any, Mapping

from rnaseq_helper.domain.models import RJobRequest, RJobResponse


def encode_request(request: RJobRequest) -> str:
    """将一个请求编码为单行 JSON；禁止 NaN/Infinity 穿过协议。"""

    return json.dumps(request.as_dict(), ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def decode_response(line: str) -> RJobResponse:
    try:
        value: Mapping[str, Any] = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"R worker 返回了无效 JSON：{exc.msg}") from exc
    return RJobResponse.from_dict(value)
