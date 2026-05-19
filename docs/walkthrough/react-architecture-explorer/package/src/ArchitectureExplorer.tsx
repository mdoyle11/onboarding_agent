"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import styles from "./ArchitectureExplorer.module.css";
import type {
  ArchitectureExplorerProps,
  ExplorerGraph,
  ExplorerGraphKey,
  ExplorerGraphRegistry,
} from "./types";

type MermaidModule = typeof import("mermaid");

type PanZoomState = {
  scale: number;
  x: number;
  y: number;
};

let mermaidConfigured = false;

function normalizeText(value: string) {
  return value.replace(/\s+/g, " ").trim().toLowerCase();
}

function parseNodeLabels(code: string) {
  const labels = new Map<string, string>();
  const matches = code.matchAll(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\["([^"]+)"\]/gm);
  for (const match of matches) {
    labels.set(match[1], match[2]);
  }
  return labels;
}

function configureMermaid(mermaid: MermaidModule["default"]) {
  if (mermaidConfigured) return;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "loose",
    theme: "base",
    themeVariables: {
      fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      primaryColor: "#e8f3ff",
      primaryTextColor: "#18202a",
      primaryBorderColor: "#93c5fd",
      lineColor: "#52606d",
      secondaryColor: "#ecfdf3",
      tertiaryColor: "#fff7e6",
    },
    flowchart: {
      htmlLabels: true,
      curve: "basis",
      rankSpacing: 76,
      nodeSpacing: 34,
    },
  });
  mermaidConfigured = true;
}

function buildDiagramCode(graph: ExplorerGraph, graphs: ExplorerGraphRegistry) {
  let code = graph.code.trim();
  if (graph.parentKey && graph.reconcileFrom && graphs[graph.parentKey]) {
    const parentTitle = graphs[graph.parentKey].title.replace(/"/g, "'");
    code += `\n    parentReconcile["Reconcile to: ${parentTitle}"]`;
    code += `\n    ${graph.reconcileFrom} -- "returns to parent flow" --> parentReconcile`;
  }
  return code;
}

function fitState(viewport: HTMLDivElement | null, svg: SVGSVGElement | null): PanZoomState {
  if (!viewport || !svg) {
    return { scale: 1, x: 24, y: 24 };
  }
  const viewportRect = viewport.getBoundingClientRect();
  const svgRect = svg.getBoundingClientRect();
  const width = svgRect.width || svg.viewBox.baseVal.width || 1000;
  const height = svgRect.height || svg.viewBox.baseVal.height || 600;
  const scale = Math.min(
    (viewportRect.width - 48) / width,
    (viewportRect.height - 48) / height,
    1.1,
  );
  return {
    scale: Math.max(scale, 0.1),
    x: 24,
    y: 24,
  };
}

function nodeGraphMapFor(graph: ExplorerGraph) {
  const nodeToGraph = { ...(graph.drillNodes || {}) };
  if (graph.parentKey) {
    nodeToGraph.parentReconcile = graph.parentKey;
  }
  return nodeToGraph;
}

function resolveTargetKeyForNode(
  node: SVGGElement,
  nodeToGraph: Record<string, ExplorerGraphKey>,
  sourceLabels: Map<string, string>,
) {
  const nodeId = String(node.id || "").toLowerCase();
  const text = normalizeText(node.textContent || "");

  for (const [mermaidId, graphKey] of Object.entries(nodeToGraph)) {
    const normalizedId = mermaidId.toLowerCase();
    if (
      nodeId === normalizedId ||
      nodeId.includes(`-${normalizedId}-`) ||
      nodeId.endsWith(`-${normalizedId}`)
    ) {
      return graphKey;
    }
  }

  for (const [mermaidId, graphKey] of Object.entries(nodeToGraph)) {
    const sourceLabel = sourceLabels.get(mermaidId);
    if (sourceLabel && normalizeText(sourceLabel) === text) {
      return graphKey;
    }
  }

  for (const [mermaidId, graphKey] of Object.entries(nodeToGraph)) {
    const normalizedId = normalizeText(
      mermaidId.replace(/([A-Z])/g, " $1").replace(/[_-]/g, " "),
    );
    if (normalizedId === text) {
      return graphKey;
    }
  }

  return "";
}

export function ArchitectureExplorer({
  graphs,
  initialKey = "overview",
  heading = "Onboarding Agent Architecture Explorer",
  homeKey = "overview",
}: ArchitectureExplorerProps) {
  const [currentKey, setCurrentKey] = useState<ExplorerGraphKey>(initialKey);
  const [showSource, setShowSource] = useState(false);
  const [renderError, setRenderError] = useState("");

  const viewportRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const panZoomRef = useRef<PanZoomState>({ scale: 1, x: 24, y: 24 });
  const dragRef = useRef({ active: false, lastX: 0, lastY: 0 });

  const currentGraph = graphs[currentKey] ?? graphs[homeKey];
  const diagramCode = useMemo(
    () => buildDiagramCode(currentGraph, graphs),
    [currentGraph, graphs],
  );

  const breadcrumbs = useMemo(() => {
    const result: Array<{ key: ExplorerGraphKey; title: string }> = [];
    let key: ExplorerGraphKey | undefined = currentKey;
    const seen = new Set<string>();
    while (key && graphs[key] && !seen.has(key)) {
      seen.add(key);
      result.unshift({ key, title: graphs[key].title });
      key = graphs[key].parentKey;
    }
    return result;
  }, [currentKey, graphs]);

  const sourceClassName = showSource
    ? `${styles.source} ${styles.sourceVisible}`
    : styles.source;

  function applyTransform() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const { x, y, scale } = panZoomRef.current;
    canvas.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
  }

  function resetView() {
    const svg = canvasRef.current?.querySelector("svg") ?? null;
    panZoomRef.current = fitState(viewportRef.current, svg as SVGSVGElement | null);
    applyTransform();
  }

  function zoomAt(multiplier: number, clientX?: number, clientY?: number) {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const targetX = clientX ?? rect.left + rect.width / 2;
    const targetY = clientY ?? rect.top + rect.height / 2;
    const beforeX = (targetX - rect.left - panZoomRef.current.x) / panZoomRef.current.scale;
    const beforeY = (targetY - rect.top - panZoomRef.current.y) / panZoomRef.current.scale;
    panZoomRef.current.scale = Math.min(4, Math.max(0.08, panZoomRef.current.scale * multiplier));
    panZoomRef.current.x = targetX - rect.left - beforeX * panZoomRef.current.scale;
    panZoomRef.current.y = targetY - rect.top - beforeY * panZoomRef.current.scale;
    applyTransform();
  }

  useEffect(() => {
    let cancelled = false;

    async function renderDiagram() {
      const canvas = canvasRef.current;
      if (!canvas) return;
      setRenderError("");
      setShowSource(false);

      try {
        const mermaidModule = await import("mermaid");
        const mermaid = mermaidModule.default;
        configureMermaid(mermaid);
        const rendered = await mermaid.render(`diagram-${currentKey}`, diagramCode);
        if (cancelled) return;
        canvas.innerHTML = rendered.svg;

        const graph = currentGraph;
        const nodeToGraph = nodeGraphMapFor(graph);
        const sourceLabels = parseNodeLabels(diagramCode);
        const svg = canvas.querySelector("svg");
        if (svg) {
          svg.querySelectorAll<SVGGElement>(".node").forEach((node) => {
            const targetKey = resolveTargetKeyForNode(node, nodeToGraph, sourceLabels);
            if (!targetKey || !graphs[targetKey]) return;
            node.dataset.drillKey = targetKey;
            node.setAttribute("tabindex", "0");
            node.setAttribute("role", "button");
            node.setAttribute("aria-label", `Open ${graphs[targetKey].title}`);
            node.style.cursor = "pointer";
          });

          svg.addEventListener("click", (event) => {
            const target = event.target as Element | null;
            const node = target?.closest(".node") as SVGGElement | null;
            const drillKey = node?.dataset.drillKey;
            if (!drillKey || !graphs[drillKey]) return;
            event.preventDefault();
            event.stopPropagation();
            setCurrentKey(drillKey);
          });

          svg.addEventListener("keydown", (event) => {
            const keyboardEvent = event as KeyboardEvent;
            if (keyboardEvent.key !== "Enter" && keyboardEvent.key !== " ") return;
            const target = event.target as Element | null;
            const node = target?.closest(".node") as SVGGElement | null;
            const drillKey = node?.dataset.drillKey;
            if (!drillKey || !graphs[drillKey]) return;
            event.preventDefault();
            setCurrentKey(drillKey);
          });
        }

        resetView();
      } catch (error) {
        if (cancelled) return;
        setRenderError(error instanceof Error ? error.message : String(error));
      }
    }

    renderDiagram();
    return () => {
      cancelled = true;
    };
  }, [currentKey, currentGraph, diagramCode, graphs]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Element | null;
      if (target?.closest(".node")) {
        return;
      }
      dragRef.current = { active: true, lastX: event.clientX, lastY: event.clientY };
      viewport?.setPointerCapture(event.pointerId);
    }

    function onPointerMove(event: PointerEvent) {
      if (!dragRef.current.active) return;
      panZoomRef.current.x += event.clientX - dragRef.current.lastX;
      panZoomRef.current.y += event.clientY - dragRef.current.lastY;
      dragRef.current.lastX = event.clientX;
      dragRef.current.lastY = event.clientY;
      applyTransform();
    }

    function onPointerUp() {
      dragRef.current.active = false;
    }

    function onWheel(event: WheelEvent) {
      event.preventDefault();
      zoomAt(event.deltaY < 0 ? 1.12 : 0.88, event.clientX, event.clientY);
    }

    function onDoubleClick() {
      resetView();
    }

    viewport.addEventListener("pointerdown", onPointerDown);
    viewport.addEventListener("pointermove", onPointerMove);
    viewport.addEventListener("pointerup", onPointerUp);
    viewport.addEventListener("wheel", onWheel, { passive: false });
    viewport.addEventListener("dblclick", onDoubleClick);

    return () => {
      viewport.removeEventListener("pointerdown", onPointerDown);
      viewport.removeEventListener("pointermove", onPointerMove);
      viewport.removeEventListener("pointerup", onPointerUp);
      viewport.removeEventListener("wheel", onWheel);
      viewport.removeEventListener("dblclick", onDoubleClick);
    };
  }, []);

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <h1 className={styles.heading}>{heading}</h1>
          <div className={styles.crumbs}>
            {breadcrumbs.map((item, index) =>
              index === breadcrumbs.length - 1 ? (
                <span className={styles.crumbCurrent} key={item.key}>
                  {item.title}
                </span>
              ) : (
                <button
                  className={styles.crumbButton}
                  key={item.key}
                  onClick={() => setCurrentKey(item.key)}
                  type="button"
                >
                  {item.title}
                </button>
              ),
            )}
          </div>
        </div>
      </header>

      <main className={styles.layout}>
        <aside className={styles.aside}>
          <div className={styles.navSection}>
            <h2 className={styles.navHeading}>Graphs</h2>
            {Object.entries(graphs).map(([key, graph]) => {
              const buttonClass =
                key === currentKey
                  ? `${styles.navButton} ${styles.navButtonActive}`
                  : styles.navButton;
              return (
                <button
                  className={buttonClass}
                  key={key}
                  onClick={() => setCurrentKey(key)}
                  type="button"
                >
                  {graph.title}
                </button>
              );
            })}
          </div>

          <div className={styles.navSection}>
            <h2 className={styles.navHeading}>Legend</h2>
            <ul className={styles.legend}>
              <li className={styles.legendItem}>
                <span className={styles.swatch} />
                Application function or module
              </li>
              <li className={styles.legendItem}>
                <span className={styles.swatchState} />
                Durable state or queue
              </li>
              <li className={styles.legendItem}>
                <span className={styles.swatchExternal} />
                External service
              </li>
            </ul>
          </div>
        </aside>

        <section className={styles.content}>
          <article className={styles.panel}>
            <div className={styles.panelHeader}>
              <div className={styles.panelTitle}>
                <h2>{currentGraph.title}</h2>
                <p>{currentGraph.summary}</p>
              </div>
              <div className={styles.controls}>
                <button
                  className={styles.control}
                  onClick={() => setCurrentKey(homeKey)}
                  type="button"
                >
                  Overview
                </button>
                {currentGraph.parentKey ? (
                  <button
                    className={styles.control}
                    onClick={() => setCurrentKey(currentGraph.parentKey!)}
                    type="button"
                  >
                    Parent
                  </button>
                ) : null}
                <button className={styles.control} onClick={() => zoomAt(1.2)} type="button">
                  Zoom In
                </button>
                <button className={styles.control} onClick={() => zoomAt(0.8)} type="button">
                  Zoom Out
                </button>
                <button className={styles.control} onClick={resetView} type="button">
                  Reset
                </button>
                <button
                  className={styles.control}
                  onClick={() => setShowSource((value) => !value)}
                  type="button"
                >
                  Source
                </button>
              </div>
            </div>

            <div className={styles.viewport} ref={viewportRef}>
              <div className={styles.canvas} ref={canvasRef} />
              {renderError ? <div className={styles.error}>{renderError}</div> : null}
            </div>

            <pre className={sourceClassName}>{diagramCode}</pre>
            <div className={styles.hint}>{currentGraph.hint}</div>
          </article>

          <article className={styles.panel}>
            <div className={styles.copy}>
              <h3>What This Graph Explains</h3>
              {currentGraph.explanation.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
          </article>

          <article className={styles.panel}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Edge</th>
                  <th>Data Passed / Return / Side Effect</th>
                </tr>
              </thead>
              <tbody>
                {currentGraph.edges.map(([edge, description]) => (
                  <tr key={`${currentKey}-${edge}`}>
                    <td>
                      <code className={styles.inlineCode}>{edge}</code>
                    </td>
                    <td>{description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </article>
        </section>
      </main>
    </div>
  );
}

export default ArchitectureExplorer;
