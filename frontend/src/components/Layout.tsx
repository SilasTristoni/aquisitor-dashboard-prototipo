import {
  Activity, AlertTriangle, BarChart3, Bell, Boxes, ChevronRight, CircleGauge, ClipboardList,
  Database, FileBarChart, FileUp, GitCompareArrows, LogOut, Menu, Moon, RadioTower, Settings2, Sun,
  Thermometer, Users, X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth";

const navigation = [
  { to: "/", label: "Tempo real", icon: Activity },
  { to: "/executivo", label: "Visão executiva", icon: BarChart3 },
  { to: "/sessoes", label: "Sessões", icon: ClipboardList },
  { to: "/medicoes", label: "Medições", icon: Database },
  { to: "/importar", label: "Importar arquivos", icon: FileUp },
  { to: "/equipamentos", label: "Equipamentos", icon: RadioTower },
  { to: "/canais", label: "Termopares", icon: Thermometer },
  { to: "/alertas", label: "Alertas", icon: Bell },
  { to: "/eventos", label: "Eventos e logs", icon: Boxes },
  { to: "/relatorios", label: "Relatórios", icon: FileBarChart },
  { to: "/comparacao", label: "Comparar sessões", icon: GitCompareArrows },
  { to: "/usuarios", label: "Usuários", icon: Users, admin: true },
  { to: "/diagnostico", label: "Diagnóstico", icon: CircleGauge },
];

const titles: Record<string, string> = { executivo: "Visão executiva", sessoes: "Sessões", medicoes: "Medições", importar: "Importar arquivos", equipamentos: "Equipamentos", canais: "Termopares", alertas: "Alertas", eventos: "Eventos", relatorios: "Relatórios", comparacao: "Comparação", usuarios: "Usuários", diagnostico: "Diagnóstico", "configuracao-inicial": "Configuração inicial" };

export default function Layout() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useState(() => localStorage.getItem("thermopower.theme") === "dark");
  useEffect(() => { document.documentElement.dataset.theme = dark ? "dark" : "light"; localStorage.setItem("thermopower.theme", dark ? "dark" : "light"); }, [dark]);
  useEffect(() => setOpen(false), [location.pathname]);
  const segment = location.pathname.split("/")[1];
  return <div className="app-shell">
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="brand"><span className="brand-mark"><Activity /></span><div><strong>ThermoPower</strong><small>MONITOR</small></div><button className="mobile-close" aria-label="Fechar menu" onClick={() => setOpen(false)}><X /></button></div>
      <nav aria-label="Navegação principal">{navigation.filter((item) => !item.admin || user?.role === "admin").map((item) => <NavLink key={item.to} to={item.to} end={item.to === "/"}><item.icon /><span>{item.label}</span></NavLink>)}</nav>
      <div className="sidebar-status"><i /><div><strong>Sistema operacional</strong><small>Backend monitorado</small></div></div>
      <div className="profile"><span>{user?.name.slice(0, 2).toUpperCase()}</span><div><strong>{user?.name}</strong><small>{user?.role === "admin" ? "Administrador" : user?.role === "operator" ? "Operador" : "Visualizador"}</small></div><button onClick={logout} aria-label="Sair"><LogOut /></button></div>
    </aside>
    {open && <button className="sidebar-backdrop" onClick={() => setOpen(false)} aria-label="Fechar menu" />}
    <main className="main-content">
      <header className="topbar"><button className="menu-button" aria-label="Abrir menu" onClick={() => setOpen(true)}><Menu /></button><div className="breadcrumbs"><span>ThermoPower</span><ChevronRight /><strong>{titles[segment] ?? "Tempo real"}</strong></div><div className="topbar-actions"><span className="system-pill"><i /> Online</span><button className="icon-button" onClick={() => setDark(!dark)} aria-label="Alternar tema">{dark ? <Sun /> : <Moon />}</button><Link className="icon-button" to="/configuracao-inicial" aria-label="Configuração inicial"><Settings2 /></Link><button className="icon-button warning-dot" aria-label="Alertas"><AlertTriangle /></button></div></header>
      <div className="page"><Outlet /></div>
    </main>
  </div>;
}
