#!/usr/bin/env node
// novel-previz 自测薄壳:转调 python3 storyboard_to_shots.py selftest,保住仓库统一回路
// `for f in skills/*/scripts/selftest.mjs; do node "$f"; done`
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const target = path.join(here, "storyboard_to_shots.py");

const py = process.env.NOVEL_PREVIZ_PYTHON || "python3";
const r = spawnSync(py, ["-X", "utf8", target, "selftest", ...process.argv.slice(2)], { stdio: "inherit" });
if (r.error) {
  console.error(`✗ 找不到 ${py}(${r.error.message});可用环境变量 NOVEL_PREVIZ_PYTHON 指定解释器`);
  process.exit(3);
}
process.exit(r.status ?? 1);
