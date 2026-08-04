import {
  Navigate,
  Outlet,
  useLocation,
} from "react-router";

import { useCurrentUser } from "../features/auth/use-auth";

export function ProtectedRoute() {
  const location = useLocation();
  const currentUserQuery = useCurrentUser();

  if (currentUserQuery.isPending) {
    return (
      <main aria-busy="true">
        <p>Checking your session...</p>
      </main>
    );
  }

  if (currentUserQuery.isError) {
    return (
      <main role="alert">
        <h1>Unable to connect</h1>
        <p>
          RemoteMatch could not contact the API. Make sure the
          backend is running.
        </p>
      </main>
    );
  }

  if (currentUserQuery.data === null) {
    return (
      <Navigate
        to="/login"
        replace
        state={{
          from: location.pathname,
        }}
      />
    );
  }

  return <Outlet />;
}