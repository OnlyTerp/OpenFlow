import { spawnSync } from "node:child_process";

const configured = process.env.PYTHON ? [process.env.PYTHON] : [];
const candidates = [...configured, ...(process.platform === "win32"
  ? ["py", "python", "python3"]
  : ["python3", "python"])];

for (const executable of [...new Set(candidates)]) {
  const prefix = executable === "py" ? ["-3"] : [];
  const result = spawnSync(
    executable,
    [...prefix, "-m", "unittest", "discover", "-s", "tests", "-v"],
    { stdio: "inherit" },
  );
  if (result.error?.code === "ENOENT") continue;
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  process.exit(result.status ?? 1);
}

console.error("Python 3 was not found. Set PYTHON to its executable path.");
process.exit(1);
