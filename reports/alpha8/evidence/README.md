# Alpha.8 evidence archive

`alpha8-evidence.tar.zst` contains the raw host inventory, build logs and module metadata, rootless logs, loaded correctness/fault records, per-trial JSON and latency CSVs, orchestration manifests, independent lower-device counters, and bounded block traces. The binary module files are not included; their tested SHA-256 values and `modinfo` output are included. Rebuild from source commit `68dca6fcd2b322524555becfd54d475cdaf973e1` with the recorded host headers to reproduce those artifacts.

Verify the downloaded archive and report/scripts/fixtures with the adjacent `SHA256SUMS` using `sha256sum -c SHA256SUMS` from `reports/alpha8/`.
