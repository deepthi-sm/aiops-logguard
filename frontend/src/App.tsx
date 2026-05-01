import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AnomalyDetail } from "./pages/AnomalyDetail";
import { AnomalyList } from "./pages/AnomalyList";
import { Dashboard } from "./pages/Dashboard";
import { Feedback } from "./pages/Feedback";
import { Incidents } from "./pages/Incidents";
import { Settings } from "./pages/Settings";
import { System } from "./pages/System";
import { Training } from "./pages/Training";

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
          <Route element={<Layout />}>
            {/* User-facing routes */}
            <Route path="/" element={<Dashboard />} />
            <Route path="/anomalies" element={<AnomalyList />} />
            <Route path="/anomalies/:id" element={<AnomalyDetail />} />
            <Route path="/feedback" element={<Feedback />} />
            <Route path="/settings" element={<Settings />} />
            {/* Admin routes — operator / engineer-only views */}
            <Route path="/admin/system" element={<System />} />
            <Route path="/admin/training" element={<Training />} />
            <Route path="/admin/incidents" element={<Incidents />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
