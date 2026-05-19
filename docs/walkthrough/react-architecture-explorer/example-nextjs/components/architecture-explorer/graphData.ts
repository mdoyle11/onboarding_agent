import architectureGraphDataJson from "./architectureGraphs.json";

import type { ArchitectureGraphData, ExplorerGraphRegistry } from "./types";

export const architectureGraphData = architectureGraphDataJson as unknown as ArchitectureGraphData;
export const architectureGraphs = architectureGraphData.graphs as ExplorerGraphRegistry;

export default architectureGraphData;
