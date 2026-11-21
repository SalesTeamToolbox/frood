#!/usr/bin/env node
// Validate all orchestrator config files for platform-correct paths
// Run before commit/CI to catch Windows paths on Linux and vice versa

import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const isWindows = process.platform === "win32";
const windowsDriveRe = /^[A-Za-z]:[\\/]/;
const windowsPathRe = /\\/;
const linuxPathRe = /^\//;

function checkFile(file, content) {
  const errors = [];
  const lines = content.split(/\r?\n/);

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineNum = i + 1;

    if (isWindows) {
      // On Windows: flag Linux absolute paths
      if (linuxPathRe.test(line) && !line.startsWith("/mnt/") && !line.startsWith("/home/")) {
        errors.push({ file, line: lineNum, issue: "Linux-style absolute path on Windows", content: line.trim() });
      }
    } else {
      // On Linux/macOS: flag Windows drive letters and backslashes
      if (windowsDriveRe.test(line)) {
        errors.push({ file, line: lineNum, issue: "Windows drive letter path on Linux", content: line.trim() });
      }
      if (windowsPathRe.test(line) && !line.includes("node_modules") && !line.includes("\\\\")) {
        // Allow escaped backslashes in JSON, but flag raw Windows paths
        if (!/\\\\/.test(line) && /[A-Za-z]:\\/.test(line)) {
          errors.push({ file, line: lineNum, issue: "Windows backslash path on Linux", content: line.trim() });
        }
      }
    }
  }

  return errors;
}

function validate() {
  const configFiles = [
    ".mcp.json",
    ".claude/settings.local.json",
    ".opencode/opencode.json",
    "package.json",
    "pyproject.toml",
  ];

  let allErrors = [];

  for (const file of configFiles) {
    const fullPath = path.join(process.cwd(), file);
    if (fs.existsSync(fullPath)) {
      try {
        const content = fs.readFileSync(fullPath, "utf8");
        const errors = checkFile(file, content);
        allErrors.push(...errors);
      } catch (e) {
        console.error(`Error reading ${file}: ${e.message}`);
      }
    }
  }

  // Also check installed config directories
  const configDirs = [
    path.join(os.homedir(), ".config", "orchestrator"),
    path.join(os.homedir(), ".config", "opencode"),
    path.join(os.homedir(), ".claude"),
  ];

  for (const dir of configDirs) {
    if (fs.existsSync(dir)) {
      const files = fs.readdirSync(dir, { recursive: true });
      for (const file of files) {
        const fullPath = path.join(dir, file);
        if (fs.statSync(fullPath).isFile() && (file.endsWith(".json") || file.endsWith(".toml") || file.endsWith(".yaml") || file.endsWith(".yml"))) {
          try {
            const content = fs.readFileSync(fullPath, "utf8");
            const errors = checkFile(path.relative(process.cwd(), fullPath), content);
            allErrors.push(...errors);
          } catch (e) {
            // skip unreadable
          }
        }
      }
    }
  }

  if (allErrors.length > 0) {
    console.error("❌ Config validation failed:");
    for (const e of allErrors) {
      console.error(`  ${e.file}:${e.line} - ${e.issue}`);
      console.error(`    ${e.content}`);
    }
    process.exit(1);
  } else {
    console.log("✅ Config validation passed: no platform-incorrect paths found");
  }
}

validate();
