import {
  ArchitectureExplorer,
  architectureGraphs,
} from "../components/architecture-explorer";

export default function Page() {
  return (
    <ArchitectureExplorer
      graphs={architectureGraphs}
      initialKey="overview"
      homeKey="overview"
      heading="Onboarding Agent Architecture Explorer"
    />
  );
}
