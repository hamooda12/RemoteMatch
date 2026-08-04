import {
  ArrowLeft,
  ArrowUpRight,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  MapPin,
} from "lucide-react";
import {
  Link,
  useParams,
} from "react-router";

import { TrackJobButton } from "../features/applications/TrackJobButton";
import type { JobDetail } from "../features/jobs/types";
import { useJob } from "../features/jobs/use-jobs";

function formatDate(value: string | null): string {
  if (!value) {
    return "Not specified";
  }

  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
  }).format(new Date(value));
}

function formatSalary(job: JobDetail): string | null {
  if (
    job.salary_min === null &&
    job.salary_max === null
  ) {
    return null;
  }

  const formatter = new Intl.NumberFormat("en", {
    maximumFractionDigits: 0,
  });

  const minimum =
    job.salary_min !== null
      ? formatter.format(Number(job.salary_min))
      : null;

  const maximum =
    job.salary_max !== null
      ? formatter.format(Number(job.salary_max))
      : null;

  const currency = job.salary_currency ?? "";

  if (minimum && maximum) {
    return `${currency} ${minimum}–${maximum}`;
  }

  if (minimum) {
    return `From ${currency} ${minimum}`;
  }

  return `Up to ${currency} ${maximum}`;
}

function extractPlainText(value: string): string {
  const document = new DOMParser().parseFromString(
    value,
    "text/html",
  );

  return document.body.textContent?.trim() || value;
}

function formatValue(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) =>
      character.toUpperCase(),
    );
}

export function JobDetailPage() {
  const { jobId } = useParams();
  const jobQuery = useJob(jobId);

  if (jobQuery.isPending) {
    return (
      <main className="page-content">
        <div className="page-state" aria-busy="true">
          <BriefcaseBusiness
            aria-hidden="true"
            size={32}
          />
          <p>Loading job details...</p>
        </div>
      </main>
    );
  }

  if (jobQuery.isError || !jobQuery.data) {
    return (
      <main className="page-content">
        <div
          className="page-state page-state-error"
          role="alert"
        >
          <h1>Job could not be loaded</h1>
          <p>
            This opportunity may have expired or been removed.
          </p>

          <Link className="secondary-button" to="/jobs">
            Return to jobs
          </Link>
        </div>
      </main>
    );
  }

  const job = jobQuery.data;
  const salary = formatSalary(job);

  return (
    <main className="page-content">
      <Link className="back-link" to="/jobs">
        <ArrowLeft aria-hidden="true" size={18} />
        Back to jobs
      </Link>

      <article className="job-detail">
        <header className="job-detail-header">
          <div className="job-detail-company-icon">
            <Building2 aria-hidden="true" size={28} />
          </div>

          <div className="job-detail-heading">
            <p>{job.company_name}</p>
            <h1>{job.title}</h1>

            <div className="job-detail-metadata">
              <span>
                <MapPin aria-hidden="true" size={16} />
                {job.location ?? "Remote"}
              </span>

              {job.employment_type && (
                <span>
                  <BriefcaseBusiness
                    aria-hidden="true"
                    size={16}
                  />
                  {formatValue(job.employment_type)}
                </span>
              )}

              <span>
                <CalendarDays
                  aria-hidden="true"
                  size={16}
                />
                Published {formatDate(job.published_at)}
              </span>
            </div>
          </div>

          <div className="job-detail-actions">
            <TrackJobButton jobId={job.id} />

            <a
              className="primary-button"
              href={job.application_url ?? job.source_url}
              target="_blank"
              rel="noreferrer noopener"
            >
              Apply externally
              <ArrowUpRight
                aria-hidden="true"
                size={18}
              />
            </a>
          </div>
        </header>

        <div className="job-detail-body">
          <div className="job-detail-main">
            <section className="job-detail-section">
              <h2>Job description</h2>

              <p className="job-description">
                {extractPlainText(job.description)}
              </p>
            </section>

            {job.requirements && (
              <section className="job-detail-section">
                <h2>Requirements</h2>

                <p className="job-description">
                  {extractPlainText(job.requirements)}
                </p>
              </section>
            )}
          </div>

          <aside className="job-detail-sidebar">
            <section>
              <h2>Opportunity details</h2>

              <dl className="job-facts">
                <div>
                  <dt>Remote</dt>
                  <dd>{job.is_remote ? "Yes" : "No"}</dd>
                </div>

                <div>
                  <dt>Experience</dt>
                  <dd>
                    {job.experience_level
                      ? formatValue(job.experience_level)
                      : "Not specified"}
                  </dd>
                </div>

                <div>
                  <dt>Salary</dt>
                  <dd>{salary ?? "Not specified"}</dd>
                </div>

                <div>
                  <dt>Source</dt>
                  <dd>{job.source_name}</dd>
                </div>

                <div>
                  <dt>Expires</dt>
                  <dd>{formatDate(job.expires_at)}</dd>
                </div>
              </dl>
            </section>

            {job.remote_regions.length > 0 && (
              <section>
                <h2>Remote regions</h2>

                <div className="skill-tags">
                  {job.remote_regions.map((region) => (
                    <span key={region}>{region}</span>
                  ))}
                </div>
              </section>
            )}

            {job.skills.length > 0 && (
              <section>
                <h2>Skills</h2>

                <div className="skill-tags">
                  {job.skills.map((skill) => (
                    <span key={skill}>{skill}</span>
                  ))}
                </div>
              </section>
            )}
          </aside>
        </div>
      </article>
    </main>
  );
}