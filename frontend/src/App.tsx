import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Header } from "./components/Header";
import { KpiCards } from "./components/KpiCards";
import { TimelineChart } from "./components/TimelineChart";
import { AnomalyList } from "./components/AnomalyList";
import { AnomalyDetail } from "./components/AnomalyDetail";
import { useLiveAnomalies } from "./hooks/useLiveAnomalies";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      // 5s stale time so a fresh detail-panel open doesn't refetch
      // immediately after a list refresh.
      staleTime: 5_000,
      retry: 1,
    },
  },
});

function Shell() {
  const { status: wsStatus } = useLiveAnomalies();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="flex h-full flex-col">
      <Header wsStatus={wsStatus} />
      <main className="mx-auto w-full max-w-7xl flex-1 space-y-4 overflow-hidden p-4 md:p-6">
        <KpiCards />
        <TimelineChart />
        <div
          className="grid flex-1 gap-4 lg:grid-cols-2"
          style={{ minHeight: 600 }}
        >
          <AnomalyList selectedId={selectedId} onSelect={setSelectedId} />
          <AnomalyDetail anomalyId={selectedId} />
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <Shell />
    </QueryClientProvider>
  );
}
