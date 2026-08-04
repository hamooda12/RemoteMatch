import {
  ArrowUpRight,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  MapPin,
  Search,
} from "lucide-react";
import {
  useState,
  type FormEvent,
} from "react";

import { TrackJobButton } from "../features/applications/TrackJobButton";
import { useJobs } from "../features/jobs/use-jobs";
import type { JobSummary } from "../features/jobs/types";
import { Link } from "react-router";

function formatDate(value: string | null): string {
  if (!value) {
    return "Recently added";
  }

  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
  }).format(new Date(value));
}

function formatSalary(job: JobSummary): string | null {
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

export function JobsPage() {
  const [searchValue, setSearchValue] = useState("");
  const [submittedSearch, setSubmittedSearch] =
    useState("");

  const jobsQuery = useJobs({
    search: submittedSearch || undefined,
    limit: 20,
    offset: 0,
  });

  function submitSearch(
    event: FormEvent<HTMLFormElement>,
  ): void {
    event.preventDefault();
    setSubmittedSearch(searchValue.trim());
  }

  return (
    <main className="page-content">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Job discovery</p>
          <h1>Remote opportunities</h1>
          <p>
            Browse active remote jobs collected by RemoteMatch.
          </p>
        </div>

        {jobsQuery.data && (
          <div className="result-count">
            <strong>{jobsQuery.data.total}</strong>
            <span>active jobs</span>
          </div>
        )}
      </section>

      <form
        className="job-search"
        onSubmit={submitSearch}
        role="search"
      >
        <Search aria-hidden="true" size={20} />

        <input
          type="search"
          value={searchValue}
          onChange={(event) =>
            setSearchValue(event.target.value)
          }
          placeholder="Search by title, company, or keyword"
          aria-label="Search jobs"
        />

        <button type="submit">Search</button>
      </form>

      {jobsQuery.isPending && (
        <div className="page-state" aria-busy="true">
          <BriefcaseBusiness
            aria-hidden="true"
            size={30}
          />
          <p>Loading remote jobs...</p>
        </div>
      )}

      {jobsQuery.isError && (
        <div
          className="page-state page-state-error"
          role="alert"
        >
          <h2>Jobs could not be loaded</h2>

          <p>
            Make sure the FastAPI server and PostgreSQL database
            are running.
          </p>

          <button
            className="secondary-button"
            type="button"
            onClick={() => jobsQuery.refetch()}
          >
            Try again
          </button>
        </div>
      )}

      {jobsQuery.data?.items.length === 0 && (
        <div className="page-state">
          <Search aria-hidden="true" size={30} />
          <h2>No jobs found</h2>
          <p>Try a different search term.</p>
        </div>
      )}

      {jobsQuery.data &&
        jobsQuery.data.items.length > 0 && (
          <section className="jobs-grid">
            {jobsQuery.data.items.map((job) => {
              const salary = formatSalary(job);
              const visibleSkills = job.skills.slice(0, 6);

              const remainingSkills =
                job.skills.length - visibleSkills.length;

              return (
                <article
                  className="job-card"
                  key={job.id}
                >
                  <div className="job-card-heading">
                    <div className="company-icon">
                      <Building2
                        aria-hidden="true"
                        size={22}
                      />
                    </div>

                    <span className="job-source">
                      {job.source_name}
                    </span>
                  </div>

                  <div>
                    <h2>{job.title}</h2>

                    <p className="company-name">
                      {job.company_name}
                    </p>
                  </div>

                  <div className="job-metadata">
                    <span>
                      <MapPin
                        aria-hidden="true"
                        size={16}
                      />
                      {job.location ?? "Remote"}
                    </span>

                    <span>
                      <CalendarDays
                        aria-hidden="true"
                        size={16}
                      />

                      {formatDate(
                        job.published_at ??
                          job.first_seen_at,
                      )}
                    </span>
                  </div>

                  {salary && (
                    <p className="job-salary">
                      {salary}
                    </p>
                  )}

                  <div className="skill-tags">
                    {visibleSkills.map((skill) => (
                      <span key={skill}>{skill}</span>
                    ))}

                    {remainingSkills > 0 && (
                      <span>+{remainingSkills}</span>
                    )}
                  </div>

                  <div className="job-card-actions">
                    <TrackJobButton jobId={job.id} />

                  <Link
  className="job-link"
  to={`/jobs/${job.id}`}
>
  View details
  <ArrowUpRight aria-hidden="true" size={17} />
</Link>
                  </div>
                </article>
              );
            })}
          </section>
        )}
    </main>
  );
}