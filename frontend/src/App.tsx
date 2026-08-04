import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";

const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const ImportPage = lazy(() => import("./pages/ImportPage"));
const MeasurementsPage = lazy(() => import("./pages/MeasurementsPage"));
const SessionDetailPage = lazy(() => import("./pages/SessionDetailPage"));
const SessionsPage = lazy(() => import("./pages/SessionsPage"));
const management = () => import("./pages/ManagementPages");
const AlertsPage = lazy(() => management().then((module) => ({ default: module.AlertsPage })));
const ChannelsPage = lazy(() => management().then((module) => ({ default: module.ChannelsPage })));
const ComparePage = lazy(() => management().then((module) => ({ default: module.ComparePage })));
const DevicesPage = lazy(() => management().then((module) => ({ default: module.DevicesPage })));
const DiagnosticsPage = lazy(() => management().then((module) => ({ default: module.DiagnosticsPage })));
const EventsPage = lazy(() => management().then((module) => ({ default: module.EventsPage })));
const ExecutivePage = lazy(() => management().then((module) => ({ default: module.ExecutivePage })));
const ReportsPage = lazy(() => management().then((module) => ({ default: module.ReportsPage })));
const UsersPage = lazy(() => management().then((module) => ({ default: module.UsersPage })));

function ProtectedLayout() {
  const { user, loading } = useAuth();
  if (loading) return <div className="boot-screen"><Spinner label="Preparando ambiente seguro" /></div>;
  return user ? <Layout /> : <Navigate to="/login" replace />;
}

function AdminOnly() {
  const { user } = useAuth();
  return user?.role === "admin" ? <UsersPage /> : <Navigate to="/" replace />;
}

export default function App() {
  return <Suspense fallback={<div className="boot-screen"><Spinner label="Carregando módulo" /></div>}><Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<ProtectedLayout />}>
      <Route index element={<DashboardPage />} />
      <Route path="executivo" element={<ExecutivePage />} />
      <Route path="sessoes" element={<SessionsPage />} />
      <Route path="sessoes/:id" element={<SessionDetailPage />} />
      <Route path="medicoes" element={<MeasurementsPage />} />
      <Route path="importar" element={<ImportPage />} />
      <Route path="equipamentos" element={<DevicesPage />} />
      <Route path="canais" element={<ChannelsPage />} />
      <Route path="alertas" element={<AlertsPage />} />
      <Route path="eventos" element={<EventsPage />} />
      <Route path="relatorios" element={<ReportsPage />} />
      <Route path="comparacao" element={<ComparePage />} />
      <Route path="usuarios" element={<AdminOnly />} />
      <Route path="diagnostico" element={<DiagnosticsPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Route>
  </Routes></Suspense>;
}
