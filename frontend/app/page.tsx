import { JobForm } from "../components/job-form";

export default function HomePage() {
  return (
    <main className="container page-stack">
      <section className="hero">
        <h1 className="page-title">paper2slides</h1>
        <p className="page-subtitle">Submit a paper-processing job, tune run controls, and track end-to-end status with stricter evidence grounding.</p>
      </section>
      <JobForm />
    </main>
  );
}
