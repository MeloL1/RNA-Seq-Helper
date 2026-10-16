from __future__ import annotations

import gzip
import shutil
import tarfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable


class ArchiveSafetyError(ValueError):
    pass


class ArchiveCancelled(RuntimeError):
    """用户在压缩包检查或展开期间主动取消。"""


@dataclass(frozen=True)
class ArchiveLimits:
    max_members: int = 10_000
    max_member_bytes: int = 1_000_000_000
    max_total_bytes: int = 2_000_000_000
    max_compression_ratio: float = 1_000.0
    max_path_depth: int = 12


@dataclass(frozen=True)
class ArchiveMember:
    name: str
    size: int
    compressed_size: int
    is_link: bool = False
    is_dir: bool = False


@dataclass(frozen=True)
class ArchiveManifest:
    source_path: Path
    archive_type: str
    members: tuple[ArchiveMember, ...]
    total_bytes: int
    safe: bool


class ArchiveService:
    """先检查清单，后安全展开；不调用 zip/tar 的不受限 extractall。"""

    def inspect(self, path: Path, limits: ArchiveLimits | None = None) -> ArchiveManifest:
        limits = limits or ArchiveLimits()
        path = path.expanduser().resolve()
        if not path.is_file():
            raise ArchiveSafetyError(f"找不到压缩文件：{path}")
        if zipfile.is_zipfile(path):
            return self._inspect_zip(path, limits)
        if tarfile.is_tarfile(path):
            return self._inspect_tar(path, limits)
        if path.name.lower().endswith(".gz"):
            return self._inspect_gzip(path, limits)
        raise ArchiveSafetyError("文件不是可识别的 zip/tar 压缩包")

    def extract(
        self,
        manifest: ArchiveManifest,
        target_dir: Path,
        *,
        progress: Callable[[int, int, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[Path, ...]:
        if not manifest.safe:
            raise ArchiveSafetyError("压缩包清单未通过安全检查，拒绝展开")
        target_dir = target_dir.expanduser().resolve()
        # 展开前检查目标卷剩余空间，避免在中途写满用户磁盘后留下半套项目。
        probe = target_dir
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        free_bytes = shutil.disk_usage(probe).free
        required_bytes = max(16 * 1024 * 1024, int(manifest.total_bytes * 1.10))
        if free_bytes < required_bytes:
            raise ArchiveSafetyError(
                f"目标磁盘剩余空间不足：至少需要约 {required_bytes / (1024 ** 2):.1f} MB"
            )
        target_dir.mkdir(parents=True, exist_ok=True)
        extracted: list[Path] = []
        if manifest.archive_type == "gzip":
            member = manifest.members[0]
            destination = self._safe_destination(target_dir, member.name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                with gzip.open(manifest.source_path, "rb") as source, destination.open("wb") as target:
                    self._copy_cancellable_bounded(source, target, member.size, cancelled)
            except (OSError, EOFError, zlib.error, ArchiveSafetyError) as exc:
                destination.unlink(missing_ok=True)
                raise ArchiveSafetyError(f"gzip 文件无法完整展开：{exc}") from exc
            extracted.append(destination)
            if progress:
                progress(1, 1, member.name)
        elif manifest.archive_type == "zip":
            with zipfile.ZipFile(manifest.source_path) as archive:
                for index, member in enumerate(manifest.members, start=1):
                    if cancelled and cancelled():
                        raise ArchiveCancelled("已取消压缩包展开")
                    destination = self._safe_destination(target_dir, member.name)
                    if member.is_dir:
                        destination.mkdir(parents=True, exist_ok=True)
                        if progress:
                            progress(index, len(manifest.members), member.name)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member.name) as source, destination.open("wb") as target:
                        self._copy_cancellable(source, target, cancelled)
                    extracted.append(destination)
                    if progress:
                        progress(index, len(manifest.members), member.name)
        else:
            with tarfile.open(manifest.source_path, mode="r:*") as archive:
                for index, member in enumerate(manifest.members, start=1):
                    if cancelled and cancelled():
                        raise ArchiveCancelled("已取消压缩包展开")
                    if member.is_link:
                        raise ArchiveSafetyError("压缩包含符号链接，拒绝展开")
                    destination = self._safe_destination(target_dir, member.name)
                    if member.is_dir:
                        destination.mkdir(parents=True, exist_ok=True)
                        if progress:
                            progress(index, len(manifest.members), member.name)
                        continue
                    source = archive.extractfile(member.name)
                    if source is None:
                        raise ArchiveSafetyError(f"无法读取压缩成员：{member.name}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with source, destination.open("wb") as target:
                        self._copy_cancellable(source, target, cancelled)
                    extracted.append(destination)
                    if progress:
                        progress(index, len(manifest.members), member.name)
        return tuple(extracted)

    def extract_recursive(
        self,
        manifest: ArchiveManifest,
        target_dir: Path,
        *,
        max_depth: int | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[Path, ...]:
        """安全地展开嵌套 zip/tar；每一层都重新检查清单和目标路径。"""
        depth_limit = max_depth if max_depth is not None else 4
        if depth_limit < 0:
            raise ArchiveSafetyError("压缩包递归层级上限无效")
        extracted = list(self.extract(manifest, target_dir, progress=progress, cancelled=cancelled))
        pending: list[tuple[Path, int]] = [
            (path, 1)
            for path in extracted
            if self._is_nested_container(path)
        ]
        while pending:
            if cancelled and cancelled():
                raise ArchiveCancelled("已取消压缩包展开")
            nested_path, depth = pending.pop(0)
            if depth > depth_limit:
                raise ArchiveSafetyError("嵌套压缩包层级超过安全上限")
            nested_manifest = self.inspect(nested_path)
            nested_dir = nested_path.parent / f".{nested_path.name}.expanded"
            nested_files = self.extract(
                nested_manifest, nested_dir, progress=progress, cancelled=cancelled,
            )
            extracted.extend(nested_files)
            pending.extend(
                (path, depth + 1)
                for path in nested_files
                if self._is_nested_container(path)
            )
        return tuple(extracted)

    @staticmethod
    def _copy_cancellable(source, target, cancelled: Callable[[], bool] | None) -> None:
        while True:
            if cancelled and cancelled():
                raise ArchiveCancelled("已取消压缩包展开")
            block = source.read(1024 * 1024)
            if not block:
                return
            target.write(block)

    @staticmethod
    def _copy_cancellable_bounded(source, target, expected_size: int, cancelled: Callable[[], bool] | None) -> None:
        copied = 0
        while True:
            if cancelled and cancelled():
                raise ArchiveCancelled("已取消 gzip 展开")
            block = source.read(1024 * 1024)
            if not block:
                break
            copied += len(block)
            if copied > expected_size:
                raise ArchiveSafetyError("gzip 展开内容超过已检查的大小")
            target.write(block)
        if copied != expected_size:
            raise ArchiveSafetyError("gzip 展开内容与已检查的大小不一致")

    @staticmethod
    def _is_nested_container(path: Path) -> bool:
        """gzip 文本（例如 GEO .txt.gz）不是 tar 容器，不再误当作嵌套包。"""
        if not path.is_file() or path.suffix.lower() not in {".zip", ".tar", ".gz", ".tgz"}:
            return False
        return zipfile.is_zipfile(path) or tarfile.is_tarfile(path)

    @staticmethod
    def _inspect_zip(path: Path, limits: ArchiveLimits) -> ArchiveManifest:
        members: list[ArchiveMember] = []
        total = 0
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_members:
                raise ArchiveSafetyError("压缩包成员数量超过安全上限")
            for info in infos:
                name = info.filename
                ArchiveService._validate_name(name, limits)
                compressed = max(1, info.compress_size)
                if info.file_size > limits.max_member_bytes:
                    raise ArchiveSafetyError(f"压缩成员过大：{name}")
                if info.file_size / compressed > limits.max_compression_ratio:
                    raise ArchiveSafetyError(f"压缩比异常，疑似压缩炸弹：{name}")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ArchiveSafetyError(f"压缩包包含符号链接：{name}")
                total += info.file_size
                if total > limits.max_total_bytes:
                    raise ArchiveSafetyError("压缩包展开总大小超过安全上限")
                members.append(ArchiveMember(name, info.file_size, info.compress_size, is_dir=info.is_dir()))
        return ArchiveManifest(path, "zip", tuple(members), total, True)

    @staticmethod
    def _inspect_tar(path: Path, limits: ArchiveLimits) -> ArchiveManifest:
        members: list[ArchiveMember] = []
        total = 0
        archive_bytes = max(1, path.stat().st_size)
        with tarfile.open(path, mode="r:*") as archive:
            infos = archive.getmembers()
            if len(infos) > limits.max_members:
                raise ArchiveSafetyError("压缩包成员数量超过安全上限")
            for info in infos:
                ArchiveService._validate_name(info.name, limits)
                is_link = info.issym() or info.islnk()
                if is_link:
                    raise ArchiveSafetyError(f"压缩包包含符号链接：{info.name}")
                if not (info.isdir() or info.isfile()):
                    raise ArchiveSafetyError(f"压缩包包含非普通文件成员：{info.name}")
                if info.size > limits.max_member_bytes:
                    raise ArchiveSafetyError(f"压缩成员过大：{info.name}")
                total += info.size
                if total > limits.max_total_bytes:
                    raise ArchiveSafetyError("压缩包展开总大小超过安全上限")
                if total / archive_bytes > limits.max_compression_ratio:
                    raise ArchiveSafetyError("压缩包整体压缩比异常，疑似压缩炸弹")
                members.append(ArchiveMember(info.name, info.size, info.size, False, info.isdir()))
        return ArchiveManifest(path, "tar", tuple(members), total, True)

    @staticmethod
    def _inspect_gzip(path: Path, limits: ArchiveLimits) -> ArchiveManifest:
        compressed_size = max(1, path.stat().st_size)
        member_name = path.name[:-3]
        if not member_name.strip():
            raise ArchiveSafetyError("gzip 文件名缺少解压后的文件名")
        ArchiveService._validate_name(member_name, limits)
        total = 0
        try:
            with gzip.open(path, "rb") as source:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > limits.max_member_bytes:
                        raise ArchiveSafetyError(f"gzip 展开文件过大：{member_name}")
                    if total > limits.max_total_bytes:
                        raise ArchiveSafetyError("压缩包展开总大小超过安全上限")
                    if total / compressed_size > limits.max_compression_ratio:
                        raise ArchiveSafetyError("压缩比异常，疑似压缩炸弹")
        except ArchiveSafetyError:
            raise
        except (OSError, EOFError, zlib.error) as exc:
            raise ArchiveSafetyError(f"gzip 文件损坏或无法读取：{exc}") from exc
        member = ArchiveMember(member_name, total, path.stat().st_size)
        return ArchiveManifest(path, "gzip", (member,), total, True)

    @staticmethod
    def _validate_name(name: str, limits: ArchiveLimits) -> None:
        pure = PurePosixPath(name)
        if pure.is_absolute() or name.startswith("/") or "\\" in name:
            raise ArchiveSafetyError(f"压缩成员路径不安全：{name}")
        if any(part in {"", ".", ".."} for part in pure.parts):
            raise ArchiveSafetyError(f"压缩成员可能逃逸目标目录：{name}")
        if len(pure.parts) > limits.max_path_depth:
            raise ArchiveSafetyError(f"压缩成员路径层级过深：{name}")

    @staticmethod
    def _safe_destination(target_dir: Path, name: str) -> Path:
        destination = (target_dir / name).resolve()
        if destination != target_dir and target_dir not in destination.parents:
            raise ArchiveSafetyError(f"展开路径逃逸目标目录：{name}")
        return destination
