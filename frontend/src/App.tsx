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

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/anomalies" element={<AnomalyList />} />
          <Route path="/anomalies/:id" element={<AnomalyDetail />} />
          <Route path="/system" element={<System />} />
          <Route path="/feedback" element={<Feedback />} />
          <Route path="/training" element={<Training />} />
          <Route path="/incidents" element={<Incidents />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
