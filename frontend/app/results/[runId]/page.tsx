import Link from "next/link";

import { ResultsPanel } from "../../../components/results-panel";

type ResultsPageProps = {
  params: { runId: string };
};

export default function ResultsPage({ params }: ResultsPageProps) {
  return (
    <main className="container page-stack">
      <h1 className="page-title">Results {params.runId}</h1>
      <ResultsPanel runId={params.runId} />
      <div className="top-links">
        <Link href={`/inspect/${params.runId}`}>Inspect artifacts, extracted figures, and asset-map decisions</Link>
        <Link href={`/run/${params.runId}`}>Back to run status</Link>
        <Link href="/">New job</Link>
      </div>
    </main>
  );
}
