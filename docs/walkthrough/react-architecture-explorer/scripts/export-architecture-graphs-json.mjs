import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const rootDir = path.resolve(path.dirname(scriptPath), "..");
const sourcePath = path.join(rootDir, "data", "architectureGraphs.source.json");
const outputPath = path.join(rootDir, "package", "src", "architectureGraphs.json");

const sourceJson = JSON.parse(readFileSync(sourcePath, "utf8"));
const graphs = sourceJson.graphs ?? sourceJson;

const payload = {
  metadata: {
    project: "Onboarding Agent",
    source: "data/architectureGraphs.source.json",
    formatVersion: 1,
    generatedAt: new Date().toISOString(),
  },
  graphs,
};

writeFileSync(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(`Wrote ${outputPath}`);
