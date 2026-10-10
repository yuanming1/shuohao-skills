#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const python = process.env.STORYBOARD_BLOCKING_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const test = fileURLToPath(new URL('./selftest.py', import.meta.url));
const result = spawnSync(python, ['-X', 'utf8', test], { stdio: 'inherit' });
if (result.error) {
  console.error(`无法启动 ${python}；可通过 STORYBOARD_BLOCKING_PYTHON 指定 Python 解释器。`);
}
process.exit(result.status ?? 3);
