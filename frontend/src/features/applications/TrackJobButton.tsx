import { BookmarkPlus, Check } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../lib/api-client";
import { useCreateApplication } from "./use-applications";

type TrackJobButtonProps = {
  jobId: string;
};

export function TrackJobButton({
  jobId,
}: TrackJobButtonProps) {
  const createMutation = useCreateApplication();
  const [isTracked, setIsTracked] = useState(false);

  async function trackJob(): Promise<void> {
    try {
      await createMutation.mutateAsync({
        job_id: jobId,
        status: "saved",
        notes: null,
        applied_at: null,
      });

      setIsTracked(true);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setIsTracked(true);
      }
    }
  }

  return (
    <div className="track-job-control">
      <button
        className={
          isTracked
            ? "track-job-button track-job-button-saved"
            : "track-job-button"
        }
        type="button"
        onClick={trackJob}
        disabled={isTracked || createMutation.isPending}
      >
        {isTracked ? (
          <>
            <Check aria-hidden="true" size={16} />
            Saved
          </>
        ) : (
          <>
            <BookmarkPlus aria-hidden="true" size={16} />
            {createMutation.isPending
              ? "Saving..."
              : "Save job"}
          </>
        )}
      </button>

      {createMutation.isError && !isTracked && (
        <span className="track-job-error" role="alert">
          Save failed
        </span>
      )}
    </div>
  );
}