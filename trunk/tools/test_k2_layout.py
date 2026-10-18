#!/usr/bin/env python3
"""Check K2 partition boundaries and exercise the real image packing recipe."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


TRUNK = Path(__file__).resolve().parents[1]
BOARDS = TRUNK / "configs/boards"
MAP = TRUNK / "linux-3.4.x/drivers/mtd/ralink/ralink-flash-map.h"


def config(path):
    return dict(re.findall(r"^(CONFIG_\w+)=(.*)$", path.read_text(), re.M))


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)


class K2Layout(unittest.TestCase):
    def test_partitions(self):
        # Compile the production map, including recalc_partitions(), for both
        # rootfs modes. Preserve the MTD numbers used by existing consumers.
        with tempfile.TemporaryDirectory(prefix="k2-map-") as tmp:
            tmp = Path(tmp)
            for product, start in (("PSG1218", 0x50000),
                                   ("K2-v22.4", 0x50000),
                                   ("K2-v22.5", 0xA0000),
                                   ("HC5761", 0x50000)):
                for ram in (False, True):
                    with self.subTest(product=product, ram=ram):
                        cfg = config(BOARDS / product / "kernel-3.4.x.config")
                        if ram:
                            cfg.pop("CONFIG_RT2880_ROOTFS_IN_FLASH", None)
                        defines = "\n".join(
                            f"#define {key} {1 if value == 'y' else value}"
                            for key, value in cfg.items()
                            if key.startswith(("CONFIG_MTD_", "CONFIG_RT2880_",
                                               "CONFIG_ROOTFS_IN_FLASH_"))
                        )
                        source = tmp / "map.c"
                        source.write_text(defines + r'''
#include <stdint.h>
#include <stdio.h>
#define MTDPART_OFS_APPEND ((uint64_t)-1)
#define MTD_WRITEABLE 0x400
struct mtd_partition {
    const char *name;
    uint64_t size, offset;
    unsigned int mask_flags;
};
''' + f'#include "{MAP}"\n' + r'''
int main(int argc, char **argv) {
    unsigned int i;
    uint64_t end = 0;
    recalc_partitions(argc > 1 ? 0x1000000 : 0x800000, 0x180000);
    for (i = 0; i < sizeof(rt2880_partitions)/sizeof(rt2880_partitions[0]); i++) {
        struct mtd_partition *p = &rt2880_partitions[i];
        uint64_t offset = p->offset == MTDPART_OFS_APPEND ? end : p->offset;
        printf("%s %llu %llu %u\n", p->name,
               (unsigned long long)offset, (unsigned long long)p->size, p->mask_flags);
        end = offset + p->size;
    }
    return 0;
}
''')
                        binary = tmp / "map"
                        run(os.environ.get("CC", "cc"), "-std=gnu89", "-Werror",
                            str(source), "-o", str(binary))
                        args = (str(binary), "16M") if product == "HC5761" else (str(binary),)
                        rows = [line.split() for line in run(*args).stdout.splitlines()]
                        parts = {row[0]: tuple(map(int, row[1:])) for row in rows}
                        end = 0xFC0000 if product == "HC5761" else 0x800000
                        storage = int(cfg["CONFIG_MTD_STORE_PART_SIZ"], 0)
                        self.assertEqual(parts["Factory"][:2], (0x40000, 0x10000))
                        self.assertEqual(parts["Kernel"][0], start)
                        self.assertEqual(rows[3][0], "Kernel")
                        self.assertEqual(rows[4 if ram else 5][0], "Storage")
                        self.assertEqual(rows[5 if ram else 6][0], "Firmware_Stub")
                        self.assertEqual(parts["Storage"][:2], (end - storage, storage))
                        stub_end = end - storage if end > 0x800000 else end
                        self.assertEqual(parts["Firmware_Stub"][:2], (start, stub_end - start))
                        if not ram:
                            self.assertEqual(parts["RootFS"][0], start + parts["Kernel"][1])
                            self.assertEqual(sum(parts[p][1] for p in ("Kernel", "RootFS")),
                                             end - storage - start)
                        if product == "K2-v22.5":
                            self.assertEqual(parts["permanent_config"], (0x50000, 0x50000, 0x400))
                        else:
                            self.assertNotIn("permanent_config", parts)

    def test_templates(self):
        for rev in ("22.4", "22.5"):
            product = f"K2-v{rev}"
            board = BOARDS / product
            for suffix in ("", "_nano"):
                cfg = config(TRUNK / f"configs/templates/{product}{suffix}.config")
                self.assertEqual(cfg["CONFIG_FIRMWARE_PRODUCT_ID"], f'"{product}"')
            self.assertIn(f'"{product}"', (board / "board.h").read_text())
            self.assertIn("-DBOARD_PSG1218", (board / "board.mk").read_text())

    def test_image_size_limit(self):
        # Use the actual mkimage and vendor recipe with synthetic kernel/rootfs
        # data. The exact maximum must pack; the next aligned size must fail.
        with tempfile.TemporaryDirectory(prefix="k2-image-") as tmp:
            tmp = Path(tmp)
            mkimage = TRUNK / "tools/mkimage"
            run(os.environ.get("CC", "cc"), "-DUSE_HOSTCC", "-idirafter",
                str(mkimage / "include"), str(mkimage / "mkimage.c"),
                str(mkimage / "crc32.c"), "-o", str(tmp / "mkimage"))
            product = "K2-v22.5"
            kernel_dir = tmp / "merge" / product
            kernel_dir.mkdir(parents=True)
            (kernel_dir / "kernel.bin").write_bytes(bytes(192))
            images = tmp / "images"
            images.mkdir()
            cfg = config(BOARDS / product / "kernel-3.4.x.config")
            variables = cfg.copy()
            variables.update({
                "ROOTDIR": str(TRUNK), "IMAGEDIR": str(images),
                "MERGE_DIR": str(tmp / "merge"), "MKIMAGE_DIR": str(tmp),
                "CONFIG_FIRMWARE_PRODUCT_ID": product,
                "CONFIG_WITHOUT_KERNEL": "y", "ENTRY_CMD": "echo 0x80000000",
                "FIRMWARE_KERNEL_VER": "3.4", "FIRMWARE_ROOTFS_VER": "3.9",
                "FIRMWARE_BUILDS_VER": "test",
            })
            command = ["make", "--no-print-directory", "-f",
                       str(TRUNK / "vendors/Ralink/Makefile"), "image"]
            command += [f"{key}={value}" for key, value in variables.items()]
            for excess in (0, 16):
                with self.subTest(excess=excess):
                    with (images / "ramdisk").open("wb") as rootfs:
                        rootfs.truncate(0x6E0000 - 256 + excess)
                    image = images / f"{product}_3.4.3.9-test.trx"
                    image.unlink(missing_ok=True)
                    result = subprocess.run(command, text=True, capture_output=True)
                    if excess:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("permanent_config and Storage reserved", result.stdout)
                        self.assertFalse(image.exists())
                    else:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(image.stat().st_size, 0x6E0000)
                        self.assertEqual(image.read_bytes()[36:36 + len(product)], product.encode())


if __name__ == "__main__":
    unittest.main()
