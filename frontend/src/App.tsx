import { Navigate, Route, Routes } from "react-router";

import { ProtectedRoute } from "./components/ProtectedRoute";
import { AppLayout } from "./layouts/AppLayout";
import { ApplicationsPage } from "./pages/ApplicationsPage";
import { CVPage } from "./pages/CVPage";
import { DashboardPage } from "./pages/DashboardPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { JobsPage } from "./pages/JobsPage";
import { LoginPage } from "./pages/LoginPage";
import { MatchesPage } from "./pages/MatchesPage";
import { ProfilePage } from "./pages/ProfilePage";
import { RegisterPage } from "./pages/RegisterPage";

function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={<Navigate to="/dashboard" replace />}
      />

      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route
            path="/dashboard"
            element={<DashboardPage />}
          />

          <Route path="/jobs" element={<JobsPage />} />

          <Route
            path="/jobs/:jobId"
            element={<JobDetailPage />}
          />

          <Route
            path="/matches"
            element={<MatchesPage />}
          />

          <Route
            path="/applications"
            element={<ApplicationsPage />}
          />

          <Route path="/cv" element={<CVPage />} />

          <Route
            path="/profile"
            element={<ProfilePage />}
          />
        </Route>
      </Route>

      <Route
        path="*"
        element={<Navigate to="/dashboard" replace />}
      />
    </Routes>
  );
}

export default App;