export type ExplorerGraphKey = string;

export type ExplorerEdgeRow = [edge: string, description: string];

export interface ExplorerGraph {
  title: string;
  summary: string;
  hint: string;
  explanation: string[];
  code: string;
  edges: ExplorerEdgeRow[];
  parentKey?: ExplorerGraphKey;
  reconcileFrom?: string;
  drillNodes?: Record<string, ExplorerGraphKey>;
}

export type ExplorerGraphRegistry = Record<ExplorerGraphKey, ExplorerGraph>;

export interface ArchitectureGraphMetadata {
  project: string;
  source: string;
  formatVersion: number;
  generatedAt: string;
}

export interface ArchitectureGraphData {
  metadata: ArchitectureGraphMetadata;
  graphs: ExplorerGraphRegistry;
}

export interface ArchitectureExplorerProps {
  graphs: ExplorerGraphRegistry;
  initialKey?: ExplorerGraphKey;
  heading?: string;
  homeKey?: ExplorerGraphKey;
}
