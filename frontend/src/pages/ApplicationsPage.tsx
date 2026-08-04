import {
  ArrowUpRight,
  BriefcaseBusiness,
  CalendarDays,
  LoaderCircle,
  Save,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import {
  applicationStatuses,
  type ApplicationStatus,
  type TrackedJob,
} from "../features/applications/types";
import {
  useApplications,
  useDeleteApplication,
  useUpdateApplication,
} from "../features/applications/use-applications";

const statusLabels: Record<ApplicationStatus, string> = {
  saved: "Saved",
  applied: "Applied",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
};

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
  }).format(new Date(value));
}

function ApplicationCard({
  trackedJob,
}: {
  trackedJob: TrackedJob;
}) {
  const { application, job } = trackedJob;

  const [status, setStatus] =
    useState<ApplicationStatus>(application.status);

  const [notes, setNotes] = useState(
    application.notes ?? "",
  );

  const updateMutation = useUpdateApplication(
    application.id,
  );

  const deleteMutation = useDeleteApplication(
    application.id,
  );

 

  const hasChanges =
    status !== application.status ||
    notes.trim() !== (application.notes ?? "");

  async function saveChanges(): Promise<void> {
    let appliedAt = application.applied_at;

    if (status === "saved") {
      appliedAt = null;
    } else if (!appliedAt) {
      appliedAt = new Date().toISOString();
    }

    try {
      await updateMutation.mutateAsync({
        status,
        notes: notes.trim() || null,
        applied_at: appliedAt,
      });
    } catch {
      return;
    }
  }

  async function removeApplication(): Promise<void> {
    const confirmed = window.confirm(
      `Stop tracking "${job.title}"?`,
    );

    if (!confirmed) {
      return;
    }

    try {
      await deleteMutation.mutateAsync();
    } catch {
      return;
    }
  }

  return (
    <article className="application-card">
      <div className="application-card-header">
        <div>
          <span
            className={`application-status application-status-${application.status}`}
          >
            {statusLabels[application.status]}
          </span>

          <h2>{job.title}</h2>
          <p>{job.company_name}</p>
        </div>

        <a
          className="application-external-link"
          href={job.application_url ?? job.source_url}
          target="_blank"
          rel="noreferrer noopener"
          aria-label={`Open ${job.title}`}
        >
          <ArrowUpRight aria-hidden="true" size={19} />
        </a>
      </div>

      <div className="application-metadata">
        <span>
          <BriefcaseBusiness
            aria-hidden="true"
            size={15}
          />
          {job.employment_type ?? "Employment type unknown"}
        </span>

        <span>
          <CalendarDays aria-hidden="true" size={15} />
          Tracked {formatDate(application.created_at)}
        </span>

        {application.applied_at && (
          <span>
            Applied {formatDate(application.applied_at)}
          </span>
        )}
      </div>

      <div className="application-editor">
        <div className="form-field">
          <label htmlFor={`status-${application.id}`}>
            Application status
          </label>

          <select
            id={`status-${application.id}`}
            value={status}
            onChange={(event) =>
              setStatus(
                event.target.value as ApplicationStatus,
              )
            }
          >
            {applicationStatuses.map((statusValue) => (
              <option
                key={statusValue}
                value={statusValue}
              >
                {statusLabels[statusValue]}
              </option>
            ))}
          </select>
        </div>

        <div className="form-field">
          <label htmlFor={`notes-${application.id}`}>
            Private notes
          </label>

          <textarea
            id={`notes-${application.id}`}
            value={notes}
            maxLength={2000}
            rows={4}
            placeholder="Interview details, contact person, follow-up date..."
            onChange={(event) =>
              setNotes(event.target.value)
            }
          />

          <span className="character-count">
            {notes.length}/2000
          </span>
        </div>
      </div>

      {updateMutation.error && (
        <div className="form-error" role="alert">
          {updateMutation.error instanceof Error
            ? updateMutation.error.message
            : "Application could not be updated."}
        </div>
      )}

      {deleteMutation.error && (
        <div className="form-error" role="alert">
          {deleteMutation.error instanceof Error
            ? deleteMutation.error.message
            : "Application could not be removed."}
        </div>
      )}

      <div className="application-card-actions">
        <button
          className="danger-button"
          type="button"
          onClick={removeApplication}
          disabled={deleteMutation.isPending}
        >
          <Trash2 aria-hidden="true" size={17} />
          Remove
        </button>

        <button
          className="primary-button"
          type="button"
          onClick={saveChanges}
          disabled={
            !hasChanges || updateMutation.isPending
          }
        >
          {updateMutation.isPending ? (
            <>
              <LoaderCircle
                className="spinner"
                aria-hidden="true"
                size={17}
              />
              Saving...
            </>
          ) : (
            <>
              <Save aria-hidden="true" size={17} />
              Save changes
            </>
          )}
        </button>
      </div>
    </article>
  );
}

export function ApplicationsPage() {
  const [statusFilter, setStatusFilter] =
    useState<ApplicationStatus | "all">("all");

  const applicationsQuery = useApplications(
    statusFilter === "all"
      ? undefined
      : statusFilter,
  );

  return (
    <main className="page-content">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Application tracking</p>
          <h1>Your applications</h1>
          <p>
            Track saved jobs, submitted applications,
            interviews, offers, and rejections.
          </p>
        </div>

        {applicationsQuery.data && (
          <div className="result-count">
            <strong>{applicationsQuery.data.total}</strong>
            <span>tracked jobs</span>
          </div>
        )}
      </section>

      <section
        className="application-filters"
        aria-label="Application status filter"
      >
        <button
          type="button"
          className={
            statusFilter === "all"
              ? "application-filter-active"
              : ""
          }
          onClick={() => setStatusFilter("all")}
        >
          All
        </button>

        {applicationStatuses.map((status) => (
          <button
            key={status}
            type="button"
            className={
              statusFilter === status
                ? "application-filter-active"
                : ""
            }
            onClick={() => setStatusFilter(status)}
          >
            {statusLabels[status]}
          </button>
        ))}
      </section>

      {applicationsQuery.isPending && (
        <div className="page-state" aria-busy="true">
          <LoaderCircle
            className="spinner"
            aria-hidden="true"
            size={30}
          />
          <p>Loading applications...</p>
        </div>
      )}

      {applicationsQuery.isError && (
        <div
          className="page-state page-state-error"
          role="alert"
        >
          <h2>Applications could not be loaded</h2>

          <button
            className="secondary-button"
            type="button"
            onClick={() => applicationsQuery.refetch()}
          >
            Try again
          </button>
        </div>
      )}

      {applicationsQuery.data?.items.length === 0 && (
        <div className="page-state">
          <BriefcaseBusiness
            aria-hidden="true"
            size={32}
          />

          <h2>No applications found</h2>

          <p>
            Save a job from the Jobs or Matches page to start
            tracking it.
          </p>

          <Link className="primary-button" to="/jobs">
            Browse jobs
          </Link>
        </div>
      )}

      {applicationsQuery.data &&
        applicationsQuery.data.items.length > 0 && (
          <section className="applications-list">
            {applicationsQuery.data.items.map(
              (trackedJob) => (
               <ApplicationCard
  key={`${trackedJob.application.id}-${trackedJob.application.updated_at}`}
  trackedJob={trackedJob}
/>
              ),
            )}
          </section>
        )}
    </main>
  );
}