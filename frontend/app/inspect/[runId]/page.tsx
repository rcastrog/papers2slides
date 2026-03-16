import Link from "next/link";

import { RunInspector } from "../../../components/run-inspector";

type InspectPageProps = {
  params: { runId: string };
};

export default function InspectPage({ params }: InspectPageProps) {
  return (
    <main className="container page-stack">
      <h1 className="page-title">Inspect run {params.runId}</h1>
      <p className="page-subtitle">
        Browse extracted source figures, asset-map decisions, and per-visual fallback status.
      </p>
      <RunInspector runId={params.runId} />
      <div className="top-links">
        <Link href={`/results/${params.runId}`}>Back to results</Link>
        <Link href={`/run/${params.runId}`}>Back to run status</Link>
      </div>
    </main>
  );
}
