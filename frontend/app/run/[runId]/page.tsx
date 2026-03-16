import Link from "next/link";

import { RunStatus } from "../../../components/run-status";

type RunPageProps = {
  params: { runId: string };
};

export default function RunPage({ params }: RunPageProps) {
  return (
    <main className="container page-stack">
      <h1 className="page-title">Run {params.runId}</h1>
      <RunStatus runId={params.runId} />
      <Link href="/">Back to submission</Link>
    </main>
  );
}
