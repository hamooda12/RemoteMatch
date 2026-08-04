import type { PropsWithChildren } from "react";
import { BriefcaseBusiness, FileSearch, Radar } from "lucide-react";
import { Link } from "react-router";

type AuthLayoutProps = PropsWithChildren<{
  title: string;
  description: string;
}>;

export function AuthLayout({
  title,
  description,
  children,
}: AuthLayoutProps) {
  return (
    <main className="auth-layout">
      <aside className="auth-introduction">
        <Link className="brand" to="/">
          <span className="brand-icon">
            <Radar aria-hidden="true" size={24} />
          </span>
          <span>RemoteMatch</span>
        </Link>

        <div className="auth-introduction-content">
          <p className="eyebrow">Your remote career workspace</p>

          <h1>Find work that matches your actual experience.</h1>

          <p>
            RemoteMatch analyzes your CV, compares your skills
            with remote opportunities, and keeps every
            application organized.
          </p>

          <ul className="feature-list">
            <li>
              <FileSearch aria-hidden="true" size={20} />
              CV-based skill extraction
            </li>

            <li>
              <BriefcaseBusiness
                aria-hidden="true"
                size={20}
              />
              Personalized remote job matching
            </li>
          </ul>
        </div>
      </aside>

      <section className="auth-panel">
        <div className="auth-card">
          <div className="auth-card-heading">
            <h2>{title}</h2>
            <p>{description}</p>
          </div>

          {children}
        </div>
      </section>
    </main>
  );
}