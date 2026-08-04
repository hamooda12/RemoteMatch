import {
  CheckCircle2,
  Download,
  FileText,
  LoaderCircle,
  RefreshCw,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-react";
import {
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";

import { downloadCV } from "../features/cv/cv-api";
import {
  useCV,
  useCVSkills,
  useDeleteCV,
  useParseCV,
  useUploadCV,
} from "../features/cv/use-cv";
import type { CVParseStatus } from "../features/cv/types";

const MAX_FILE_SIZE = 5 * 1024 * 1024;

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  const kilobytes = bytes / 1024;

  if (kilobytes < 1024) {
    return `${kilobytes.toFixed(1)} KB`;
  }

  return `${(kilobytes / 1024).toFixed(2)} MB`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function getStatusLabel(status: CVParseStatus): string {
  switch (status) {
    case "processed":
      return "Processed";

    case "failed":
      return "Processing failed";

    default:
      return "Waiting for processing";
  }
}

export function CVPage() {
  const fileInputReference =
    useRef<HTMLInputElement | null>(null);

  const [selectedFile, setSelectedFile] =
    useState<File | null>(null);

  const [fileError, setFileError] =
    useState<string | null>(null);

  const [downloadError, setDownloadError] =
    useState<string | null>(null);

  const [isDownloading, setIsDownloading] =
    useState(false);

  const cvQuery = useCV();
  const uploadMutation = useUploadCV();
  const parseMutation = useParseCV();
  const deleteMutation = useDeleteCV();

  const document = cvQuery.data;
  const isProcessed =
    document?.parse_status === "processed";

  const skillsQuery = useCVSkills(isProcessed);

  function selectFile(
    event: ChangeEvent<HTMLInputElement>,
  ): void {
    const file = event.target.files?.[0] ?? null;

    setFileError(null);
    setSelectedFile(null);

    if (!file) {
      return;
    }

    const filename = file.name.toLowerCase();
    const supported =
      filename.endsWith(".pdf") ||
      filename.endsWith(".docx");

    if (!supported) {
      setFileError(
        "Only PDF and DOCX files are supported.",
      );
      event.target.value = "";
      return;
    }

    if (file.size === 0) {
      setFileError("The selected file is empty.");
      event.target.value = "";
      return;
    }

    if (file.size > MAX_FILE_SIZE) {
      setFileError(
        "The CV cannot exceed 5 MiB.",
      );
      event.target.value = "";
      return;
    }

    setSelectedFile(file);
  }

  async function submitUpload(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();

    if (!selectedFile) {
      setFileError("Select a PDF or DOCX file.");
      return;
    }

    try {
      await uploadMutation.mutateAsync(selectedFile);

      setSelectedFile(null);
      setFileError(null);

      if (fileInputReference.current) {
        fileInputReference.current.value = "";
      }
    } catch {
      return;
    }
  }

  async function handleParse(): Promise<void> {
    try {
      await parseMutation.mutateAsync();
    } catch {
      return;
    }
  }

  async function handleDownload(): Promise<void> {
    if (!document) {
      return;
    }

    setDownloadError(null);
    setIsDownloading(true);

    try {
      const blob = await downloadCV();
      const objectURL = URL.createObjectURL(blob);
      const link = window.document.createElement("a");

      link.href = objectURL;
      link.download = document.original_filename;

      window.document.body.appendChild(link);
      link.click();
      link.remove();

      URL.revokeObjectURL(objectURL);
    } catch (error) {
      setDownloadError(
        error instanceof Error
          ? error.message
          : "The CV could not be downloaded.",
      );
    } finally {
      setIsDownloading(false);
    }
  }

  async function handleDelete(): Promise<void> {
    const confirmed = window.confirm(
      "Delete this CV and all extracted information?",
    );

    if (!confirmed) {
      return;
    }

    try {
      await deleteMutation.mutateAsync();
      setSelectedFile(null);
    } catch {
      return;
    }
  }

  return (
    <main className="page-content">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Candidate document</p>
          <h1>Your CV</h1>
          <p>
            Upload a searchable PDF or DOCX file so RemoteMatch
            can extract your skills and calculate personalized
            job matches.
          </p>
        </div>

        {document && (
          <div
            className={`cv-status cv-status-${document.parse_status}`}
          >
            {isProcessed && (
              <CheckCircle2
                aria-hidden="true"
                size={17}
              />
            )}

            {getStatusLabel(document.parse_status)}
          </div>
        )}
      </section>

      {cvQuery.isPending && (
        <div className="page-state" aria-busy="true">
          <LoaderCircle
            className="spinner"
            aria-hidden="true"
            size={30}
          />
          <p>Loading CV information...</p>
        </div>
      )}

      {cvQuery.isError && (
        <div
          className="page-state page-state-error"
          role="alert"
        >
          <h2>CV information could not be loaded</h2>

          <button
            className="secondary-button"
            type="button"
            onClick={() => cvQuery.refetch()}
          >
            Try again
          </button>
        </div>
      )}

      {!cvQuery.isPending && !cvQuery.isError && (
        <>
          {document && (
            <section className="cv-document-card">
              <div className="cv-file-icon">
                <FileText aria-hidden="true" size={30} />
              </div>

              <div className="cv-document-details">
                <h2>{document.original_filename}</h2>

                <div className="cv-document-metadata">
                  <span>
                    {formatBytes(document.size_bytes)}
                  </span>

                  <span>
                    {document.media_type.includes("pdf")
                      ? "PDF"
                      : "DOCX"}
                  </span>

                  <span>
                    Updated {formatDate(document.updated_at)}
                  </span>
                </div>
              </div>

              <div className="cv-document-actions">
                <button
                  className="secondary-button"
                  type="button"
                  onClick={handleDownload}
                  disabled={isDownloading}
                >
                  {isDownloading ? (
                    <LoaderCircle
                      className="spinner"
                      aria-hidden="true"
                      size={17}
                    />
                  ) : (
                    <Download
                      aria-hidden="true"
                      size={17}
                    />
                  )}

                  Download
                </button>

                <button
                  className="danger-button"
                  type="button"
                  onClick={handleDelete}
                  disabled={deleteMutation.isPending}
                >
                  <Trash2 aria-hidden="true" size={17} />
                  Delete
                </button>
              </div>
            </section>
          )}

          {downloadError && (
            <div className="form-error" role="alert">
              {downloadError}
            </div>
          )}

          {deleteMutation.error && (
            <div className="form-error" role="alert">
              {deleteMutation.error instanceof Error
                ? deleteMutation.error.message
                : "The CV could not be deleted."}
            </div>
          )}

          <form
            className="cv-upload-card"
            onSubmit={submitUpload}
          >
            <div className="cv-upload-icon">
              <UploadCloud aria-hidden="true" size={31} />
            </div>

            <div className="cv-upload-heading">
              <h2>
                {document
                  ? "Replace your CV"
                  : "Upload your CV"}
              </h2>

              <p>
                Select a searchable PDF or DOCX file. Maximum
                size: 5 MiB.
              </p>
            </div>

            <label className="cv-file-picker">
              <span>Choose file</span>

              <input
                ref={fileInputReference}
                type="file"
                accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={selectFile}
              />
            </label>

            {selectedFile && (
              <div className="selected-file" role="status">
                <FileText aria-hidden="true" size={18} />

                <span>
                  {selectedFile.name} ·{" "}
                  {formatBytes(selectedFile.size)}
                </span>
              </div>
            )}

            {fileError && (
              <p className="field-error">{fileError}</p>
            )}

            {uploadMutation.error && (
              <div className="form-error" role="alert">
                {uploadMutation.error instanceof Error
                  ? uploadMutation.error.message
                  : "The CV could not be uploaded."}
              </div>
            )}

            <button
              className="primary-button"
              type="submit"
              disabled={
                !selectedFile ||
                uploadMutation.isPending
              }
            >
              {uploadMutation.isPending ? (
                <>
                  <LoaderCircle
                    className="spinner"
                    aria-hidden="true"
                    size={18}
                  />
                  Uploading...
                </>
              ) : (
                <>
                  <UploadCloud
                    aria-hidden="true"
                    size={18}
                  />
                  {document ? "Replace CV" : "Upload CV"}
                </>
              )}
            </button>
          </form>

          {document &&
            document.parse_status !== "processed" && (
              <section className="cv-process-card">
                <div className="cv-process-icon">
                  <Sparkles aria-hidden="true" size={27} />
                </div>

                <div>
                  <h2>Process your CV</h2>
                  <p>
                    Extract searchable text and technical skills
                    used by the matching engine.
                  </p>
                </div>

                <button
                  className="primary-button"
                  type="button"
                  onClick={handleParse}
                  disabled={parseMutation.isPending}
                >
                  {parseMutation.isPending ? (
                    <>
                      <LoaderCircle
                        className="spinner"
                        aria-hidden="true"
                        size={18}
                      />
                      Processing...
                    </>
                  ) : (
                    <>
                      <RefreshCw
                        aria-hidden="true"
                        size={18}
                      />
                      Process CV
                    </>
                  )}
                </button>
              </section>
            )}

          {parseMutation.error && (
            <div className="form-error" role="alert">
              {parseMutation.error instanceof Error
                ? parseMutation.error.message
                : "The CV could not be processed."}
            </div>
          )}

          {isProcessed && (
            <section className="cv-skills-card">
              <div className="cv-skills-heading">
                <div>
                  <p className="eyebrow">
                    Extraction results
                  </p>
                  <h2>Detected skills</h2>
                </div>

                {skillsQuery.data && (
                  <span>
                    {skillsQuery.data.skill_count} skills
                  </span>
                )}
              </div>

              {skillsQuery.isPending && (
                <p>Loading extracted skills...</p>
              )}

              {skillsQuery.isError && (
                <div className="form-error" role="alert">
                  Extracted skills could not be loaded.
                </div>
              )}

              {skillsQuery.data &&
                skillsQuery.data.skills.length === 0 && (
                  <div className="empty-skills">
                    <p>
                      No supported skills were detected in this
                      CV.
                    </p>
                  </div>
                )}

              {skillsQuery.data &&
                skillsQuery.data.skills.length > 0 && (
                  <div className="extracted-skills">
                    {skillsQuery.data.skills.map((skill) => (
                      <span key={skill}>{skill}</span>
                    ))}
                  </div>
                )}

              {skillsQuery.data && (
                <p className="extraction-version">
                  Extraction version:{" "}
                  {skillsQuery.data.extraction_version}
                </p>
              )}
            </section>
          )}
        </>
      )}
    </main>
  );
}