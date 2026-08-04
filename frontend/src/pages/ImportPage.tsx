import { CheckCircle2, FileSpreadsheet, FileText, UploadCloud } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, ErrorNotice, PageHeader, Panel, Spinner } from "../components/ui";

type Preview = {
  valid_rows: number;
  invalid_rows: number;
  start?: string;
  end?: string;
  mapping: Record<string, string>;
  errors: Array<{ row: number; field: string; message: string }>;
  rows: Array<Record<string, unknown>>;
};

export default function ImportPage() {
  const [thermal, setThermal] = useState<File | null>(null);
  const [electrical, setElectrical] = useState<File | null>(null);
  const [thermalPreview, setThermalPreview] = useState<Preview | null>(null);
  const [electricalPreview, setElectricalPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sessionId, setSessionId] = useState<number | null>(null);

  async function preview() {
    setBusy(true); setError(""); setSessionId(null);
    try {
      if (!thermal && !electrical) throw new Error("Selecione ao menos um arquivo.");
      const tasks: Promise<void>[] = [];
      if (thermal) {
        const body = new FormData(); body.append("file", thermal);
        tasks.push(api<Preview>("/imports/at4532/preview", { method: "POST", body }).then(setThermalPreview));
      } else setThermalPreview(null);
      if (electrical) {
        const body = new FormData(); body.append("file", electrical);
        tasks.push(api<Preview>("/imports/gpm8213/preview", { method: "POST", body }).then(setElectricalPreview));
      } else setElectricalPreview(null);
      await Promise.all(tasks);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha na prévia"); }
    finally { setBusy(false); }
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    if (thermal) form.append("at4532_file", thermal);
    if (electrical) form.append("gpm8213_file", electrical);
    try {
      const result = await api<{ session_id: number }>("/imports/session", { method: "POST", body: form });
      setSessionId(result.session_id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha na importação"); }
    finally { setBusy(false); }
  }

  const ready = Boolean((thermal && thermalPreview) || (electrical && electricalPreview));
  return <>
    <PageHeader eyebrow="IMPORTAÇÃO ASSISTIDA" title="Combinar arquivos dos equipamentos" description="Valide o TXT do GPM-8213 e o XLSX do AT4532 antes de persistir uma sessão." />
    {error && <ErrorNotice message={error} />}
    {sessionId && <div className="notice success"><CheckCircle2 /><div><strong>Importação concluída</strong><span>A sessão #{sessionId} foi criada com os dados válidos.</span></div><Link className="button primary" to={`/sessoes/${sessionId}`}>Abrir análise</Link></div>}
    <div className="import-grid">
      <FileCard title="Temperatura — AT4532" accept=".xlsx" icon={<FileSpreadsheet />} file={thermal} preview={thermalPreview} onFile={(file) => { setThermal(file); setThermalPreview(null); }} />
      <FileCard title="Elétrica — GPM-8213" accept=".txt,text/plain" icon={<FileText />} file={electrical} preview={electricalPreview} onFile={(file) => { setElectrical(file); setElectricalPreview(null); }} />
    </div>
    <div className="import-actions"><button className="button secondary" onClick={preview} disabled={busy || (!thermal && !electrical)}><UploadCloud /> Gerar pré-visualização</button>{busy && <Spinner label="Processando arquivos" />}</div>
    {ready && <form onSubmit={confirm}><Panel title="Confirmar nova sessão" kicker="ETAPA FINAL"><div className="form-grid"><label className="field"><span>Nome da sessão</span><input name="name" minLength={2} required placeholder="Ex.: Ensaio integrado 01" /></label><label className="field"><span>Grade de sincronização</span><select name="grid_ms" defaultValue="1000"><option value="500">500 ms</option><option value="1000">1 segundo</option><option value="2000">2 segundos</option></select></label><label className="field"><span>Tolerância de pareamento</span><select name="tolerance_ms" defaultValue="1500"><option value="500">500 ms</option><option value="1000">1 segundo</option><option value="1500">1,5 segundo</option><option value="3000">3 segundos</option></select></label><label className="field"><span>Descrição</span><input name="description" /></label></div><button className="button primary" disabled={busy}>Confirmar e criar sessão</button></Panel></form>}
  </>;
}

function FileCard({ title, accept, icon, file, preview, onFile }: { title: string; accept: string; icon: React.ReactNode; file: File | null; preview: Preview | null; onFile: (file: File | null) => void }) {
  return <Panel title={title} kicker="ARQUIVO DE ORIGEM"><label className="upload-drop">{icon}<strong>{file?.name ?? "Selecionar arquivo"}</strong><span>{file ? `${(file.size / 1024).toFixed(1)} KB` : `Formato aceito: ${accept.split(",")[0]}`}</span><input type="file" accept={accept} onChange={(event) => onFile(event.target.files?.[0] ?? null)} /></label>{preview && <div className="preview-summary"><div><Badge tone="success">{preview.valid_rows} válidas</Badge><Badge tone={preview.invalid_rows ? "danger" : "neutral"}>{preview.invalid_rows} inválidas</Badge></div><small>{preview.start ? `${new Date(preview.start).toLocaleString("pt-BR")} → ${new Date(preview.end!).toLocaleString("pt-BR")}` : "Sem período detectado"}</small><p><strong>Mapeamento:</strong> {Object.entries(preview.mapping).map(([key, value]) => `${key} → ${value}`).join(" · ")}</p>{preview.errors.slice(0, 4).map((issue) => <p className="import-error" key={`${issue.row}-${issue.message}`}>Linha {issue.row}: {issue.message}</p>)}</div>}</Panel>;
}
