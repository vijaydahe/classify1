#!/usr/bin/env python3
"""Combine thin macOS Mach-O binaries into a single universal (fat) binary.

A stand-in for `lipo -create` so a universal macOS agent can be produced off a
non-mac build host. The fat format is a big-endian header + per-arch records,
followed by the thin binaries placed at aligned offsets.

  python3 make_universal.py out  agent-darwin-amd64 agent-darwin-arm64
"""
import struct
import sys

FAT_MAGIC = 0xCAFEBABE
# (cputype, cpusubtype) per architecture
ARCH = {
    "x86_64": (0x01000007, 0x00000003),
    "arm64":  (0x0100000C, 0x00000000),
}
ALIGN_POW = 14  # 2**14 = 16 KiB, the standard alignment for arm64 slices


def detect_arch(data: bytes) -> str:
    # Thin Mach-O 64-bit little-endian magic is 0xFEEDFACF; cputype follows.
    magic, cputype = struct.unpack_from("<II", data, 0)
    if magic != 0xFEEDFACF:
        raise SystemExit("not a 64-bit little-endian Mach-O")
    for name, (ct, _sub) in ARCH.items():
        if cputype == ct:
            return name
    raise SystemExit(f"unknown cputype {cputype:#x}")


def main() -> int:
    out, *inputs = sys.argv[1:]
    if len(inputs) < 2:
        raise SystemExit("need an output path and >=2 thin binaries")

    slices = []
    for path in inputs:
        with open(path, "rb") as f:
            data = f.read()
        slices.append((detect_arch(path_data := data), data))

    align = 1 << ALIGN_POW
    nfat = len(slices)
    # Header (8 bytes) + nfat * fat_arch (20 bytes each), then aligned payloads.
    offset = 8 + nfat * 20
    records, payloads = [], []
    for arch, data in slices:
        offset = (offset + align - 1) & ~(align - 1)
        cputype, cpusub = ARCH[arch]
        records.append(struct.pack(">IIIII", cputype, cpusub, offset, len(data), ALIGN_POW))
        payloads.append((offset, data))
        offset += len(data)

    with open(out, "wb") as f:
        f.write(struct.pack(">II", FAT_MAGIC, nfat))
        for r in records:
            f.write(r)
        for off, data in payloads:
            f.seek(off)
            f.write(data)

    print(f"wrote universal binary {out} ({len(slices)} archs, {offset} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
