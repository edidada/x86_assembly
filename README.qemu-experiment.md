# QEMU 引导实验（experiment/qemu-boot 分支）

这个分支用 **GitHub Actions + QEMU** 把仓库里的 MBR 汇编代码「真正引导」起来，
而不是只做语法汇编检查。实验分支独立于 `master`，不影响 `master` 上稳定的
`build.yml`（NASM 3.01 汇编校验）。

## 为什么用 QEMU 而不是 VirtualBox

GitHub 托管的 runner 跑在 Azure 虚拟机里，**不暴露 VT-x/AMD-V**。VirtualBox
能安装，但启动虚拟机时会报 `VERR_VMX_NO_VMX`。macOS runner 虽然支持嵌套虚拟化，
但多为 Apple Silicon，其 VirtualBox 只能运行 ARM 客户机，跑不了这里的 x86 代码。
QEMU 的纯软件模拟（TCG）不需要硬件虚拟化，能在这个环境里真正引导 16 位 MBR。

## 怎么验证「真的跑起来了」

MBR 把结果写进 VGA 文本模式显存（物理地址 `0xB8000`）。工作流通过 QEMU 的
QMP 监控接口执行 `xp/1024xb 0xb8000` 读取这段显存，取偶数偏移的字符字节解码成文本，
再检查是否出现预期字符串。同时用 `screendump` 抓屏，作为 artifact 上传。

| case | 源文件 | 预期 | 结果 |
|------|--------|------|------|
| c05 | `c05/c05_mbr.asm` | 不应出现 `Label offset` | ✓ 负向对照（教材早期版本，SeaBIOS 判为不可引导） |
| c06 | `c06/c06_mbr.asm` | 出现 `Label offset` | ✓ 引导成功 |
| c07 | `c07/c07_mbr.asm` | 出现 `5050` | ✓ 引导成功（`1+2+3+...+100=5050`） |

## c05 为什么是负向对照

`c05_mbr.asm` 是教材第 5 章的早期手写版本：逐字节写显存、`mov ax,number`
没有 `org 0x7c00` 偏移、开头也没有跳转指令。SeaBIOS 拒绝引导它并报
`not a bootable disk`。这是这份教学代码本身的缺陷，不是实验工具的问题，
所以没有篡改原始源码，而是把它作为「早期版本引导失败」的对照如实记录。
`c06` 正是这一章的修正版。

## 本地复现

需要 Linux（或 WSL）/macOS，安装 `qemu-system-i386`、`nasm`：

```bash
nasm -f bin c07/c07_mbr.asm -o c07_mbr.bin
dd if=/dev/zero of=disk.img bs=1M count=1
dd if=c07_mbr.bin of=disk.img conv=notrunc
python3 scripts/verify_boot.py --image disk.img --expect "5050" --screenshot screen.ppm
```

成功时输出 `OK: found '5050' in guest VGA output`，并生成 `screen.ppm` 截图。

## 工作流文件

- `.github/workflows/qemu-boot.yml` — CI 定义（push 到本分支或手动触发）
- `scripts/verify_boot.py` — QEMU/QMP 引导与显存校验脚本
- 每次运行的截图与 `.bin` 在对应 `boot-cXX` artifact 中
