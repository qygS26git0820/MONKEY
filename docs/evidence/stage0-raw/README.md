# 阶段 0 原始证据（固化副本）

## 这是什么

阶段 0 环境审计的原始命令输出，共 20 个文件。`docs/env-report.md` 中每一处
`raw/NN` 引用都指向这里的同名文件。

## 从哪里来

- 原始位置：`runs/env-20260912-123911/raw/`
- 固化时间：2026-09-13
- 固化方式：**逐字节复制**，未做任何重新编码、未删改任何文件

## 为什么要有这份副本

`runs/` 被 `.gitignore` 覆盖。阶段 0 是整个项目的起点，它的证据如果只落在
`runs/` 下，换机器或清空 `runs/` 就会消失——而 `docs/env-report.md` 会留在
仓库里，指向一批不存在的文件。

因此：**阶段 0 的证据固化为版本控制内的副本；每次实验的轨迹仍属运行产物，
继续留在 `runs/` 下、不进 git。**

原始目录未被改动，仍保留在 `runs/env-20260912-123911/raw/`。

## 编码警告：这些文件不是 UTF-8

**没有做转码，这是刻意的**——转码会改变字节，证据就不再是原始字节了。

固化时我逐文件探测过编码，结果分三类：

- **按 UTF-8 解码失败、按 GBK 解码成功**：`01`、`05b`、`05c`、`05d`（4 个）。
  我只验证了"可被 GBK 解码"，**没有进一步区分 GBK 与 GB18030**。
- **UTF-8 与 GBK 都解不开**：`03`、`03b`、`04`。阶段 0 的记录说这是
  `wsl.exe` 的 **UTF-16LE** 输出（见 `docs/env-report.md`），
  但**本次固化时我没有逐文件确认其确切编码**，只知道它不是 UTF-8 也不是 GBK。
- **UTF-8**：其余 13 个。

直接 `cat` 非 UTF-8 的文件会看到乱码。按阶段 0 记录的办法转：

```bash
iconv -f GBK      -t UTF-8 docs/evidence/stage0-raw/01-host-os-disk.txt
iconv -f UTF-16LE -t UTF-8 docs/evidence/stage0-raw/03-wsl-status.txt
```

## 编号里有洞，这是事实不是遗漏

编号从 `04` 直接跳到 `05b`，`05` 与 `05a` 不存在。`05b`–`05e` 是注册表探测
**用错方法**的失败样本，`05f` 是改用 `.bat` + `chcp 65001` 后拿到可信结果的
那一次。这些失败样本被保留下来而不是删掉，是阶段 0 可信度论据的一部分。

`env-report.md` 里没有交代 `05`/`05a` 这两个编号，我也**不确定**它们是被清理了
还是本来就没生成。

## 校验：副本与原始逐字节一致

```bash
# 应无输出（无差异）
diff -r runs/env-20260912-123911/raw docs/evidence/stage0-raw --exclude=README.md
```

或按 sha256 逐条核对（本目录内执行 `sha256sum -c`）：

```
8907e8fef206881809d42e9a482e17edce378f528072b82250ace8d55f3d75a8  01-host-os-disk.txt
f81dbdea53331649d79586764f122832b2ca716ff5810deae4b3032c85f07c3b  02-host-tooling.txt
c67ff921dd101147d49648da699ae7a2594ac8d613c48ce6cd23bdc196aad259  03-wsl-status.txt
dc83b833294e745d277029d85f1c2c2c27a63d6e80da414bed77b29dbd0d42c5  03b-wsl-diagnose.txt
b770d58809b11ff4c9e2a00089f894ac3960deda73ce0de24324e60deda1df41  04-wsl-internals.txt
c7ae54eadee3ec841d596cf175a85c232cb72860aa5aad6073e20c2cac1c0091  05b-reg-longpaths-sparsevhd.txt
330aa1b0c756cab4d97b9f10c362648c2b4395a5be1d14c467070a555b0da81d  05c-reg-via-cmd.txt
8e1c0d296ff5e300e48161c6c935f5f9c1fd2abc703bf6d24010ae61a5232570  05d-reg-control.txt
690f4bfea3130a672cf092ec40701518610227f10955aec8f530e9eb1989982c  05e-reg-retry.txt
0b557eeb068a26c90a709b778bf7996e2b31b6a8126d82e1a246806a5cca0593  05f-reg-bat.txt
61ff76716f41aecb0f2dcd32e4121394b5063b5da3ab897f937cc7ae8de6f752  06-docker-host.txt
828e06a27df6189ce47797f63b4ed6ed3dcc806948d1f3f39eff47a0dea72f10  07-network.txt
bb11638fcefc58a4ec99ba7cfd61ee5622d88889804d538b754df07e409f3d2f  08-docker-config.txt
b54d55652bdbbcd2d36bfd761b5af3bff2c9453e7f652bfc2443b90558d2821f  09-registry-mirrors.txt
3f81be7be4c9738bc043cebcb2a6d159c91b12d751c254becae2b5affdde6f07  10-docker-pull.txt
952b6745c404b26d67febbdb193f224d93c01edfb6064fc6d927b05476f8d8e0  11-fs-benchmark.txt
7f895256a1f4ab27dc37b74fd02aa67596f09f373cd7897995db0d5b466f0c6e  12-k8s-kind-record.txt
d43c4471baa40739fb04a0c9822dbab43d224312d3a4dd16ec58008bd772dc1b  13-baseline-and-controls.txt
1889a90b04db7fc934a794f8ca0e961a1def0b031de29139a42a5969b9d269f6  14-outside-pollution-mtime.txt
1b7c4f8d5352296ddbcc3c163415784b50787184fea4b55567fd351a877f9eef  15-final-consistency.txt
```
