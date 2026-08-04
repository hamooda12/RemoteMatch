import {
  ArrowUpRight,
  Check,
  CircleAlert,
  FileText,
  Target,
  UserRound,
  X,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { TrackJobButton } from "../features/applications/TrackJobButton";
import type { JobMatch } from "../features/matches/types";
import { useJobMatches } from "../features/matches/use-matches";
import { ApiError } from "../lib/api-client";

const scoreFilters = [1, 25, 50, 75];

type ScoreBarProps = {
  label: string;
  score: number;
  maximum: number;
};

function ScoreBar({
  label,
  score,
  maximum,
}: ScoreBarProps) {
  const percentage = Math.round(
    (score / maximum) * 100,
  );

  return (
    <div className="score-breakdown-row">
      <div className="score-breakdown-label">
        <span>{label}</span>

        <strong>
          {score}/{maximum}
        </strong>
      </div>

      <div className="score-bar">
        <span
          style={{
            width: `${percentage}%`,
          }}
        />
      </div>
    </div>
  );
}

function MatchCard({
  match,
}: {
  match: JobMatch;
}) {
  const job = match.job;

  return (
    <article className="match-card">
      <div className="match-card-header">
        <div className="match-score">
          <strong>{match.score}</strong>
          <span>match</span>
        </div>

        <div className="match-job-heading">
          <p>{job.company_name}</p>
          <h2>{job.title}</h2>

          <div className="match-job-meta">
            <span>{job.location ?? "Remote"}</span>

            {job.experience_level && (
              <span>{job.experience_level}</span>
            )}

            {job.employment_type && (
              <span>{job.employment_type}</span>
            )}
          </div>
        </div>

        <div className="match-header-actions">
          <TrackJobButton jobId={job.id} />

        <Link
  className="match-job-link"
  to={`/jobs/${job.id}`}
  aria-label={`View ${job.title}`}
>
  <ArrowUpRight aria-hidden="true" size={20} />
</Link>
        </div>
      </div>

      <div className="match-card-content">
        <section className="match-section">
          <h3>Score breakdown</h3>

          <div className="score-breakdown">
            <ScoreBar
              label="Skills"
              score={match.breakdown.skill_score}
              maximum={60}
            />

            <ScoreBar
              label="Target role"
              score={match.breakdown.role_score}
              maximum={20}
            />

            <ScoreBar
              label="Experience"
              score={
                match.breakdown.experience_score
              }
              maximum={10}
            />

            <ScoreBar
              label="Salary"
              score={match.breakdown.salary_score}
              maximum={10}
            />
          </div>
        </section>

        <section className="match-section">
          <h3>Skill comparison</h3>

          {match.matched_skills.length > 0 && (
            <div className="match-skill-group">
              <p>
                <Check aria-hidden="true" size={16} />
                Matched skills
              </p>

              <div className="skill-tags matched-skill-tags">
                {match.matched_skills.map(
                  (skill) => (
                    <span key={skill}>{skill}</span>
                  ),
                )}
              </div>
            </div>
          )}

          {match.missing_skills.length > 0 && (
            <div className="match-skill-group">
              <p>
                <CircleAlert
                  aria-hidden="true"
                  size={16}
                />
                Skills to improve
              </p>

              <div className="skill-tags missing-skill-tags">
                {match.missing_skills.map(
                  (skill) => (
                    <span key={skill}>{skill}</span>
                  ),
                )}
              </div>
            </div>
          )}

          {match.excluded_skills.length > 0 && (
            <div className="match-skill-group excluded-group">
              <p>
                <X aria-hidden="true" size={16} />
                Excluded technologies detected
              </p>

              <div className="skill-tags excluded-skill-tags">
                {match.excluded_skills.map(
                  (skill) => (
                    <span key={skill}>{skill}</span>
                  ),
                )}
              </div>
            </div>
          )}
        </section>
      </div>

      {match.reasons.length > 0 && (
        <section className="match-reasons">
          <h3>Why this score?</h3>

          <ul>
            {match.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

export function MatchesPage() {
  const [minimumScore, setMinimumScore] =
    useState(1);

  const matchesQuery = useJobMatches({
    minimumScore,
    limit: 20,
    offset: 0,
  });

  const error =
    matchesQuery.error instanceof ApiError
      ? matchesQuery.error
      : null;

  const setupRequired =
    error?.status === 409
      ? error.message
      : null;

  const profileRequired =
    setupRequired
      ?.toLowerCase()
      .includes("profile") ?? false;

  return (
    <main className="page-content">
      <section className="page-heading">
        <div>
          <p className="eyebrow">
            Personalized results
          </p>

          <h1>Your job matches</h1>

          <p>
            Opportunities ranked using your CV skills,
            target roles, experience level, and salary
            preferences.
          </p>
        </div>

        {matchesQuery.data && (
          <div className="result-count">
            <strong>
              {matchesQuery.data.total}
            </strong>

            <span>matching jobs</span>
          </div>
        )}
      </section>

      <section
        className="match-filter"
        aria-label="Minimum match score"
      >
        <span>Minimum score</span>

        <div className="score-filter-options">
          {scoreFilters.map((score) => (
            <button
              key={score}
              type="button"
              className={
                minimumScore === score
                  ? "score-filter-active"
                  : ""
              }
              onClick={() =>
                setMinimumScore(score)
              }
            >
              {score === 1
                ? "Any"
                : `${score}+`}
            </button>
          ))}
        </div>
      </section>

      {matchesQuery.isPending && (
        <div className="page-state" aria-busy="true">
          <Target aria-hidden="true" size={32} />
          <p>Calculating your matches...</p>
        </div>
      )}

      {setupRequired && (
        <section className="setup-required-card">
          <div className="setup-required-icon">
            {profileRequired ? (
              <UserRound
                aria-hidden="true"
                size={27}
              />
            ) : (
              <FileText
                aria-hidden="true"
                size={27}
              />
            )}
          </div>

          <div>
            <p className="eyebrow">
              Setup required
            </p>

            <h2>
              {profileRequired
                ? "Complete your profile"
                : "Upload and process your CV"}
            </h2>

            <p>{setupRequired}</p>

            <Link
              className="primary-button setup-required-link"
              to={
                profileRequired
                  ? "/profile"
                  : "/cv"
              }
            >
              {profileRequired
                ? "Open profile"
                : "Open CV manager"}
            </Link>
          </div>
        </section>
      )}

      {matchesQuery.isError &&
        !setupRequired && (
          <div
            className="page-state page-state-error"
            role="alert"
          >
            <h2>Matches could not be loaded</h2>

            <p>
              An unexpected error occurred while
              calculating your job matches.
            </p>

            <button
              className="secondary-button"
              type="button"
              onClick={() =>
                matchesQuery.refetch()
              }
            >
              Try again
            </button>
          </div>
        )}

      {matchesQuery.data?.items.length === 0 && (
        <div className="page-state">
          <Target aria-hidden="true" size={32} />
          <h2>No matches above this score</h2>

          <p>
            Choose a lower minimum score or update
            your candidate profile.
          </p>
        </div>
      )}

      {matchesQuery.data &&
        matchesQuery.data.items.length > 0 && (
          <section className="matches-list">
            {matchesQuery.data.items.map(
              (match) => (
                <MatchCard
                  key={match.job.id}
                  match={match}
                />
              ),
            )}
          </section>
        )}
    </main>
  );
}