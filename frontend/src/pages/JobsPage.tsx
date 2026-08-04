import {
  ArrowUpRight,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Filter,
  MapPin,
  RotateCcw,
  Search,
} from "lucide-react";
import {
  useState,
  type FormEvent,
} from "react";
import { Link } from "react-router";

import { TrackJobButton } from "../features/applications/TrackJobButton";
import { useJobs } from "../features/jobs/use-jobs";
import type {
  JobListParameters,
  JobSummary,
} from "../features/jobs/types";

const PAGE_SIZE = 20;

function parseList(value: string): string[] | undefined {
  const values = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  return values.length > 0 ? values : undefined;
}

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
  const [skillsValue, setSkillsValue] = useState("");
  const [regionsValue, setRegionsValue] = useState("");
  const [employmentType, setEmploymentType] =
    useState("");
  const [experienceLevel, setExperienceLevel] =
    useState("");
  const [minimumSalary, setMinimumSalary] =
    useState("");
  const [salaryCurrency, setSalaryCurrency] =
    useState("");
  const [filterError, setFilterError] =
    useState<string | null>(null);
  const [filters, setFilters] =
    useState<JobListParameters>({});
  const [offset, setOffset] = useState(0);

  const jobsQuery = useJobs({
    ...filters,
    limit: PAGE_SIZE,
    offset,
  });

  const total = jobsQuery.data?.total ?? 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(
    1,
    Math.ceil(total / PAGE_SIZE),
  );

  function submitFilters(
    event: FormEvent<HTMLFormElement>,
  ): void {
    event.preventDefault();
    setFilterError(null);

    const salary =
      minimumSalary === ""
        ? undefined
        : Number(minimumSalary);

    if (
      salary !== undefined &&
      (Number.isNaN(salary) || salary < 0)
    ) {
      setFilterError(
        "Minimum salary must be zero or greater.",
      );
      return;
    }

    const currency = salaryCurrency
      .trim()
      .toUpperCase();

    if (
      currency !== "" &&
      !/^[A-Z]{3}$/.test(currency)
    ) {
      setFilterError(
        "Currency must use three letters, such as USD.",
      );
      return;
    }

    if (salary !== undefined && currency === "") {
      setFilterError(
        "Currency is required with minimum salary.",
      );
      return;
    }

    setFilters({
      search: searchValue.trim() || undefined,
      skills: parseList(skillsValue),
      remoteRegions: parseList(regionsValue),
      employmentType: employmentType || undefined,
      experienceLevel: experienceLevel || undefined,
      minimumSalary: salary,
      salaryCurrency: currency || undefined,
    });

    setOffset(0);
  }

  function clearFilters(): void {
    setSearchValue("");
    setSkillsValue("");
    setRegionsValue("");
    setEmploymentType("");
    setExperienceLevel("");
    setMinimumSalary("");
    setSalaryCurrency("");
    setFilterError(null);
    setFilters({});
    setOffset(0);
  }

  return (
    <main className="page-content">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Job discovery</p>
          <h1>Remote opportunities</h1>
          <p>
            Search and filter active remote jobs collected by
            RemoteMatch.
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
        className="jobs-filter-form"
        onSubmit={submitFilters}
      >
        <div className="job-search">
          <Search aria-hidden="true" size={20} />

          <input
            type="search"
            value={searchValue}
            onChange={(event) =>
              setSearchValue(event.target.value)
            }
            placeholder="Search title, company, or keyword"
            aria-label="Search jobs"
          />

          <button type="submit">Search</button>
        </div>

        <div className="advanced-filters">
          <div className="filter-heading">
            <span>
              <Filter aria-hidden="true" size={17} />
              Filters
            </span>

            <button
              type="button"
              onClick={clearFilters}
            >
              <RotateCcw
                aria-hidden="true"
                size={15}
              />
              Clear
            </button>
          </div>

          <div className="filter-grid">
            <div className="form-field">
              <label htmlFor="job-skills">Skills</label>

              <input
                id="job-skills"
                type="text"
                value={skillsValue}
                onChange={(event) =>
                  setSkillsValue(event.target.value)
                }
                placeholder="Python, FastAPI"
              />

              <p className="field-hint">
                Separate skills with commas.
              </p>
            </div>

            <div className="form-field">
              <label htmlFor="remote-regions">
                Remote regions
              </label>

              <input
                id="remote-regions"
                type="text"
                value={regionsValue}
                onChange={(event) =>
                  setRegionsValue(event.target.value)
                }
                placeholder="Europe, Worldwide"
              />
            </div>

            <div className="form-field">
              <label htmlFor="employment-type">
                Employment type
              </label>

              <select
                id="employment-type"
                value={employmentType}
                onChange={(event) =>
                  setEmploymentType(event.target.value)
                }
              >
                <option value="">Any type</option>
                <option value="full_time">
                  Full time
                </option>
                <option value="part_time">
                  Part time
                </option>
                <option value="contract">
                  Contract
                </option>
                <option value="internship">
                  Internship
                </option>
              </select>
            </div>

            <div className="form-field">
              <label htmlFor="job-experience">
                Experience
              </label>

              <select
                id="job-experience"
                value={experienceLevel}
                onChange={(event) =>
                  setExperienceLevel(event.target.value)
                }
              >
                <option value="">Any level</option>
                <option value="no_experience">
                  No experience
                </option>
                <option value="internship">
                  Internship
                </option>
                <option value="entry_level">
                  Entry level
                </option>
                <option value="junior">Junior</option>
                <option value="mid_level">
                  Mid level
                </option>
                <option value="senior">Senior</option>
              </select>
            </div>

            <div className="form-field">
              <label htmlFor="job-minimum-salary">
                Minimum salary
              </label>

              <input
                id="job-minimum-salary"
                type="number"
                min="0"
                value={minimumSalary}
                onChange={(event) =>
                  setMinimumSalary(event.target.value)
                }
                placeholder="30000"
              />
            </div>

            <div className="form-field">
              <label htmlFor="job-currency">
                Currency
              </label>

              <input
                id="job-currency"
                type="text"
                maxLength={3}
                value={salaryCurrency}
                onChange={(event) =>
                  setSalaryCurrency(event.target.value)
                }
                placeholder="USD"
              />
            </div>
          </div>

          {filterError && (
            <p className="field-error" role="alert">
              {filterError}
            </p>
          )}

          <button
            className="primary-button filter-submit"
            type="submit"
          >
            <Filter aria-hidden="true" size={17} />
            Apply filters
          </button>
        </div>
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
            Make sure the API and database are running.
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
          <p>Try changing or clearing the filters.</p>

          <button
            className="secondary-button"
            type="button"
            onClick={clearFilters}
          >
            Clear filters
          </button>
        </div>
      )}

      {jobsQuery.data &&
        jobsQuery.data.items.length > 0 && (
          <>
            <section className="jobs-grid">
              {jobsQuery.data.items.map((job) => {
                const salary = formatSalary(job);
                const visibleSkills =
                  job.skills.slice(0, 6);
                const remainingSkills =
                  job.skills.length -
                  visibleSkills.length;

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
                        <span key={skill}>
                          {skill}
                        </span>
                      ))}

                      {remainingSkills > 0 && (
                        <span>
                          +{remainingSkills}
                        </span>
                      )}
                    </div>

                    <div className="job-card-actions">
                      <TrackJobButton jobId={job.id} />

                      <Link
                        className="job-link"
                        to={`/jobs/${job.id}`}
                      >
                        View details
                        <ArrowUpRight
                          aria-hidden="true"
                          size={17}
                        />
                      </Link>
                    </div>
                  </article>
                );
              })}
            </section>

            {totalPages > 1 && (
              <nav
                className="pagination"
                aria-label="Job results pages"
              >
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() =>
                    setOffset((currentOffset) =>
                      Math.max(
                        0,
                        currentOffset - PAGE_SIZE,
                      ),
                    )
                  }
                >
                  <ChevronLeft
                    aria-hidden="true"
                    size={17}
                  />
                  Previous
                </button>

                <span>
                  Page {currentPage} of {totalPages}
                </span>

                <button
                  type="button"
                  disabled={
                    offset + PAGE_SIZE >= total
                  }
                  onClick={() =>
                    setOffset(
                      (currentOffset) =>
                        currentOffset + PAGE_SIZE,
                    )
                  }
                >
                  Next
                  <ChevronRight
                    aria-hidden="true"
                    size={17}
                  />
                </button>
              </nav>
            )}
          </>
        )}
    </main>
  );
}