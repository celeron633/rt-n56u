# 在 WSL 下编译 Padavan

本文以 HC5761 为例。默认精简配置保留双频 Wi-Fi、有线网络、IPv6 和中文 Web 管理，
关闭可选工具、SSH/FTP 服务、USB/SD 及多媒体功能。已验证的环境是 WSL 下的 Debian 13、项目预编译的
MIPS GCC 7.4.0 工具链和 GNU Make 4.3。已验证通过 `build_firmware_tmp HC5761`
在临时源码副本中完成整包构建；构建产物和日志均保存在源码仓库外。HC5761 尚未实机验证。

## 1. 准备源码和系统依赖

以下命令在 WSL 的 Linux 终端执行。建议将源码放在 Linux 文件系统中，例如
`~/rt-n56u`，避免在 `/mnt/c` 等 Windows 挂载目录中编译。
本文假定项目已克隆到 `~/rt-n56u`；如果路径不同，请调整命令。

```sh
sudo apt-get update
sudo apt-get install -y \
  unzip libtool-bin curl cmake gperf gawk flex bison fakeroot kmod cpio \
  git python3-docutils gettext automake autopoint texinfo build-essential \
  help2man pkg-config zlib1g-dev libgmp-dev libmpc-dev libmpfr-dev \
  libncurses-dev libltdl-dev wget libc-dev-bin xz-utils
```

sudo 密码只在终端提示时输入，不要写入脚本或日志。

## 2. 下载交叉工具链

使用仓库自带的下载脚本，它会下载 `hanwckf/padavan-toolchain` 的 v1.1 发布包，
并解压到 `toolchain-mipsel/toolchain-3.4.x/`：

```sh
cd ~/rt-n56u/toolchain-mipsel
sh dl_toolchain.sh
./toolchain-3.4.x/bin/mipsel-linux-uclibc-gcc --version
```

最后一条命令应显示 GCC 7.4.0。`trunk/toolchain.inc` 已指向此目录，无需修改。
脚本在目标目录存在时会直接退出；如果下载或解压中断，先检查该目录是否完整，
不要把目录存在当作工具链安装成功。

## 3. 准备 GNU Make 4.3

本次构建中，Debian 13 的 GNU Make 4.4.1 在 `make dep` 阶段出现长时间反复执行
变量展开命令的现象，换用 4.3 后正常。项目包含 `.EXPORT_ALL_VARIABLES` 和
`$(shell ...)` 变量，为复现已验证环境，建议本地安装 Make 4.3。

```sh
make_build_dir=$(mktemp -d /tmp/padavan-make.XXXXXX)
cd "$make_build_dir"
curl -fL --retry 3 -o make-4.3.tar.gz \
  https://ftp.gnu.org/gnu/make/make-4.3.tar.gz
tar -xf make-4.3.tar.gz
cd make-4.3
./configure --prefix="$HOME/.local/padavan"
make -j"$(nproc)"
make install
"$HOME/.local/padavan/bin/make" --version
```

这不会替换系统的 `/usr/bin/make`。后面的构建命令通过 PATH 选择本地版本；
如果该位置已经安装了 Make 4.3，可跳过安装步骤。

## 4. 在临时副本中构建（推荐）

HC5761 的配置入口仍是 `trunk/configs/templates/HC5761.config` 和
`trunk/configs/boards/HC5761/`。在源码仓库中修改它们，然后运行：

```sh
cd ~/rt-n56u/trunk
sudo env PATH="$HOME/.local/padavan/bin:$PATH" LC_ALL=C \
  ./build_firmware_tmp HC5761
```

脚本会在 `/tmp` 下创建唯一目录，例如 `/tmp/padavan-HC5761.ABC123/`，复制 Git
跟踪的源码文件当前内容，然后在副本中调用原有构建脚本。它不会复制整个 `.git`，
也不会复制源码树中已有的编译产物。工具链通过符号链接复用，不重复下载。

- 已跟踪文件的未提交修改也会参与构建。
- 新增配置或源码文件必须先 `git add`；未跟踪、被忽略的文件不会进入副本。
- 暂存后仍未提交的新文件可以构建；脚本读取工作区内容，不是暂存区内容。
- 源码和构建目录路径不能含空格等空白字符，旧 Makefile 不支持这种路径。
- 每次构建都是全新副本，不复用上次的目标文件，需要额外磁盘空间和完整编译时间。

需要把构建放到持久目录时，可指定第二个参数；目录必须已存在并位于源码仓库外：

```sh
mkdir -p "$HOME/padavan-builds"
cd ~/rt-n56u/trunk
sudo env PATH="$HOME/.local/padavan/bin:$PATH" LC_ALL=C \
  ./build_firmware_tmp HC5761 "$HOME/padavan-builds"
```

本次 WSL 环境中 `fakeroot-tcp` 曾报 `libfakeroot: connect: Permission denied`，
因此使用 sudo 构建。构建结束后，副本中的文件会归还给调用 sudo 的用户；
共享工具链的所有者不会改变。

## 5. 查找和检查固件

脚本结束时打印构建目录、日志及固件位置。所有生成内容都留在副本中：

| 内容 | 相对于构建目录的路径 |
| --- | --- |
| 完整日志 | `build.log` |
| 源仓库提交号 | `source-revision.txt` |
| 固件 | `trunk/images/*.trx` |
| 实际功能配置 | `trunk/.config` |
| 实际内核配置 | `trunk/linux-3.4.x/.config` |
| 驱动、依赖解压、目标文件 | `trunk/` 下对应组件目录 |

将下面的示例目录替换成脚本实际输出的目录：

```sh
build_dir=/tmp/padavan-HC5761.ABC123
cd "$build_dir/trunk"
ls -lh images/HC5761_*.trx
./tools/mkimage/mkimage -l images/HC5761_3.4.3.9-099.trx
./tools/mksquashfs_xz/unsquashfs -s images/ramdisk
cd images
sha256sum HC5761_3.4.3.9-099.trx
```

文件名由项目版本号决定。镜像信息应显示 `Product ID: HC5761`、MIPS 架构和 LZMA
压缩。HC5761 镜像最大长度为 `0xef0000` 字节，包含 64 字节头；打包时会检查此限制。
固件大小取决于功能配置，构建时间也会影响 SHA256。

`source-revision.txt` 记录基础提交号，不代表未提交修改；需要可复现的源码记录时，
应先提交修改。失败的副本也会保留，便于查看日志。脚本会报告非零退出码，内核准备
失败后会停止，不继续打包。

编译通过不等于完成硬件验证。首次刷入前请阅读
[HC5761 分区及验证说明](hc5761.md)，备份完整闪存，使用支持对应 Padavan 布局的引导器。
不要直接作为原厂升级包或 OpenWrt sysupgrade 包使用。

## 6. 再次构建与清理

修改配置后再次运行 `build_firmware_tmp` 即可；切换机型只需更换第一个参数。
每次都会分配新目录，无需在源码仓库里执行 `clear_tree`。

`/tmp` 可能在系统维护或重启时被清理。需要保留的固件和日志请复制到持久目录，
或者从一开始指定 `$HOME/padavan-builds`。构建脚本不会自动删除任何已有构建目录；
不再需要某个副本时，确认保存好产物后删除该副本即可。

## 7. 旧的原地构建入口

`build_firmware_modify` 仍然可用，但它会在当前源码树中解压依赖、复制驱动、改写
已跟踪的生成文件，并留下目标文件。若选择此入口，仍须自行处理 `git status` 中的
生成文件；`.gitignore` 无法忽略已跟踪文件的改动。

推荐入口通过完整隔离构建副本避免这些问题，因此仓库不再维护数百条按组件列举的
忽略规则，也不使用 `.git/info/exclude`。新增代码和板级配置仍会正常出现在 Git 状态中。
