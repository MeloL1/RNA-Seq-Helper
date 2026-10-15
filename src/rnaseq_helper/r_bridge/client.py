from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from rnaseq_helper.domain.models import JobContext, RJobRequest, RJobResponse
from rnaseq_helper.services.runtime_paths import resolve_rscript
from .protocol import decode_response, encode_request


class RBridgeError(RuntimeError):
    pass


class RBridgeClient:
    """一次请求一个独立 Rscript 进程，隔离 R 状态和崩溃。"""

    def __init__(self, worker_path: Path | None = None, rscript: str = "Rscript") -> None:
        if worker_path:
            self.worker_path = worker_path
        else:
            candidates = [
                Path(__file__).parents[3] / "resources" / "r" / "worker.R",
                Path(sys.executable).parent.parent / "Resources" / "resources" / "r" / "worker.R",
            ]
            self.worker_path = next((path for path in candidates if path.exists()), candidates[0])
        self.rscript = resolve_rscript(rscript)

    def submit(self, request: RJobRequest, context: JobContext) -> RJobResponse:
        if context.cancelled():
            raise RBridgeError("任务在提交前已取消")
        if not self.worker_path.exists():
            raise RBridgeError(f"找不到 R worker：{self.worker_path}")
        command = [self.rscript, "--vanilla", str(self.worker_path)]
        env = os.environ.copy()
        # 内置 runtime 必须只加载 app 内的已验证库，避免被用户机器上的
        # 同名 R 包覆盖；普通开发环境仍保留用户库的兼容性。
        if "/Contents/Frameworks/R.framework/" in self.rscript:
            env["R_LIBS_USER"] = ""
        else:
            env.setdefault("R_LIBS_USER", str(Path.home() / "Library" / "R" / "library"))
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
                cwd=context.workdir,
            )
        except OSError as exc:
            raise RBridgeError(f"无法启动 R worker：{exc}") from exc
        try:
            assert process.stdin is not None
            process.stdin.write(encode_request(request) + "\n")
            process.stdin.close()
            context.emit("r_worker", None, "正在等待独立 R worker 返回")
            started = time.monotonic()
            last_progress_second = 0
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    if context.cancelled():
                        process.kill()
                        process.communicate()
                        raise RBridgeError("任务已取消")
                    elapsed = int(time.monotonic() - started)
                    if elapsed >= 2 and elapsed // 2 > last_progress_second:
                        last_progress_second = elapsed // 2
                        context.emit(
                            "r_worker",
                            None,
                            f"正在等待独立 R worker 返回（已等待 {elapsed} 秒）",
                        )
                    if elapsed > context.timeout_seconds:
                        process.kill()
                        stdout, stderr = process.communicate()
                        raise RBridgeError(
                            f"R worker 超时（超过 {context.timeout_seconds} 秒），已终止本次任务"
                        )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if context.cancelled():
            raise RBridgeError("任务已取消")
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        if not lines:
            detail = stderr.strip() or f"退出码 {process.returncode}"
            raise RBridgeError(f"R worker 没有返回结果：{detail}")
        try:
            response = decode_response(lines[-1])
        except ValueError as exc:
            raise RBridgeError(f"R worker 协议错误：{exc}；stderr：{stderr.strip()}") from exc
        if response.request_id != request.request_id:
            raise RBridgeError("R worker 返回的请求 ID 不匹配")
        if not response.ok:
            raise RBridgeError(json.dumps(response.error or {}, ensure_ascii=False))
        return response

    def run(self, method: str, payload: dict[str, Any], context: JobContext, profile_id: str = "stage0-micro-v1") -> RJobResponse:
        """便捷构造请求；底层 submit 仍保持规划中的 request 契约。"""

        return self.submit(RJobRequest(str(uuid4()), method, payload, profile_id), context)
