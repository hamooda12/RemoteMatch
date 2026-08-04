import {
  BriefcaseBusiness,
  ClipboardList,
  FileText,
  LayoutDashboard,
  LogOut,
  Radar,
  Target,
  UserRound,
} from "lucide-react";
import {
  NavLink,
  Outlet,
  useNavigate,
} from "react-router";

import {
  useCurrentUser,
  useLogout,
} from "../features/auth/use-auth";

const navigationItems = [
  {
    to: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
  },
  {
    to: "/matches",
    label: "Matches",
    icon: Target,
  },
  {
    to: "/jobs",
    label: "All jobs",
    icon: BriefcaseBusiness,
  },
  {
    to: "/applications",
    label: "Applications",
    icon: ClipboardList,
  },
  {
    to: "/cv",
    label: "My CV",
    icon: FileText,
  },
  {
    to: "/profile",
    label: "Profile",
    icon: UserRound,
  },
];

export function AppLayout() {
  const navigate = useNavigate();
  const currentUserQuery = useCurrentUser();
  const logoutMutation = useLogout();

  const user = currentUserQuery.data;

  const initials =
    user?.display_name
      .split(" ")
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("") ?? "RM";

  async function handleLogout(): Promise<void> {
    try {
      await logoutMutation.mutateAsync();
      navigate("/login", { replace: true });
    } catch {
      return;
    }
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <NavLink className="sidebar-brand" to="/dashboard">
          <span className="brand-icon">
            <Radar aria-hidden="true" size={23} />
          </span>

          <span>RemoteMatch</span>
        </NavLink>

        <nav
          className="sidebar-navigation"
          aria-label="Main navigation"
        >
          {navigationItems.map((item) => {
            const Icon = item.icon;

            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  isActive
                    ? "sidebar-link sidebar-link-active"
                    : "sidebar-link"
                }
              >
                <Icon aria-hidden="true" size={19} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="sidebar-account">
          <div className="account-avatar">{initials}</div>

          <div className="account-details">
            <strong>{user?.display_name}</strong>
            <span>{user?.email}</span>
          </div>

          <button
            className="logout-button"
            type="button"
            aria-label="Sign out"
            title="Sign out"
            onClick={handleLogout}
            disabled={logoutMutation.isPending}
          >
            <LogOut aria-hidden="true" size={19} />
          </button>
        </div>

        {logoutMutation.error && (
          <p className="sidebar-error" role="alert">
            Sign out failed.
          </p>
        )}
      </aside>

      <div className="app-main">
        <header className="app-topbar">
          <p>Remote job workspace</p>
        </header>

        <Outlet />
      </div>
    </div>
  );
}