// Fixture stand-in for the board CLI: prints the file named by WV_FIX_BOARD, or exits 3 when it is "FAIL".
import fs from "node:fs";
const f = process.env.WV_FIX_BOARD;
if (!f || f === "FAIL") { console.error("fixture failure"); process.exit(3); }
process.stdout.write(fs.readFileSync(f, "utf8"));
