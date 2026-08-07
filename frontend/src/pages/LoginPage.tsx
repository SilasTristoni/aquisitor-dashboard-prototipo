import { Activity, ArrowRight, CheckCircle2, LockKeyhole, ShieldCheck, Thermometer, Zap } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";
import { loadClientConfig } from "../clientConfig";

export default function LoginPage() {
  const { user, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [version, setVersion] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    loadClientConfig()
      .then((config) => {
        if (!active) return;
        setVersion(config.version);
        if (config.login_prefill.enabled) {
          setEmail(config.login_prefill.email ?? "");
          setPassword(config.login_prefill.password ?? "");
        }
      })
      .catch(() => {
        if (active) setError("Não foi possível carregar a configuração desta build.");
      });
    return () => { active = false; };
  }, []);
  if (user) return <Navigate to="/" replace />;
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(""); setLoading(true);
    try { await login(email, password); } catch (err) { setError(err instanceof Error ? err.message : "Falha no acesso"); } finally { setLoading(false); }
  }
  return <main className="login-shell">
    <section className="login-visual">
      <div className="login-brand"><span><Activity /></span><div><strong>ThermoPower</strong><small>MONITOR</small></div></div>
      <div className="login-copy"><p className="eyebrow light">MONITORAMENTO INDUSTRIAL</p><h1>Precisão que transforma dados em decisões.</h1><p>Aquisição confiável de potência e temperatura, rastreabilidade integral e análise em tempo real.</p><div className="login-benefits"><span><Zap /> Potência normalizada</span><span><Thermometer /> 32 termopares</span><span><ShieldCheck /> Operação auditável</span></div></div>
      <div className="signal-art" aria-hidden="true"><i /><i /><i /><i /><div className="signal-line" /></div>
      <small className="login-version">ThermoPower Monitor{version ? ` · Versão ${version}` : ""}</small>
    </section>
    <section className="login-form-wrap"><form className="login-card" onSubmit={submit}><div className="login-icon"><LockKeyhole /></div><p className="eyebrow">ACESSO SEGURO</p><h2>Bem-vindo de volta</h2><p className="form-intro">Entre para acessar o ambiente de monitoramento.</p>
      <label><span>E-mail</span><input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
      <label><span>Senha</span><input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} /></label>
      {error && <div className="form-error" role="alert">{error}</div>}
      <button className="button primary login-submit" disabled={loading}>{loading ? "Autenticando…" : <>Entrar no sistema <ArrowRight /></>}</button>
      <div className="demo-credentials"><CheckCircle2 /><div><strong>Ambiente de demonstração</strong><span>Credenciais preenchidas automaticamente.</span></div></div>
    </form></section>
  </main>;
}
