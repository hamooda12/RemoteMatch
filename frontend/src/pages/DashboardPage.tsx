import {
  ArrowRight,
  BriefcaseBusiness,
  CheckCircle2,
  CircleAlert,
  ClipboardList,
  FileText,
  Target,
  UserRound,
} from "lucide-react";
import { Link } from "react-router";

import { useApplications } from "../features/applications/use-applications";
import { useCurrentUser } from "../features/auth/use-auth";
import { useCV } from "../features/cv/use-cv";
import { useJobs } from "../features/jobs/use-jobs";
import { useJobMatches } from "../features/matches/use-matches";
import { useProfile } from "../features/profile/use-profile";

export function DashboardPage() {
  const currentUserQuery = useCurrentUser();
  const jobsQuery = useJobs({
    limit: 1,
    offset: 0,
  });

  const applicationsQuery = useApplications();
  const profileQuery = useProfile();
  const cvQuery = useCV();

  const profileReady =
    profileQuery.data !== undefined &&
    profileQuery.data !== null;

  const cvReady =
    cvQuery.data?.parse_status === "processed";

  const matchingReady = profileReady && cvReady;

  const matchesQuery = useJobMatches(
    {
      minimumScore: 1,
      limit: 1,
      offset: 0,
    },
    matchingReady,
  );

  const user = currentUserQuery.data;

  if (!user) {
    return null;
  }

  const dashboardHasError =
    jobsQuery.isError ||
    applicationsQuery.isError ||
    profileQuery.isError ||
    cvQuery.isError ||
    matchesQuery.isError;

  const setupCompleted =
    Number(profileReady) + Number(cvReady);

  const setupPercentage = setupCompleted * 50;

  const recentApplications =
    applicationsQuery.data?.items.slice(0, 3) ?? [];

  return (
    <main className="page-content">
      <section className="dashboard-welcome">
        <p className="eyebrow">Dashboard</p>
        <h1>Welcome back, {user.display_name}</h1>
        <p>
          Monitor your job search and continue building your
          candidate profile.
        </p>
      </section>

      {dashboardHasError && (
        <div className="dashboard-warning" role="status">
          <CircleAlert aria-hidden="true" size={18} />
          Some dashboard information could not be loaded.
        </div>
      )}

      <section
        className="dashboard-statistics"
        aria-label="Job search summary"
      >
        <article className="dashboard-stat-card">
          <div className="stat-icon">
            <BriefcaseBusiness
              aria-hidden="true"
              size={21}
            />
          </div>

          <div>
            <span>Active jobs</span>
            <strong>
              {jobsQuery.data?.total ?? "—"}
            </strong>
          </div>
        </article>

        <article className="dashboard-stat-card">
          <div className="stat-icon">
            <Target aria-hidden="true" size={21} />
          </div>

          <div>
            <span>Job matches</span>
            <strong>
              {matchingReady
                ? matchesQuery.data?.total ?? "—"
                : "—"}
            </strong>
          </div>
        </article>

        <article className="dashboard-stat-card">
          <div className="stat-icon">
            <ClipboardList
              aria-hidden="true"
              size={21}
            />
          </div>

          <div>
            <span>Applications</span>
            <strong>
              {applicationsQuery.data?.total ?? "—"}
            </strong>
          </div>
        </article>

        <article className="dashboard-stat-card">
          <div className="stat-icon">
            <CheckCircle2
              aria-hidden="true"
              size={21}
            />
          </div>

          <div>
            <span>Setup progress</span>
            <strong>{setupPercentage}%</strong>
          </div>
        </article>
      </section>

      <div className="dashboard-grid">
        <section className="dashboard-panel">
          <div className="dashboard-panel-heading">
            <div>
              <p className="eyebrow">Candidate setup</p>
              <h2>Matching readiness</h2>
            </div>

            <span>{setupCompleted}/2 complete</span>
          </div>

          <div className="setup-progress">
            <span
              style={{
                width: `${setupPercentage}%`,
              }}
            />
          </div>

          <div className="setup-checklist">
            <Link
              className="setup-checklist-item"
              to="/profile"
            >
              <div
                className={
                  profileReady
                    ? "checklist-icon checklist-complete"
                    : "checklist-icon"
                }
              >
                {profileReady ? (
                  <CheckCircle2
                    aria-hidden="true"
                    size={20}
                  />
                ) : (
                  <UserRound
                    aria-hidden="true"
                    size={20}
                  />
                )}
              </div>

              <div>
                <strong>Candidate profile</strong>
                <span>
                  {profileReady
                    ? "Profile completed"
                    : "Add roles and preferences"}
                </span>
              </div>

              <ArrowRight
                aria-hidden="true"
                size={18}
              />
            </Link>

            <Link
              className="setup-checklist-item"
              to="/cv"
            >
              <div
                className={
                  cvReady
                    ? "checklist-icon checklist-complete"
                    : "checklist-icon"
                }
              >
                {cvReady ? (
                  <CheckCircle2
                    aria-hidden="true"
                    size={20}
                  />
                ) : (
                  <FileText
                    aria-hidden="true"
                    size={20}
                  />
                )}
              </div>

              <div>
                <strong>Processed CV</strong>
                <span>
                  {cvReady
                    ? "CV skills extracted"
                    : cvQuery.data
                      ? "CV requires processing"
                      : "Upload your CV"}
                </span>
              </div>

              <ArrowRight
                aria-hidden="true"
                size={18}
              />
            </Link>
          </div>

          {matchingReady && (
            <Link
              className="dashboard-primary-link"
              to="/matches"
            >
              View personalized matches
              <ArrowRight
                aria-hidden="true"
                size={18}
              />
            </Link>
          )}
        </section>

        <section className="dashboard-panel">
          <div className="dashboard-panel-heading">
            <div>
              <p className="eyebrow">Latest activity</p>
              <h2>Recent applications</h2>
            </div>

            <Link to="/applications">
              View all
            </Link>
          </div>

          {applicationsQuery.isPending && (
            <p className="dashboard-empty">
              Loading applications...
            </p>
          )}

          {!applicationsQuery.isPending &&
            recentApplications.length === 0 && (
              <div className="dashboard-empty">
                <ClipboardList
                  aria-hidden="true"
                  size={28}
                />

                <p>You are not tracking any jobs yet.</p>

                <Link to="/jobs">Browse jobs</Link>
              </div>
            )}

          {recentApplications.length > 0 && (
            <div className="recent-applications">
              {recentApplications.map(
                ({ application, job }) => (
                  <Link
                    className="recent-application"
                    to="/applications"
                    key={application.id}
                  >
                    <div>
                      <strong>{job.title}</strong>
                      <span>{job.company_name}</span>
                    </div>

                    <span
                      className={`application-status application-status-${application.status}`}
                    >
                      {application.status}
                    </span>
                  </Link>
                ),
              )}
            </div>
          )}
        </section>
      </div>

      <section className="dashboard-quick-actions">
        <Link to="/jobs">
          <BriefcaseBusiness
            aria-hidden="true"
            size={19}
          />
          Browse remote jobs
          <ArrowRight aria-hidden="true" size={17} />
        </Link>

        <Link to="/matches">
          <Target aria-hidden="true" size={19} />
          Review matches
          <ArrowRight aria-hidden="true" size={17} />
        </Link>

        <Link to="/applications">
          <ClipboardList
            aria-hidden="true"
            size={19}
          />
          Track applications
          <ArrowRight aria-hidden="true" size={17} />
        </Link>
      </section>
    </main>
  );
}