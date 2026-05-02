import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { PublicOnlyRoute } from "./components/PublicOnlyRoute";
import { AnomalyDetail } from "./pages/AnomalyDetail";
import { AnomalyList } from "./pages/AnomalyList";
import { Connect } from "./pages/Connect";
import { Dashboard } from "./pages/Dashboard";
import { Feedback } from "./pages/Feedback";
import { Incidents } from "./pages/Incidents";
import { Landing } from "./pages/Landing";
import { Login } from "./pages/Login";
import { Settings } from "./pages/Settings";
import { Signup } from "./pages/Signup";
import { System } from "./pages/System";
import { Training } from "./pages/Training";
import { Upload } from "./pages/Upload";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 5s stale time so opening a detail panel immediately after a list
      // refresh doesn't refetch the same data.
      staleTime: 5_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Public routes — no Layout, no auth required */}
          <Route path="/" element={<Landing />} />
          <Route
            path="/login"
            element={
              <PublicOnlyRoute>
                <Login />
              </PublicOnlyRoute>
            }
          />
          <Route
            path="/signup"
            element={
              <PublicOnlyRoute>
                <Signup />
              </PublicOnlyRoute>
            }
          />

          {/* Protected dashboard routes — Layout (sidebar) wraps these */}
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/anomalies" element={<AnomalyList />} />
            <Route path="/anomalies/:id" element={<AnomalyDetail />} />
            <Route path="/feedback" element={<Feedback />} />
            <Route path="/upload" element={<Upload />} />
            <Route path="/connect" element={<Connect />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/admin/system" element={<System />} />
            <Route path="/admin/training" element={<Training />} />
            <Route path="/admin/incidents" element={<Incidents />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
